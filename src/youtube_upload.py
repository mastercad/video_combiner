"""
YouTube-Upload und Authentifizierung
"""

import pickle
import os
import sys
import time
import tqdm

from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

def authenticate_youtube_service():
    SCOPES = ['https://www.googleapis.com/auth/youtube']
    creds = None
    token_file = 'youtube_token.pickle'
    if os.path.exists(token_file):
        with open(token_file, 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('config/client_secrets.json'):
                print("\n❌ FEHLER: 'config/client_secrets.json' nicht gefunden!")
                print("\nSo richtest du YouTube-Upload ein:")
                print("1. Gehe zu: https://console.cloud.google.com/")
                print("2. Erstelle ein neues Projekt oder wähle ein existierendes")
                print("3. Aktiviere 'YouTube Data API v3'")
                print("4. Erstelle OAuth 2.0 Credentials (Desktop-App)")
                print("5. Lade die JSON-Datei herunter und benenne sie 'client_secrets.json'")
                print("6. Lege sie in das Verzeichnis: config/")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file('config/client_secrets.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, 'wb') as token:
            pickle.dump(creds, token)
    return build('youtube', 'v3', credentials=creds)

def _is_playlist_id(value):
    """Prüft ob ein String eine YouTube-Playlist-ID ist (Format: PLxxxxxxxx)."""
    return bool(value and value.startswith('PL') and len(value) >= 20)


def _find_playlist_by_title(youtube, title):
    """Sucht eine eigene Playlist anhand des Titels. Gibt die ID zurück oder None."""
    next_page = None
    while True:
        response = youtube.playlists().list(
            part='snippet', mine=True, maxResults=50, pageToken=next_page
        ).execute()
        for item in response.get('items', []):
            if item['snippet']['title'].strip().lower() == title.strip().lower():
                return item['id']
        next_page = response.get('nextPageToken')
        if not next_page:
            break
    return None


def _create_playlist(youtube, title, privacy='unlisted'):
    """Erstellt eine neue YouTube-Playlist und gibt die ID zurück."""
    response = youtube.playlists().insert(
        part='snippet,status',
        body={
            'snippet': {'title': title, 'description': f'Erstellt von KADERBLICK Video Combiner'},
            'status': {'privacyStatus': privacy},
        }
    ).execute()
    return response['id']


def resolve_playlist(youtube, playlist_value, privacy='unlisted'):
    """Löst einen Playlist-Wert auf: ID direkt verwenden, Name suchen/erstellen.

    Args:
        youtube: Authentifizierter YouTube-Service
        playlist_value: Playlist-ID (PLxxx...) oder Playlist-Name
        privacy: Privatsphäre-Status für neu erstellte Playlists

    Returns:
        Playlist-ID als String
    """
    if _is_playlist_id(playlist_value):
        print(f"   Playlist-ID erkannt: {playlist_value}")
        return playlist_value

    # Nach Name suchen
    print(f"   🔍 Suche Playlist '{playlist_value}'...")
    found_id = _find_playlist_by_title(youtube, playlist_value)
    if found_id:
        print(f"   ✓ Playlist gefunden: {found_id}")
        return found_id

    # Nicht gefunden → neu erstellen
    print(f"   📋 Playlist '{playlist_value}' nicht gefunden, erstelle neu...")
    new_id = _create_playlist(youtube, playlist_value, privacy=privacy)
    print(f"   ✓ Playlist erstellt: {new_id}")
    return new_id


def upload_to_youtube(video_file, title, description, playlist_id=None, category_id='17', 
                      privacy_status='private', tags=None):
    print(f"\n📤 Lade Video zu YouTube hoch...")
    print(f"   Datei: {video_file}")
    print(f"   Titel: {title}")
    print(f"   Privatsphäre: {privacy_status}")
    try:
        youtube = authenticate_youtube_service()
        body = {
            'snippet': {
                'title': title,
                'description': description,
                'categoryId': category_id
            },
            'status': {
                'privacyStatus': privacy_status
            }
        }
        if tags:
            body['snippet']['tags'] = tags
        CHUNK_SIZE = 256 * 1024 * 1024
        media = MediaFileUpload(video_file, chunksize=CHUNK_SIZE, resumable=True)
        file_size = os.path.getsize(video_file)
        file_size_gb = file_size / (1024**3)
        print(f"\n📤 Upload zu YouTube ({file_size_gb:.2f} GB, Chunk-Größe: 256 MB)")
        request = youtube.videos().insert(
            part=','.join(body.keys()),
            body=body,
            media_body=media
        )
        response = None
        total_chunks = int(file_size / CHUNK_SIZE) + 1
        with tqdm.tqdm(total=100, desc="YouTube Upload", unit="%", bar_format='{desc}: {percentage:3.0f}%|{bar}| {n:.0f}/{total:.0f} [{elapsed}<{remaining}]') as pbar:
            last_progress = 0
            last_update_time = time.time()
            chunk_count = 0
            start_time = time.time()
            while response is None:
                try:
                    chunk_start = time.time()
                    print(f"   [DEBUG] Starte Upload von Chunk {chunk_count + 1}...")
                    status, response = request.next_chunk()
                    chunk_time = time.time() - chunk_start
                    chunk_count += 1
                    print(f"   [DEBUG] Chunk {chunk_count} fertig nach {chunk_time:.1f}s")
                    if chunk_count <= 5:
                        speed_mbps = (CHUNK_SIZE / (1024*1024) * 8) / chunk_time
                        pbar.write(f"   ✓ Chunk {chunk_count}: {chunk_time:.1f}s → {speed_mbps:.1f} Mbit/s")
                    if status:
                        progress = int(status.progress() * 100)
                        if progress > last_progress:
                            pbar.update(progress - last_progress)
                            time_since_update = time.time() - last_update_time
                            if (progress % 5 == 0 and progress != last_progress) or time_since_update > 60:
                                uploaded_gb = (file_size * status.progress()) / (1024**3)
                                elapsed = time.time() - start_time
                                speed_mbps = (uploaded_gb * 8 * 1024) / elapsed if elapsed > 0 else 0
                                remaining_gb = file_size_gb - uploaded_gb
                                eta_minutes = (remaining_gb * 8 * 1024 / speed_mbps / 60) if speed_mbps > 0 else 0
                                pbar.write(f"   → {progress}% ({uploaded_gb:.2f}/{file_size_gb:.2f} GB) - {speed_mbps:.1f} Mbit/s - ETA: {eta_minutes:.0f} min")
                                last_update_time = time.time()
                            last_progress = progress
                except HttpError as e:
                    pbar.write(f"\n   ❌ HTTP-Fehler: {e}")
                    if e.resp.status in [500, 502, 503, 504]:
                        pbar.write(f"   🔄 Server-Fehler, versuche erneut...")
                        time.sleep(5)
                    else:
                        raise
                except Exception as e:
                    pbar.write(f"\n   ❌ Fehler: {type(e).__name__}: {e}")
                    pbar.write(f"   🔄 Versuche erneut...")
                    time.sleep(2)
        print("\n✓ Upload erfolgreich! YouTube verarbeitet das Video jetzt...")
        video_id = response['id']
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        print(f"   Video-ID: {video_id}")
        print(f"   URL: {video_url}")
        if playlist_id:
            try:
                resolved_id = resolve_playlist(youtube, playlist_id, privacy=privacy_status)
                print(f"\n📋 Füge Video zu Playlist hinzu (ID: {resolved_id})...")
                playlist_request = youtube.playlistItems().insert(
                    part='snippet',
                    body={
                        'snippet': {
                            'playlistId': resolved_id,
                            'resourceId': {
                                'kind': 'youtube#video',
                                'videoId': video_id
                            }
                        }
                    }
                )
                playlist_request.execute()
                print("✓ Video zur Playlist hinzugefügt!")
            except HttpError as e:
                print(f"⚠️  Fehler beim Hinzufügen zur Playlist: {e}")
        return video_id
    except HttpError as e:
        print(f"\n❌ HTTP-Fehler beim Upload: {e}")
        return None
    except Exception as e:
        print(f"\n❌ Fehler beim Upload: {e}")
        return None
