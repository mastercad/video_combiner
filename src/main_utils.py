"""
Hilfsfunktionen für main.py: Cache, Segment-Parsing, Terminal-Reset, zentrale Pipeline.
Dieses Modul wird von CLI und GUI gleichermaßen genutzt.
"""

from pathlib import Path
import pandas as pd
import sys
import os


def clean_cache(textclips_dir="output/text_clips", segments_dir="output/segments"):
    """Löscht alte Textclips und Segmente aus dem Cache."""
    deleted_count = 0
    for directory in [Path(textclips_dir), Path(segments_dir)]:
        if directory.exists():
            for file in directory.glob("*"):
                if file.is_file():
                    file.unlink()
                    deleted_count += 1
    return deleted_count


def parse_segments_from_csv(csv_path):
    """Liest und parst die Segmente aus der CSV-Datei."""
    df = pd.read_csv(csv_path)
    segments = []
    for _, row in df.iterrows():
        def parse_float(val):
            if isinstance(val, str):
                val = val.replace(',', '.')
            return float(val)

        raw_videoname = row.get('videoname', None)
        if pd.isna(raw_videoname) or not str(raw_videoname).strip():
            continue
        videoname = str(raw_videoname)

        seg = {
            'videoname': videoname,
            'start_minute': parse_float(row['start_minute']),
            'length_seconds': parse_float(row['length_seconds'])
        }
        if 'title' in df.columns and not pd.isna(row.get('title', None)):
            seg['title'] = str(row['title'])
        if 'sub_title' in df.columns and not pd.isna(row.get('sub_title', None)):
            seg['sub_title'] = str(row['sub_title'])
        if 'audio' in df.columns and not pd.isna(row.get('audio', None)):
            seg['audio'] = int(row['audio'])
        else:
            seg['audio'] = 1
        segments.append(seg)
    return segments


def reset_terminal():
    """Setzt das Terminal zurück, falls ffmpeg es durcheinander gebracht hat."""
    if sys.stdin.isatty():
        try:
            import subprocess
            subprocess.run(['stty', 'sane'], check=False)
        except Exception:
            pass


def run_video_pipeline(segments, options, log_callback=None):
    """
    Zentrale Video-Pipeline – wird von CLI und GUI gleichermaßen genutzt.

    Args:
        segments: Liste von Segment-Dicts (videoname, start_minute, length_seconds, ...)
        options: Dict mit Optionen:
            - input_dir (str): Input-Verzeichnis (default: 'input')
            - output_file (str|None): Output-Datei (None = automatisch)
            - no_audio (bool): Keine Audio-Spur
            - youtube_opt (bool): YouTube-optimierte Ausgabe (default True)
            - workers (int|None): Anzahl paralleler Worker
            - debug_cache (bool): Debug-Infos für Cache
            - logo_path (str): Pfad zum Logo
            - upload_only (bool): Nur Upload, kein Rendering
            - youtube_upload (bool): YouTube-Upload aktiv
            - youtube_title (str): YouTube-Titel
            - youtube_playlist (str): YouTube-Playlist-ID
            - youtube_privacy (str): Privatsphäre (public/private/unlisted)
            - youtube_tags (str): Komma-getrennte Tags
            - youtube_category (str): YouTube-Kategorie ID
        log_callback: Optionaler Callback für Statusmeldungen.
            Signatur: callback(message: str)

    Returns:
        dict: {'success': bool, 'output_file': str|None, 'video_id': str|None, 'error': str|None}
    """
    from src.processing import analyze_video_resolutions, assemble_ffmpeg_script
    from src.segment_utils import generate_output_filename
    from src.youtube_upload import upload_to_youtube

    def log(msg):
        if log_callback:
            log_callback(msg)
        print(msg)

    input_dir = options.get('input_dir', 'input')
    output_file = options.get('output_file', None)
    use_audio = not options.get('no_audio', False)
    youtube_opt = options.get('youtube_opt', True)
    workers = options.get('workers', None)
    debug_cache = options.get('debug_cache', False)
    logo_path = options.get('logo_path', 'input/teamlogo.png')
    upload_only = options.get('upload_only', False)

    if not segments:
        return {'success': False, 'output_file': None, 'video_id': None,
                'error': 'Keine Segmente vorhanden.'}

    log(f"=== KADERBLICK Video Combiner ===")
    log(f"Gefunden: {len(segments)} Segmente")
    log(f"Input-Verzeichnis: {input_dir}")
    log(f"Audio: {'ja' if use_audio else 'nein'}")
    log(f"YouTube-Optimierung: {'ja' if youtube_opt else 'nein'}")
    if logo_path and Path(logo_path).exists():
        log(f"Logo: {logo_path}")

    # Output-Dateiname
    if output_file is None:
        output_file = generate_output_filename(segments, "output")
        log(f"Automatischer Dateiname: {output_file}")
    else:
        log(f"Benutzerdefinierter Dateiname: {output_file}")

    # Upload-Only: Video-Erstellung überspringen
    if upload_only and os.path.exists(output_file):
        file_size_gb = os.path.getsize(output_file) / (1024 ** 3)
        log(f"Upload-Only: {output_file} ({file_size_gb:.2f} GB)")
    else:
        # Video erstellen
        try:
            target_width, target_height, target_fps, needs_reencoding, \
                source_codec, source_pix_fmt, source_fps_raw = \
                analyze_video_resolutions(segments, input_dir, log_callback=log)

            assemble_ffmpeg_script(
                segments, input_dir, output_file,
                use_audio=use_audio,
                target_width=target_width,
                target_height=target_height,
                target_fps=target_fps,
                max_workers=workers,
                debug_cache=debug_cache,
                youtube_opt=youtube_opt,
                needs_reencoding=needs_reencoding,
                logo_path=logo_path,
                log_callback=log,
                source_codec=source_codec,
                source_pix_fmt=source_pix_fmt,
                source_fps_raw=source_fps_raw,
            )
        except Exception as e:
            reset_terminal()
            return {'success': False, 'output_file': output_file,
                    'video_id': None, 'error': str(e)}
        finally:
            reset_terminal()

    # YouTube-Upload
    video_id = None
    if options.get('youtube_upload', False):
        log("Starte YouTube-Upload...")
        yt_chapters_path = Path("output/yt_chapters.txt")
        description = ""
        if yt_chapters_path.exists():
            with open(yt_chapters_path, 'r', encoding='utf-8') as f:
                description = f.read()
        else:
            log("Keine yt_chapters.txt gefunden – Upload ohne Kapitel")

        youtube_title = options.get('youtube_title', '') or Path(output_file).stem

        tags = None
        youtube_tags = options.get('youtube_tags', '')
        if youtube_tags:
            tags = [t.strip() for t in youtube_tags.split(',')]

        try:
            video_id = upload_to_youtube(
                video_file=output_file,
                title=youtube_title,
                description=description,
                playlist_id=options.get('youtube_playlist', ''),
                category_id=options.get('youtube_category', '17'),
                privacy_status=options.get('youtube_privacy', 'unlisted'),
                tags=tags,
            )
            if video_id:
                log(f"Upload erfolgreich! https://www.youtube.com/watch?v={video_id}")
        except Exception as e:
            log(f"YouTube-Upload fehlgeschlagen: {e}")

    log("Pipeline abgeschlossen.")
    return {'success': True, 'output_file': output_file,
            'video_id': video_id, 'error': None}
