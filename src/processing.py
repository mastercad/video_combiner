"""
Verarbeitung: create_ffmpeg_script, analyze_video_resolutions, extract_single_segment
"""

import multiprocessing
from collections import OrderedDict
import time
import subprocess
from pathlib import Path
import tqdm
from .ffmpeg_utils import retrieve_video_duration, extract_video_specs, is_video_file_complete
from .textclip import create_textclip
from .segment_utils import extract_date_from_filename
import os
import signal
from concurrent.futures import ProcessPoolExecutor, as_completed

# Modul-weites Tracking für ffmpeg-Prozesskontrolle
_concat_proc = None

# Cache für Hardware-Encoder-Erkennung
_hw_encoder = None


def detect_hw_encoder():
    """Erkennt automatisch den besten verfügbaren H.264-Encoder.

    Reihenfolge: h264_nvenc (NVIDIA) → libx264 (CPU-Fallback).
    Das Ergebnis wird gecacht.
    """
    global _hw_encoder
    if _hw_encoder is not None:
        return _hw_encoder

    # NVENC testen: kurzes Dummy-Encoding mit color-Source (erzeugt echte Frames)
    try:
        result = subprocess.run(
            ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=black:s=256x256:d=0.5:r=25',
             '-pix_fmt', 'yuv420p', '-c:v', 'h264_nvenc', '-f', 'null', '-'],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=10,
        )
        if result.returncode == 0:
            _hw_encoder = 'h264_nvenc'
            return _hw_encoder
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    _hw_encoder = 'libx264'
    return _hw_encoder


def _get_youtube_maxrate(width, height, fps):
    """Berechnet die optimale YouTube-Upload-Bitrate dynamisch anhand Auflösung und FPS.

    Orientiert sich an der tatsächlichen YouTube-Ausgabe-Bitrate (VP9/AV1),
    multipliziert mit ~1.3× als Qualitätsreserve für H.264→VP9-Transcodierung.

    YouTube re-encodiert zu VP9/AV1 (30-50% effizienter als H.264). Die
    tatsächlichen YouTube-Streaming-Bitraten liegen bei:
      2160p (4K)  30fps: ~15 Mbps   60fps: ~22 Mbps   (VP9)
      1440p       30fps: ~10 Mbps   60fps: ~15 Mbps
      1080p       30fps:  ~5 Mbps   60fps:  ~7 Mbps
       720p       30fps:  ~3 Mbps   60fps:  ~5 Mbps
       480p       30fps: ~1.5 Mbps  60fps:  ~2 Mbps
       360p       30fps: ~0.7 Mbps  60fps:  ~1 Mbps
    Mehr als ~1.3× davon in H.264 hochzuladen bringt keinen sichtbaren
    Qualitätsgewinn – YouTube re-encodiert alles.

    Returns:
        maxrate (int): Maximale Bitrate in Mbit/s
    """
    # Tabelle: (Mindest-Höhe, Upload-Bitrate 30fps, Upload-Bitrate 60fps)
    # Basierend auf realer YouTube-Ausgabe × ~1.3 Headroom
    yt_tiers = [
        (2160, 20, 30),   # YouTube VP9: ~15/~22 Mbps → Upload H.264: 20/30
        (1440, 13, 20),   # YouTube VP9: ~10/~15 Mbps → Upload H.264: 13/20
        (1080,  6.5, 9),  # YouTube VP9:  ~5/ ~7 Mbps → Upload H.264: 6.5/9
        (720,   4,  6.5), # YouTube VP9:  ~3/ ~5 Mbps → Upload H.264: 4/6.5
        (480,   2,  2.5), # YouTube VP9: ~1.5/~2 Mbps → Upload H.264: 2/2.5
        (360,   1,  1.3), # YouTube VP9: ~0.7/~1 Mbps → Upload H.264: 1/1.3
    ]
    pixel_height = min(width, height) if width < height else height  # Hochkant-Videos berücksichtigen
    high_fps = fps > 32  # YouTube unterscheidet <=30fps vs. höher

    # Exakten Tier finden oder linear zwischen zwei Tiers interpolieren
    for i, (tier_h, br_low, br_high) in enumerate(yt_tiers):
        if pixel_height >= tier_h:
            br = br_high if high_fps else br_low
            # Zwischen aktuellem und nächsthöherem Tier interpolieren
            if i > 0:
                upper_h, upper_br_low, upper_br_high = yt_tiers[i - 1]
                upper_br = upper_br_high if high_fps else upper_br_low
                if pixel_height < upper_h:
                    ratio = (pixel_height - tier_h) / (upper_h - tier_h)
                    br = br + ratio * (upper_br - br)
            return int(round(br))

    # Unterhalb 360p → Minimum
    return 1


