"""
Hilfsfunktionen für Segment-Metadaten, Dateinamen, Datumsextraktion
"""

import re

def extract_date_from_filename(filename):
    if not isinstance(filename, (str, bytes)):
        return None

    match = re.search(r'DJI_(\d{8})\d{6}', filename)
    if match:
        return match.group(1)
    match2 = re.match(r'(\d{4})-(\d{2})-(\d{2})', filename)
    if match2:
        year, day, month = match2.groups()
        return f"{year}{month}{day}"
    
    return None

def format_date_ddmmyyyy(yyyymmdd):
    if not yyyymmdd or len(yyyymmdd) != 8:
        return None
    year = yyyymmdd[0:4]
    month = yyyymmdd[4:6]
    day = yyyymmdd[6:8]

    return f"{day}_{month}_{year}"

def generate_output_filename(segments, output_base_dir="output"):
    dates = set()
    for seg in segments:
        videoname = seg.get('videoname', None)
        if not videoname:
            continue
        date = extract_date_from_filename(videoname)
        if date:
            dates.add(date)
    sorted_dates = sorted(dates)
    formatted_dates = []
    for d in sorted_dates:
        formatted = format_date_ddmmyyyy(d)
        if formatted:
            formatted_dates.append(formatted)
    if not formatted_dates:
        return f"{output_base_dir}/Spielanalyse.mp4"
    date_string = "_".join(formatted_dates)
    
    return f"{output_base_dir}/Spielanalyse_{date_string}.mp4"
