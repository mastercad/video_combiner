#!/usr/bin/env python3
"""
CSV Validator - Prüft ob die Segment-Dauern in der CSV mit den tatsächlichen Videos übereinstimmen

Verwendung:
    python validate_csv.py --csv segments.csv --input input/
    python validate_csv.py --csv segments.csv --input input/ --fix  # Korrigiert automatisch
"""

import pandas as pd
import subprocess
import json
import argparse
from pathlib import Path


def retrieve_video_duration(video_path):
    """Liest die Gesamtdauer eines Videos in Sekunden"""
    cmd = [
        'ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format',
        str(video_path)
    ]
    result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    return float(data['format']['duration'])


def validate_csv(csv_file, input_dir, fix=False):
    """Validiert die CSV und korrigiert optional die Dauer"""
    df = pd.read_csv(csv_file)
    
    print(f"\n📋 Validiere CSV: {csv_file}")
    print(f"   Input-Verzeichnis: {input_dir}")
    print(f"=" * 80)
    
    errors_found = 0
    corrections = []
    
    for idx, row in df.iterrows():
        videoname = row['videoname']
        start_minute = float(str(row['start_minute']).replace(',', '.'))
        length_seconds = float(str(row['length_seconds']).replace(',', '.'))
        
        video_path = Path(input_dir) / videoname
        
        if not video_path.exists():
            print(f"\n❌ Zeile {idx + 2}: Video nicht gefunden: {videoname}")
            errors_found += 1
            continue
        
        try:
            video_duration = retrieve_video_duration(video_path)
            start_time = start_minute * 60
            max_duration = video_duration - start_time
            
            if start_time > video_duration:
                print(f"\n❌ Zeile {idx + 2}: Startzeit ({start_minute:.2f} min = {start_time:.2f}s) ist nach Video-Ende!")
                print(f"   Video: {videoname}")
                print(f"   Video-Länge: {video_duration:.2f}s ({video_duration/60:.2f} min)")
                errors_found += 1
                continue
            
            if length_seconds > max_duration:
                diff = length_seconds - max_duration
                print(f"\n⚠️  Zeile {idx + 2}: Dauer geht über Video-Ende hinaus!")
                print(f"   Video: {videoname}")
                print(f"   Video-Länge: {video_duration:.2f}s ({video_duration/60:.2f} min)")
                print(f"   Start: {start_minute:.2f} min ({start_time:.2f}s)")
                print(f"   Angefordert: {length_seconds:.2f}s")
                print(f"   Max verfügbar: {max_duration:.2f}s")
                print(f"   Differenz: {diff:.2f}s zu viel!")
                
                if fix:
                    df.at[idx, 'length_seconds'] = round(max_duration, 2)
                    corrections.append((idx + 2, videoname, length_seconds, max_duration))
                    print(f"   ✓ Korrigiert auf: {max_duration:.2f}s")
                
                errors_found += 1
            else:
                # Alles OK
                print(f"✓ Zeile {idx + 2}: OK - {videoname} (Start: {start_minute:.2f}min, Dauer: {length_seconds:.2f}s)")
        
        except Exception as e:
            print(f"\n❌ Zeile {idx + 2}: Fehler beim Prüfen von {videoname}: {e}")
            errors_found += 1
    
    print(f"\n" + "=" * 80)
    
    if errors_found == 0:
        print(f"✅ Alle {len(df)} Segmente sind gültig!")
    else:
        print(f"⚠️  {errors_found} Problem(e) gefunden!")
        
        if fix and corrections:
            backup_file = csv_file.replace('.csv', '_backup.csv')
            df.to_csv(backup_file, index=False)
            print(f"\n📦 Backup erstellt: {backup_file}")
            
            df.to_csv(csv_file, index=False)
            print(f"✓ CSV korrigiert: {csv_file}")
            print(f"\nKorrigierte Einträge:")
            for line, video, old_dur, new_dur in corrections:
                print(f"  Zeile {line}: {video}")
                print(f"    {old_dur:.2f}s → {new_dur:.2f}s (Differenz: {old_dur - new_dur:.2f}s)")
        elif errors_found > 0 and not fix:
            print(f"\n💡 Tipp: Führe das Tool mit --fix aus, um die CSV automatisch zu korrigieren:")
            print(f"   python validate_csv.py --csv {csv_file} --input {input_dir} --fix")


def main():
    parser = argparse.ArgumentParser(description='Validiert CSV-Segmente gegen tatsächliche Video-Dauern')
    parser.add_argument('--csv', '-c', default='segments.csv', help='CSV-Datei mit Segment-Definitionen')
    parser.add_argument('--input', '-i', default='input', help='Input-Verzeichnis mit Videos')
    parser.add_argument('--fix', action='store_true', help='Korrigiert automatisch falsche Dauern')
    
    args = parser.parse_args()
    validate_csv(args.csv, args.input, args.fix)


if __name__ == "__main__":
    main()