def _build_video_encoder_args(quality='high', width=1920, height=1080, fps=30, no_bitrate_limit=False):
    """Gibt Video-Encoder-Argumente zurück (NVENC oder CPU, automatisch erkannt).

    quality:          'high' (Concat/Final) oder 'medium' (Segment-Extraktion)
    width:            Ziel-Breite in Pixel
    height:           Ziel-Höhe in Pixel
    fps:              Ziel-Framerate
    no_bitrate_limit: True → kein maxrate/bufsize (ignoriert YouTube-Empfehlungen)

    Bitrate-Limits werden dynamisch aus Auflösung und FPS berechnet,
    sofern no_bitrate_limit nicht gesetzt ist.
    """
    # Bitrate-Limit nur wenn gewünscht
    bitrate_args = []
    if not no_bitrate_limit:
        maxrate = _get_youtube_maxrate(width, height, fps)
        if quality != 'high':
            maxrate = max(1, int(round(maxrate * 0.65)))
        bufsize = maxrate * 2
        bitrate_args = ['-maxrate', f'{maxrate}M', '-bufsize', f'{bufsize}M']

    encoder = detect_hw_encoder()
    if encoder == 'h264_nvenc':
        base = ['-c:v', 'h264_nvenc', '-rc', 'vbr', '-pix_fmt', 'yuv420p']
        if quality == 'high':
            return base + [
                '-preset', 'p5',
                '-cq', '23',
                '-b:v', '0',
                *bitrate_args,
                '-profile:v', 'high',
                '-level', '5.1',
                '-movflags', '+faststart',
            ]
        else:
            return base + [
                '-preset', 'p4',
                '-cq', '28',
                '-b:v', '0',
                *bitrate_args,
            ]
    else:  # libx264 CPU-Fallback
        base = ['-c:v', 'libx264', '-pix_fmt', 'yuv420p']
        if quality == 'high':
            return base + [
                '-crf', '23',
                *bitrate_args,
                '-profile:v', 'high',
                '-level', '5.1',
                '-preset', 'medium',
                '-movflags', '+faststart',
            ]
        else:
            return base + [
                '-crf', '28',
                *bitrate_args,
                '-preset', 'medium',
            ]


def _build_audio_encoder_args(quality='high'):
    """Gibt Audio-Encoder-Argumente zurück.

    quality: 'high' → 160k, 'medium' → 128k
    """
    bitrate = '160k' if quality == 'high' else '128k'
    return ['-c:a', 'aac', '-b:a', bitrate, '-ar', '48000', '-ac', '2']


def build_encode_cmd(*, input_args, output_file, video_filter=None,
                     audio=True, quality='high', stream_copy=False,
                     width=1920, height=1080, fps=30, no_bitrate_limit=False):
    """Zentrale Funktion zum Erstellen eines ffmpeg-Encode-Kommandos.

    Args:
        input_args:       Liste von Input-Argumenten (z.B. ['-i', path])
        output_file:      Pfad zur Ausgabedatei
        video_filter:     Optionaler -vf String (z.B. 'scale=3840:2160,fps=30')
        audio:            True → encode, False → kein Audio, 'copy' → stream copy
        quality:          'high' (Final) oder 'medium' (Zwischenschritt)
        stream_copy:      True → kein Re-Encoding (kopiert Streams direkt)
        width:            Ziel-Breite in Pixel (für dynamische Bitrate-Berechnung)
        height:           Ziel-Höhe in Pixel
        fps:              Ziel-Framerate
        no_bitrate_limit: True → kein maxrate/bufsize (ignoriert YouTube-Empfehlungen)
    """
    cmd = ['ffmpeg', '-y']

    # CUDA HW-Decoding aktivieren wenn Re-Encoding mit NVENC
    if not stream_copy and detect_hw_encoder() == 'h264_nvenc':
        cmd.extend(['-hwaccel', 'cuda'])

    cmd.extend(list(input_args))

    if stream_copy:
        cmd.extend(['-c:v', 'copy'])
        if audio == 'copy' or audio is True:
            cmd.extend(['-c:a', 'copy'])
        else:
            cmd.append('-an')
    else:
        if video_filter:
            cmd.extend(['-vf', video_filter])
        cmd.extend(_build_video_encoder_args(quality=quality, width=width, height=height, fps=fps, no_bitrate_limit=no_bitrate_limit))
        if audio is True:
            cmd.extend(_build_audio_encoder_args(quality=quality))
        elif audio == 'copy':
            cmd.extend(['-c:a', 'copy'])
        else:
            cmd.append('-an')

    cmd.append(str(output_file))
    return cmd


