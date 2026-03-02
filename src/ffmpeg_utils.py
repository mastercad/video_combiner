"""
Hilfsfunktionen für ffmpeg-Kommandos und Videoanalyse
"""

import subprocess
import json
from pathlib import Path


def retrieve_video_duration(video_path):
    cmd = [
        'ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format',
        str(video_path)
    ]
    result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    return float(data['format']['duration'])

def extract_video_specs(video_path):
    cmd = [
        'ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams',
        video_path
    ]
    result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True)
    streams = json.loads(result.stdout)['streams']
    video_stream = next(s for s in streams if s['codec_type'] == 'video')
    audio_stream = next((s for s in streams if s['codec_type'] == 'audio'), None)
    fps_parts = video_stream['r_frame_rate'].split('/')
    fps = int(fps_parts[0]) / int(fps_parts[1]) if len(fps_parts) == 2 else float(fps_parts[0])
    specs = {
        'width': video_stream['width'],
        'height': video_stream['height'],
        'fps': fps,
        'fps_raw': video_stream['r_frame_rate'],
        'codec': video_stream['codec_name'],
        'pix_fmt': video_stream['pix_fmt']
    }
    if audio_stream:
        specs['audio_codec'] = audio_stream['codec_name']
        specs['sample_rate'] = audio_stream['sample_rate']
        specs['channels'] = audio_stream['channels']
    return specs

def is_video_file_complete(video_path, expected_duration=None, tolerance=2.0, debug=False) -> bool:
    if not Path(video_path).exists():
        if debug:
            print(f"   ⚠️  DEBUG: {Path(video_path).name} existiert nicht")
        return False
    file_size = Path(video_path).stat().st_size
    if file_size < 1024:
        if debug:
            print(f"   ⚠️  DEBUG: {Path(video_path).name} zu klein ({file_size} bytes)")
        return False
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-show_streams', str(video_path)
        ]
        result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            if debug:
                print(f"   ⚠️  DEBUG: {Path(video_path).name} nicht lesbar (ffprobe returncode: {result.returncode})")
            return False
        data = json.loads(result.stdout)
        if 'streams' not in data or len(data['streams']) == 0:
            if debug:
                print(f"   ⚠️  DEBUG: {Path(video_path).name} hat keine Streams")
            return False
        if expected_duration is not None and 'format' in data:
            actual_duration = float(data['format'].get('duration', 0))
            duration_diff = abs(actual_duration - expected_duration)
            if duration_diff > tolerance:
                if debug:
                    print(f"   ⚠️  DEBUG: {Path(video_path).name} Dauer stimmt nicht!")
                    print(f"      Erwartet: {expected_duration:.2f}s, Ist: {actual_duration:.2f}s, Diff: {duration_diff:.2f}s (Toleranz: {tolerance}s)")
                return False
        return True
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        if debug:
            print(f"   ⚠️  DEBUG: {Path(video_path).name} Exception: {type(e).__name__}: {e}")
        return False
