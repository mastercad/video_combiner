"""
Textclip-Erstellung für Videosegmente
"""

from pathlib import Path
import hashlib
import unicodedata
import subprocess

from .ffmpeg_utils import is_video_file_complete

def create_textclip(segment_number, game_number, title, subtitle, width=1920, height=1080, duration=1.0, fps=25, logo_path="input/teamlogo.png", use_audio=True, source_codec=None, source_pix_fmt=None, source_fps_raw=None):
    # Encoder und Pixel-Format an Quellvideo anpassen (verhindert Codec-Mismatch beim Concat)
    CODEC_ENCODER_MAP = {
        'hevc': 'libx265', 'h265': 'libx265',
        'h264': 'libx264', 'avc': 'libx264',
    }
    if source_codec:
        encoder = CODEC_ENCODER_MAP.get(source_codec, 'libx264')
        pix_fmt = source_pix_fmt or 'yuv420p'
        rate_str = source_fps_raw or str(fps)
    else:
        encoder = 'libx264'
        pix_fmt = 'yuv420p'
        rate_str = str(fps)

    out_dir = Path("output/text_clips")
    out_dir.mkdir(parents=True, exist_ok=True)
    content_hash = hashlib.md5(f"{title}_{subtitle}_{encoder}_{pix_fmt}".encode('utf-8')).hexdigest()[:8]
    text_file = out_dir / f"textclip_sp{game_number:02d}_seg{segment_number:02d}_{content_hash}.mp4"
    if is_video_file_complete(text_file, expected_duration=duration):
        return str(text_file)

    def normalize_text(s: str) -> str:
        if not s:
            return ''
        s = unicodedata.normalize('NFKC', s)
        s = s.replace('\u00A0', ' ')
        for ch in ['\u200B', '\u200C', '\u200D', '\uFEFF']:
            s = s.replace(ch, '')
        s = ' '.join(s.split())
        return s.strip()

    def wrap_max_three_pref(s: str, font_size: int, max_width_px: int) -> list:
        s = s.strip()
        if not s:
            return []
        avg_char = max(4, font_size * 0.5)
        max_chars = max(12, int(max_width_px / avg_char))
        def greedy_words_to_lines(text: str) -> list:
            words = text.split()
            lines = []
            cur = ''
            for w in words:
                candidate = w if cur == '' else cur + ' ' + w
                if len(candidate) <= max_chars:
                    cur = candidate
                else:
                    if cur:
                        lines.append(cur)
                    while len(w) > max_chars:
                        lines.append(w[:max_chars])
                        w = w[max_chars:]
                    cur = w
            if cur:
                lines.append(cur)
            return lines
        prefs = [' vs ', ' v ', '/', '|']
        for sep in prefs:
            if sep in s:
                parts = [p.strip() for p in s.split(sep) if p.strip()]
                candidate_lines = []
                for p in parts:
                    candidate_lines.extend(greedy_words_to_lines(p))
                if len(candidate_lines) <= 3:
                    return candidate_lines
        lines = greedy_words_to_lines(s)
        if len(lines) <= 3:
            return lines
        while len(lines) > 3:
            lines[-2] = lines[-2] + ' ' + lines[-1]
            lines.pop()
        return lines

    title_norm = normalize_text(title) if title else ''
    subtitle_norm = normalize_text(subtitle) if subtitle else ''
    title_lines = wrap_max_three_pref(title_norm, 72, width)
    subtitle_lines = wrap_max_three_pref(subtitle_norm, 48, width)
    logo_exists = Path(logo_path).is_file()
    vf_filters = []
    title_font = 72
    subtitle_font = 48
    title_line_h = int(title_font * 1.1)
    subtitle_line_h = int(subtitle_font * 1.1)
    box_x = int(width * 0.05)
    box_w = int(width * 0.9)
    logo_h = 300 if logo_exists else 0
    gap_logo_title = 30 if logo_exists and len(title_lines) > 0 else 0
    gap_title_sub = 30 if len(title_lines) > 0 and len(subtitle_lines) > 0 else 0
    title_block_h = title_line_h * len(title_lines)
    subtitle_block_h = subtitle_line_h * len(subtitle_lines)
    block_height = logo_h + gap_logo_title + title_block_h + gap_title_sub + subtitle_block_h
    block_y_px = int((height - block_height) / 2)
    cur_y_px = block_y_px
    if logo_exists:
        vf_filters.append(f"movie={logo_path} [logo]; [0][logo] overlay=x=(W-w)/2:y={cur_y_px} [tmp1]")
        cur_y_px += logo_h + gap_logo_title
        base = '[tmp1]'
    else:
        base = '[0]'
    vf_filters.append(f"{base} drawbox=x={box_x}:y={block_y_px}:w={box_w}:h={block_height}:color=black@0.8:t=fill [tmp_box]")
    current_base = '[tmp_box]'
    for idx, line in enumerate(title_lines):
        tf = out_dir / f"text_sp{game_number:02d}_seg{segment_number:02d}_{content_hash}_t{idx}.txt"
        tf.write_text(line + "\n", encoding='utf-8')
        next_tmp = f"[tmp_t{idx}]"
        y_px = cur_y_px + idx * title_line_h
        vf_filters.append(
            f"{current_base} drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile='{str(tf)}':reload=1:fontcolor=white:fontsize={title_font}:x=(w-text_w)/2:y={y_px} {next_tmp}"
        )
        current_base = next_tmp
    subtitle_start_px = cur_y_px + title_block_h + gap_title_sub
    for idx, line in enumerate(subtitle_lines):
        tf = out_dir / f"text_sp{game_number:02d}_seg{segment_number:02d}_{content_hash}_s{idx}.txt"
        tf.write_text(line + "\n", encoding='utf-8')
        y_px = subtitle_start_px + idx * subtitle_line_h
        vf_filters.append(
            f"{current_base} drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile='{str(tf)}':reload=1:fontcolor=white:fontsize={subtitle_font}:x=(w-text_w)/2:y={y_px}"
        )
    vf = '; '.join(vf_filters)
    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', f'color=black:size={width}x{height}:duration={duration}:rate={rate_str}',
    ]
    if use_audio:
        cmd.extend([
            '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000',
        ])
    encoder_extra = ['-tag:v', 'hvc1'] if encoder == 'libx265' else []
    cmd.extend([
        '-vf', vf,
        '-c:v', encoder,
        '-crf', '18',
        '-pix_fmt', pix_fmt,
        '-preset', 'veryfast',
        *encoder_extra,
        '-g', str(int(round(fps))),
        '-force_key_frames', 'expr:gte(t,0)',
    ])
    if use_audio:
        cmd.extend([
            '-c:a', 'aac',
            '-ar', '48000',
            '-ac', '2',
            '-shortest',
        ])
    else:
        cmd.append('-an')
    cmd.append(str(text_file))

    subprocess.run(cmd, stdin=subprocess.DEVNULL, check=True, capture_output=True)
    return str(text_file)