def cancel_pipeline():
    """Bricht die laufende Pipeline ab und beendet alle ffmpeg-Kindprozesse."""
    global _concat_proc
    # Tracked concat-Prozess beenden
    if _concat_proc and _concat_proc.poll() is None:
        _concat_proc.terminate()
        try:
            _concat_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _concat_proc.kill()
    # Alle ffmpeg/ffprobe-Nachkommen über /proc finden und beenden
    _kill_descendant_ffmpeg()


def _kill_descendant_ffmpeg():
    """Beendet alle ffmpeg/ffprobe-Prozesse im Prozessbaum dieses Prozesses."""
    my_pid = os.getpid()
    try:
        pid_ppid = {}
        for entry in os.listdir('/proc'):
            if entry.isdigit():
                try:
                    with open(f'/proc/{entry}/stat') as f:
                        parts = f.read().split(')')
                        rest = parts[-1].split()
                        ppid = int(rest[1])
                        pid_ppid[int(entry)] = ppid
                except (FileNotFoundError, PermissionError, IndexError, ValueError):
                    pass
        descendants = set()
        queue = [my_pid]
        while queue:
            parent = queue.pop()
            for pid, ppid in pid_ppid.items():
                if ppid == parent and pid not in descendants:
                    descendants.add(pid)
                    queue.append(pid)
        for pid in descendants:
            try:
                with open(f'/proc/{pid}/comm') as f:
                    comm = f.read().strip()
                if comm in ('ffmpeg', 'ffprobe'):
                    os.kill(pid, signal.SIGTERM)
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                pass
    except Exception:
        pass

def analyze_video_resolutions(segments, input_dir, log_callback=None):
    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    log("\n=== Analysiere Video-Auflösungen ===")
    resolutions = []
    fps_values = []
    fps_raw_values = []
    codecs = []
    pixel_formats = []

    for idx, seg in enumerate(segments, 1):
        video_path = Path(input_dir) / seg['videoname']
        log(f"  Analysiere [{idx}/{len(segments)}]: {seg['videoname']}")
        if not video_path.exists():
            log(f"  ⚠️  {video_path} existiert nicht!")
            continue
        try:
            specs = extract_video_specs(str(video_path))
            resolutions.append((specs['width'], specs['height']))
            fps_values.append(specs['fps'])
            fps_raw_values.append(specs.get('fps_raw', str(int(specs['fps']))))
            codecs.append(specs.get('codec', 'unknown'))
            pixel_formats.append(specs.get('pix_fmt', 'unknown'))
            log(f"     {specs['width']}x{specs['height']} @ {specs['fps']}fps, {specs.get('codec', '?')}, {specs.get('pix_fmt', '?')}")
        except Exception as e:
            log(f"  ❌ Fehler beim Analysieren von {video_path}: {e}")

    if not resolutions:
        log("⚠️  Keine Videos gefunden - verwende Standardwerte 1920x1080@25fps")
        return 1920, 1080, 25, True, None, None, None

    min_width = min(r[0] for r in resolutions)
    min_height = min(r[1] for r in resolutions)
    max_width = max(r[0] for r in resolutions)
    max_height = max(r[1] for r in resolutions)

    # Prüfe ob alle Videos identische Specs haben
    all_same_resolution = (min_width == max_width and min_height == max_height)
    all_same_fps = len(set(fps_values)) == 1 if fps_values else False
    all_same_codec = len(set(codecs)) == 1 if codecs else False
    all_same_pixfmt = len(set(pixel_formats)) == 1 if pixel_formats else False

    needs_reencoding = not (all_same_resolution and all_same_fps and all_same_codec and all_same_pixfmt)

    if all_same_resolution:
        target_width = max_width
        target_height = max_height
        log(f"✓ Alle Videos haben {max_width}x{max_height}")
    else:
        target_width = max_width
        target_height = max_height
        log(f"✓ Verschiedene Auflösungen erkannt (min: {min_width}x{min_height}, max: {max_width}x{max_height})")
        log(f"  → Verwende höchste Auflösung: {target_width}x{target_height}")

    if fps_values:
        target_fps = int(round(min(fps_values)))
    else:
        target_fps = 25
    log(f"✓ FPS: {target_fps}")

    if not needs_reencoding:
        log(f"✓ Codec: {codecs[0]}, Pixel-Format: {pixel_formats[0]}")
        log(f"⚡ ALLE Videos haben identische Specs → Stream-Copy ohne Neuenkodierung (VIEL schneller!)")
    else:
        log(f"⚠️  Unterschiedliche Video-Specs erkannt → Neuenkodierung erforderlich")
        if not all_same_resolution:
            log(f"   - Auflösungen variieren")
        if not all_same_fps:
            log(f"   - FPS variieren: {set(fps_values)}")
        if not all_same_codec:
            log(f"   - Codecs variieren: {set(codecs)}")
        if not all_same_pixfmt:
            log(f"   - Pixel-Formate variieren: {set(pixel_formats)}")

    # Quell-Codec-Info für Textclip-Matching (nur wenn kein Re-Encoding nötig)
    source_codec = codecs[0] if codecs and not needs_reencoding else None
    source_pix_fmt = pixel_formats[0] if pixel_formats and not needs_reencoding else None
    source_fps_raw = fps_raw_values[0] if fps_raw_values and not needs_reencoding else None

    return target_width, target_height, target_fps, needs_reencoding, source_codec, source_pix_fmt, source_fps_raw

