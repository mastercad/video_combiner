#!/usr/bin/env python3
"""
KADERBLICK Video Combiner – Modularer, YouTube-optimierter Videozuschnitt

Features:
- Automatische Auflösungserkennung (4K, 1080p, etc.)
- Parallele Verarbeitung auf mehreren CPU-Kernen
- Fortschrittsanzeige und Zeitschätzung
- YouTube-optimierte Videoausgabe (H.264, sinnvolle Bitrate, CRF, Preset, Audio)
- Optional verlustarme Ausgabe im Originalformat
- Automatische Kapitelgenerierung für YouTube
- Upload zu YouTube mit Playlist, Privatsphäre, Tags
- Benutzerfreundliche GUI (startet standardmäßig)
- Modularer Aufbau: ffmpeg, Segmentierung, Textclips, Upload, Verarbeitung

Verwendung (GUI):
    python main.py

Verwendung (CLI):
    python main.py --cli --csv segments.csv --input input/ --output output/video.mp4
    python main.py --cli --workers 8
    python main.py --cli --no-youtube-opt
    python main.py --cli --no-upload
    python main.py --cli --help

"""

import argparse
import os
import sys
from src.main_utils import clean_cache, parse_segments_from_csv, run_video_pipeline

# YouTube Upload Konfiguration
try:
    from config.youtube_config import (
        YOUTUBE_DEFAULT_PLAYLIST,
        YOUTUBE_DEFAULT_PRIVACY,
        YOUTUBE_UPLOAD_ENABLED,
        YOUTUBE_DEFAULT_CATEGORY,
        YOUTUBE_DEFAULT_TAGS,
    )
except ImportError:
    YOUTUBE_DEFAULT_PLAYLIST = None
    YOUTUBE_DEFAULT_PRIVACY = "unlisted"
    YOUTUBE_UPLOAD_ENABLED = True
    YOUTUBE_DEFAULT_CATEGORY = "17"
    YOUTUBE_DEFAULT_TAGS = None


def create_arg_parser():
    parser = argparse.ArgumentParser(
        description='KADERBLICK Video Combiner – Videozuschnitt und YouTube-Upload',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--csv', '-c', default='segments.csv',
                        help='CSV-Datei mit Segment-Definitionen')
    parser.add_argument('--input', '-i', default='input',
                        help='Input-Verzeichnis mit Quellvideos')
    parser.add_argument('--output', '-o', default=None,
                        help='Output-Datei (Standard: automatisch)')
    parser.add_argument('--no-audio', action='store_true',
                        help='Keine Audio-Spur')
    parser.add_argument('--workers', '-w', type=int, default=None,
                        help='Anzahl paralleler Worker')
    parser.add_argument('--clean-cache', action='store_true',
                        help='Alte Cache-Dateien vor Start löschen')
    parser.add_argument('--debug-cache', action='store_true',
                        help='Debug-Infos für Cache')
    parser.add_argument('--upload-only', action='store_true',
                        help='Nur Upload (überspringt Video-Erstellung)')
    parser.add_argument('--no-upload', action='store_true',
                        help='YouTube-Upload deaktivieren')
    parser.add_argument('--youtube-title', type=str, default=None,
                        help='YouTube Video-Titel')
    parser.add_argument('--youtube-playlist', type=str,
                        default=YOUTUBE_DEFAULT_PLAYLIST,
                        help='YouTube Playlist-ID')
    parser.add_argument('--youtube-privacy', type=str,
                        default=YOUTUBE_DEFAULT_PRIVACY,
                        choices=['public', 'private', 'unlisted'],
                        help='YouTube Privatsphäre')
    parser.add_argument('--youtube-tags', type=str, default=None,
                        help='Komma-getrennte Tags')
    parser.add_argument('--logo', type=str, default='input/teamlogo.png',
                        help='Pfad zum Logo-Bild')
    parser.add_argument('--no-youtube-opt', action='store_true',
                        help='Verlustlose Ausgabe (nicht YouTube-optimiert)')
    parser.add_argument('--shutdown', action='store_true',
                        help='Rechner nach Abschluss herunterfahren')
    parser.add_argument('--cli', action='store_true',
                        help='Kommandozeilen-Modus (Standard: GUI)')
    return parser


def main():
    parser = create_arg_parser()
    args = parser.parse_args()

    # ── GUI (Standard) ──────────────────────────────────────────
    if not args.cli:
        try:
            from src.gui import main as gui_main
            gui_main()
        except ImportError as e:
            print(f"Fehler: PyQt5 nicht installiert oder GUI-Modul nicht gefunden: {e}")
            print("Installieren Sie PyQt5 mit: pip install PyQt5")
            print("Oder verwenden Sie --cli für die Kommandozeilen-Version")
            sys.exit(1)
        return

    # ── CLI ──────────────────────────────────────────────────────
    if args.clean_cache:
        print("\n🧹 Räume alten Cache auf...")
        deleted = clean_cache()
        print(f"✓ {deleted} alte Cache-Dateien gelöscht")

    segments = parse_segments_from_csv(args.csv)

    # Tags: CLI-Argument > youtube_config.py > None
    tags_str = args.youtube_tags
    if not tags_str and YOUTUBE_DEFAULT_TAGS and isinstance(YOUTUBE_DEFAULT_TAGS, str):
        tags_str = YOUTUBE_DEFAULT_TAGS

    upload_enabled = YOUTUBE_UPLOAD_ENABLED and not args.no_upload

    options = {
        'input_dir': args.input,
        'output_file': args.output,
        'no_audio': args.no_audio,
        'youtube_opt': not args.no_youtube_opt,
        'workers': args.workers,
        'debug_cache': args.debug_cache,
        'logo_path': args.logo,
        'upload_only': args.upload_only,
        'youtube_upload': upload_enabled,
        'youtube_title': args.youtube_title or '',
        'youtube_playlist': args.youtube_playlist or '',
        'youtube_privacy': args.youtube_privacy,
        'youtube_tags': tags_str or '',
        'youtube_category': YOUTUBE_DEFAULT_CATEGORY,
    }

    result = run_video_pipeline(segments, options)

    if result['success']:
        vid = result.get('video_id')
        if vid:
            print(f"\n{'='*60}")
            print(f"🎉 Video erfolgreich zu YouTube hochgeladen!")
            print(f"   URL: https://www.youtube.com/watch?v={vid}")
            print(f"{'='*60}\n")

        if args.shutdown:
            import platform
            print("\n🔌 Rechner wird in 30 Sekunden heruntergefahren...")
            system = platform.system()
            if system == 'Linux':
                os.system('shutdown -h +0 "KADERBLICK: Verarbeitung abgeschlossen"')
            elif system == 'Windows':
                os.system('shutdown /s /t 30 /c "KADERBLICK: Verarbeitung abgeschlossen"')
            elif system == 'Darwin':
                os.system('sudo shutdown -h +0')
    else:
        print(f"\n❌ Fehler: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