def extract_single_segment(args):
    if len(args) == 13:
        segment_info, segment_file, video_path, start_time, duration, target_width, target_height, target_fps, segment_audio, num_threads, youtube_opt, needs_reencoding, no_bitrate_limit = args
    elif len(args) == 12:
        segment_info, segment_file, video_path, start_time, duration, target_width, target_height, target_fps, segment_audio, num_threads, youtube_opt, needs_reencoding = args
        no_bitrate_limit = False
    elif len(args) == 11:
        segment_info, segment_file, video_path, start_time, duration, target_width, target_height, target_fps, segment_audio, num_threads, youtube_opt = args
        needs_reencoding = True
        no_bitrate_limit = False
    else:
        segment_info, segment_file, video_path, start_time, duration, target_width, target_height, target_fps, segment_audio, num_threads = args
        youtube_opt = True
        needs_reencoding = True
        no_bitrate_limit = False
    
    start = time.time()
    if is_video_file_complete(segment_file, expected_duration=duration):
        processing_time = time.time() - start
        return (segment_file, processing_time, True, None, True)
    
    try:
        # Gemeinsame Input-Argumente
        input_args = ['-ss', str(start_time), '-i', str(video_path), '-t', str(duration)]
        vf = f'scale={target_width}:{target_height},fps={target_fps}'

        if not needs_reencoding:
            # Alle Videos identisch → Stream-Copy (VIEL schneller!)
            extract_cmd = build_encode_cmd(
                input_args=input_args, output_file=segment_file,
                stream_copy=True,
                audio='copy' if segment_audio else False,
                width=target_width, height=target_height, fps=target_fps,
                no_bitrate_limit=no_bitrate_limit,
            )
        elif youtube_opt:
            # YouTube-Optimierung: Re-Encode Video + Audio
            extract_cmd = build_encode_cmd(
                input_args=input_args, output_file=segment_file,
                video_filter=vf, quality='medium',
                audio=segment_audio,
                width=target_width, height=target_height, fps=target_fps,
                no_bitrate_limit=no_bitrate_limit,
            )
        else:
            # Kein YouTube: Re-Encode Video, Audio kopieren
            extract_cmd = build_encode_cmd(
                input_args=input_args, output_file=segment_file,
                video_filter=vf, quality='medium',
                audio='copy' if segment_audio else False,
                width=target_width, height=target_height, fps=target_fps,
                no_bitrate_limit=no_bitrate_limit,
            )
        result = subprocess.run(extract_cmd, stdin=subprocess.DEVNULL, capture_output=True, check=True)
        processing_time = time.time() - start

        return (segment_file, processing_time, True, None, False)
    except subprocess.CalledProcessError as e:
        processing_time = time.time() - start

        return (segment_file, processing_time, False, str(e), False)
    except Exception as e:
        processing_time = time.time() - start

        return (segment_file, processing_time, False, str(e), False)

def assemble_ffmpeg_script(segments, input_dir, output_file, use_audio=True, target_width=1920, target_height=1080, target_fps=25, max_workers=None, debug_cache=False, youtube_opt=True, needs_reencoding=True, logo_path='input/teamlogo.png', log_callback=None, source_codec=None, source_pix_fmt=None, source_fps_raw=None, no_bitrate_limit=False):
    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    # Bestimme Anzahl der parallelen Worker (Standard: CPU-Kerne - 2, mindestens 1)
    if max_workers is None:
        cpu_count = multiprocessing.cpu_count()
        max_workers = max(1, cpu_count - 2)
    threads_per_process = max(1, multiprocessing.cpu_count() // max_workers)
    log(f"\n=== Starte Video-Verarbeitung ===")
    log(f"Ziel-Auflösung: {target_width}x{target_height}@{target_fps}fps")

    # Encoder erkennen und anzeigen
    encoder = detect_hw_encoder()
    if encoder == 'h264_nvenc':
        log(f"🎮 Encoder: NVIDIA NVENC + CUDA HW-Decoding (Hardware-beschleunigt)")
    else:
        log(f"🖥️  Encoder: libx264 (CPU)")
        log(f"   ℹ️  Für schnellere Verarbeitung (3-5x) wird eine NVIDIA GPU mit NVENC empfohlen.")
        log(f"   💡 Voraussetzungen für GPU-Beschleunigung:")
        log(f"      1. NVIDIA GPU (GeForce GTX 600+ / Quadro / Tesla)")
        log(f"      2. Aktuelle NVIDIA-Treiber: sudo apt install nvidia-driver-XXX (Linux)")
        log(f"         oder von https://www.nvidia.com/drivers (Windows)")
        log(f"      3. FFmpeg mit --enable-nvenc kompiliert (ffmpeg -encoders | grep nvenc)")

    log(f"CPU-Kerne verfügbar: {multiprocessing.cpu_count()}")
    log(f"Parallele Worker: {max_workers}")
    log(f"Threads pro FFmpeg-Prozess: {threads_per_process}")
    log(f"Ausgabe: {output_file}")
    segments_dir = Path("output/segments")
    segments_dir.mkdir(parents=True, exist_ok=True)
    all_files = []
    current_game_number = 1
    last_game_date = None
    chapters = []
    current_time = 0.0
    segment_number_in_game = 1
    game_groups = OrderedDict()
    for seg in segments:
        game_date = extract_date_from_filename(seg['videoname'])
        game_groups.setdefault(game_date, []).append(seg)
    game_info = {}
    for gdate, segs in game_groups.items():
        titles = [s.get('title') for s in segs if s.get('title') and isinstance(s.get('title'), str) and s.get('title').strip()]
        if len(titles) == len(segs) and len(segs) > 0:
            game_info[gdate] = {'per_video_titles': True, 'game_title': None}
        elif len(titles) > 0:
            game_info[gdate] = {'per_video_titles': False, 'game_title': titles[0]}
        else:
            game_info[gdate] = {'per_video_titles': False, 'game_title': None}
    total_segments = len(segments)
    start_time_overall = time.time()
    log(f"\n📋 Phase 1: Bereite Metadaten für {total_segments} Segmente vor...")
    segment_jobs = []
    segment_metadata = []
    existing_segments_count = 0
    for i, segment in enumerate(segments):
        videoname = segment['videoname']
        video_path = Path(input_dir) / videoname
        if not video_path.exists():
            log(f"⚠️  Überspringe {video_path} (existiert nicht)")
            continue
        this_game_date = extract_date_from_filename(segment['videoname'])
        if last_game_date is not None and this_game_date != last_game_date:
            current_game_number += 1
            segment_number_in_game = 1
        last_game_date = this_game_date
        ginfo = game_info.get(this_game_date, {'per_video_titles': False, 'game_title': None})
        seg_title = segment.get('title') if segment.get('title') and isinstance(segment.get('title'), str) and segment.get('title').strip() else None
        if seg_title:
            title = seg_title
        elif ginfo.get('game_title'):
            title = ginfo['game_title']
        else:
            title = f"Spiel {current_game_number}"
        sub = segment.get('sub_title') if segment.get('sub_title') and isinstance(segment.get('sub_title'), str) and segment.get('sub_title').strip() else None
        if sub:
            subtitle = sub
        else:
            subtitle = f"Segment {segment_number_in_game}"
        textclip_kwargs = dict(
            width=target_width, height=target_height,
            fps=target_fps, use_audio=use_audio, logo_path=logo_path,
        )
        if source_codec and not needs_reencoding:
            textclip_kwargs['source_codec'] = source_codec
            textclip_kwargs['source_pix_fmt'] = source_pix_fmt
            textclip_kwargs['source_fps_raw'] = source_fps_raw
        textclip_file = create_textclip(
            segment_number_in_game, current_game_number, title, subtitle,
            **textclip_kwargs
        )
        chapters.append((current_time, title, subtitle))
        current_time += 1.0
        start_time = segment['start_minute'] * 60
        duration = segment['length_seconds']
        try:
            video_duration = retrieve_video_duration(video_path)
            max_duration = video_duration - start_time
            if max_duration < duration:
                log(f"   ⚠️  Segment {segment_number_in_game:02d}: Angeforderte Dauer ({duration:.2f}s) geht über Video-Ende hinaus!")
                log(f"      Video-Gesamtlänge: {video_duration:.2f}s, Start: {start_time:.2f}s, Max verfügbar: {max_duration:.2f}s")
                log(f"      → Korrigiere automatisch auf {max_duration:.2f}s")
                duration = max_duration
        except Exception as e:
            pass
        segment_file = segments_dir / f"segment_{segment_number_in_game:02d}_{Path(segment['videoname']).name}"
        segment_audio = use_audio and segment.get('audio', 1) != 0
        if is_video_file_complete(segment_file, expected_duration=duration):
            existing_segments_count += 1
        segment_metadata.append({
            'index': i,
            'textclip': textclip_file,
            'segment_file': segment_file
        })
        segment_jobs.append({
            'index': i,
            'segment_file': segment_file,
            'video_path': video_path,
            'start_time': start_time,
            'duration': duration,
            'segment_audio': segment_audio,
            'segment_number': segment_number_in_game,
            'videoname': segment['videoname'],
            'start_minute': segment['start_minute']
        })
        current_time += duration
        segment_number_in_game += 1
    log(f"\n🚀 Phase 2: Extrahiere {len(segment_jobs)} Segmente parallel (Worker: {max_workers})...")
    if existing_segments_count > 0:
        log(f"  📦 {existing_segments_count} Segment(e) bereits vorhanden (werden wiederverwendet)")
        log(f"  ⚡ {len(segment_jobs) - existing_segments_count} Segment(e) müssen erstellt werden")
    extract_args = [
        (job, job['segment_file'], job['video_path'], job['start_time'],
         job['duration'], target_width, target_height, target_fps,
         job['segment_audio'], threads_per_process, youtube_opt, needs_reencoding,
         no_bitrate_limit)
        for job in segment_jobs
    ]
    completed_segments = 0
    failed_segments = []
    segment_times = []
    cached_segments = 0
    segment_results = {}
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {executor.submit(extract_single_segment, args): args[0]['index'] for args in extract_args}
        with tqdm.tqdm(total=len(segment_jobs), desc="Extrahiere Segmente", unit="seg") as pbar:
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                job = segment_jobs[index]
                try:
                    segment_file, processing_time, success, error_msg, was_cached = future.result()
                    if success:
                        segment_results[index] = str(segment_file)
                        segment_times.append(processing_time)
                        completed_segments += 1
                        if was_cached:
                            cached_segments += 1
                        cache_tag = " [Cache]" if was_cached else ""
                        log(f"  ✓ Segment {job['segment_number']:02d}: {Path(job['videoname']).name} @ {job['start_minute']}min ({processing_time:.1f}s){cache_tag}  [{completed_segments}/{len(segment_jobs)}]")
                        if segment_times:
                            avg_time = sum(segment_times) / len(segment_times)
                            remaining = len(segment_jobs) - completed_segments
                            est_time = avg_time * remaining
                            if est_time < 60:
                                time_str = f"{est_time:.0f}s"
                            elif est_time < 3600:
                                time_str = f"{est_time/60:.1f}min"
                            else:
                                time_str = f"{est_time/3600:.1f}h"
                            pbar.set_postfix({'Restzeit': time_str, 'Ø': f"{avg_time:.1f}s", 'Cache': cached_segments})
                    else:
                        failed_segments.append((job, error_msg))
                        log(f"\n❌ Fehler bei Segment {job['segment_number']}: {error_msg}")
                except Exception as e:
                    failed_segments.append((job, str(e)))
                    log(f"\n❌ Exception bei Segment {job['segment_number']}: {e}")
                pbar.update(1)
    if failed_segments:
        log(f"\n⚠️  {len(failed_segments)} Segment(e) fehlgeschlagen!")
        for job, error in failed_segments:
            log(f"   - Segment {job['segment_number']}: {error}")
    log(f"\n✓ {completed_segments}/{len(segment_jobs)} Segmente erfolgreich verarbeitet")
    if cached_segments > 0:
        log(f"  📦 {cached_segments} Segment(e) aus Cache wiederverwendet (nicht neu erstellt)")
        log(f"  ⚡ {completed_segments - cached_segments} Segment(e) neu erstellt")
    log(f"\n🎬 Phase 3: Füge Dateien in korrekter Reihenfolge zusammen...")
    all_files = []
    for i, meta in enumerate(segment_metadata):
        all_files.append(meta['textclip'])
        seg_index = meta['index']
        if seg_index in segment_results:
            all_files.append(segment_results[seg_index])
        else:
            log(f"⚠️  Segment {seg_index} fehlt (Verarbeitung fehlgeschlagen)")
        if i < len(segment_metadata) - 1:
            if seg_index in segment_results:
                transition_file = None # Übergang ggf. auslagern
                all_files.append(transition_file) if transition_file else None
    if not all_files:
        log("Keine Segmente gefunden!")
        return
    concat_file = "output/concat_list.txt"
    with open(concat_file, 'w') as f:
        for file_path in all_files:
            abs_path = Path(file_path).resolve()
            f.write(f"file '{abs_path}'\n")
    concat_input = ['-f', 'concat', '-safe', '0', '-i', concat_file]
    if youtube_opt:
        concat_cmd = build_encode_cmd(
            input_args=concat_input, output_file=output_file,
            audio=True, quality='high',
            width=target_width, height=target_height, fps=target_fps,
            no_bitrate_limit=no_bitrate_limit,
        )
    else:
        concat_cmd = build_encode_cmd(
            input_args=concat_input, output_file=output_file,
            stream_copy=True, audio='copy',
            width=target_width, height=target_height, fps=target_fps,
            no_bitrate_limit=no_bitrate_limit,
        )
    log("Kombiniere Segmente mit Übergängen...")
    log(f"  CMD: {' '.join(str(c) for c in concat_cmd)}")
    global _concat_proc
    _concat_proc = subprocess.Popen(concat_cmd, stdin=subprocess.DEVNULL)
    _concat_proc.wait()
    returncode = _concat_proc.returncode
    _concat_proc = None
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, concat_cmd)
    total_time = time.time() - start_time_overall
    if total_time < 60:
        total_time_str = f"{total_time:.0f} Sekunden"
    elif total_time < 3600:
        total_time_str = f"{total_time/60:.1f} Minuten"
    else:
        hours = int(total_time / 3600)
        minutes = int((total_time % 3600) / 60)
        total_time_str = f"{hours}h {minutes}min"
    try:
        os.remove(concat_file)
        # Übergangsdateien ggf. entfernen
    except:
        pass
    log(f"\n{'='*60}")
    log(f"✓ FERTIG! Video gespeichert als: {output_file}")
    log(f"✓ Segmente gespeichert in: {segments_dir}")
    log(f"⏱️  Gesamte Verarbeitungszeit: {total_time_str}")
    log(f"{'='*60}\n")
    yt_lines = []
    for t, title, subtitle in chapters:
        yt_lines.append(f"{format_time(t)} {title} – {subtitle}")
    yt_chapters_path = Path("output/yt_chapters.txt")
    yt_chapters_path.parent.mkdir(parents=True, exist_ok=True)
    with open(yt_chapters_path, "w") as f:
        for line in yt_lines:
            f.write(line + "\n")
    log("\nYouTube-Kapitelübersicht (output/yt_chapters.txt):\n" + "\n".join(yt_lines))

def format_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    else:
        return f"{m:02d}:{s:02d}"
