# YouTube Upload Einrichtung

## 1. Google Cloud Projekt erstellen

1. Gehe zu [Google Cloud Console](https://console.cloud.google.com/)
2. Klicke auf "Projekt auswählen" → "Neues Projekt"
3. Gib einen Namen ein (z.B. "Fussballverein Videos")
4. Klicke "Erstellen"

## 2. YouTube Data API aktivieren

1. Im Projekt: Gehe zu "APIs & Dienste" → "Bibliothek"
2. Suche nach "YouTube Data API v3"
3. Klicke auf "YouTube Data API v3"
4. Klicke "Aktivieren"

## 3. OAuth 2.0 Credentials erstellen

1. Gehe zu "APIs & Dienste" → "Anmeldedaten"
2. Klicke "+ ANMELDEDATEN ERSTELLEN" → "OAuth-Client-ID"
3. Falls noch nicht geschehen: Konfiguriere den OAuth-Zustimmungsbildschirm
   - Wähle "Extern" (für YouTube-Uploads außerhalb deiner Organisation)
   - Fülle die erforderlichen Felder aus (App-Name, E-Mail)
   - Bei "Bereiche": Füge `https://www.googleapis.com/auth/youtube.upload` hinzu
   - Füge deine E-Mail als Testnutzer hinzu
4. Zurück zu "Anmeldedaten": Erstelle OAuth-Client-ID
   - Anwendungstyp: **Desktop-App**
   - Name: z.B. "Video Uploader"
5. Klicke "Erstellen"
6. **WICHTIG**: Klicke auf "JSON HERUNTERLADEN"
7. Benenne die heruntergeladene Datei um in: `client_secrets.json`
8. Lege sie in das Verzeichnis: `config/`

## 4. Python-Pakete installieren

```bash
pip install -r requirements.txt
```

## 5. Playlist-ID finden (optional)

1. Gehe zu YouTube Studio
2. Öffne die gewünschte Playlist
3. Die URL sieht so aus: `https://www.youtube.com/playlist?list=PLxxx...`
4. Kopiere die ID nach `list=` (z.B. `PLxxx...`)

## 6. Standard-Einstellungen konfigurieren

Erstelle/bearbeite `config/youtube_config.py`:

```python
# YouTube Upload Konfiguration

# Deine Standard-Playlist-ID (z.B. "PLxxxxxxxxxxxxxxxxxxx")
YOUTUBE_DEFAULT_PLAYLIST = "PLxxxxxxxxxxxxxxxxxxx"  # <-- Hier deine Playlist-ID eintragen!

# Standard Privatsphäre-Einstellung
YOUTUBE_DEFAULT_PRIVACY = "unlisted"

# Upload standardmäßig aktiviert?
YOUTUBE_UPLOAD_ENABLED = True

# Standard Video-Kategorie (17 = Sports)
YOUTUBE_DEFAULT_CATEGORY = "17"

# Standard-Tags (komma-getrennt, optional)
YOUTUBE_DEFAULT_TAGS = "Fußball,Spielanalyse,Training"
```

# YouTube Upload Einrichtung & Nutzung

Diese Anleitung beschreibt die vollständige Einrichtung und Nutzung des automatischen YouTube-Uploads im KADERBLICK Video Combiner.

---

## 1. Google Cloud Projekt & API-Zugang

1. Gehe zu [Google Cloud Console](https://console.cloud.google.com/)
2. Erstelle ein neues Projekt (z.B. "Fussballverein Videos")
3. Aktiviere im Projekt die **YouTube Data API v3** (APIs & Dienste → Bibliothek)
4. Gehe zu "APIs & Dienste" → "Anmeldedaten"
5. Erstelle **OAuth-Client-ID** (Typ: Desktop-App)
6. Lade die JSON-Datei herunter und benenne sie um in: `client_secrets.json`
7. Lege sie ins Verzeichnis `config/`

## 2. Python-Abhängigkeiten installieren

```bash
pip install -r requirements.txt
```

## 3. Playlist-ID finden (optional)

1. Gehe zu YouTube Studio
2. Öffne die gewünschte Playlist
3. Die URL sieht so aus: `https://www.youtube.com/playlist?list=PLxxx...`
4. Kopiere die ID nach `list=` (z.B. `PLxxx...`)

## 4. Standard-Einstellungen konfigurieren

Bearbeite `config/youtube_config.py`:

```python
# Deine Standard-Playlist-ID (z.B. "PLxxxxxxxxxxxxxxxxxxx")
YOUTUBE_DEFAULT_PLAYLIST = "PLxxxxxxxxxxxxxxxxxxx"

# Standard-Privatsphäre (public, private, unlisted)
YOUTUBE_DEFAULT_PRIVACY = "unlisted"

# Upload standardmäßig aktiviert?
YOUTUBE_UPLOAD_ENABLED = True

# Standard Video-Kategorie (17 = Sports)
YOUTUBE_DEFAULT_CATEGORY = "17"

# Standard-Tags (komma-getrennt, optional)
YOUTUBE_DEFAULT_TAGS = "Fußball,Spielanalyse,Training"
```

## 5. Verwendung & CLI-Optionen

### Standard-Upload (nutzt Einstellungen aus youtube_config.py)

```bash
python main.py
# → Erstellt Video, lädt es automatisch zu YouTube hoch (unlisted, zu deiner Playlist)
```

### Ohne Upload

```bash
python main.py --no-upload
```

### Originalformat (nicht YouTube-optimiert)

```bash
python main.py --no-youtube-opt
# → Exportiert im Originalformat (z.B. für Archivierung, nicht für YouTube)
```

### Mit spezifischen Einstellungen (überschreibt Defaults)

```bash
python main.py \
   --youtube-title "Spielanalyse 18.10.2024" \
   --youtube-playlist "PLxxxxxxxxxxxxxxxxxxx" \
   --youtube-privacy "public" \
   --youtube-tags "Fußball,Training,Analyse"
```

### Parameterübersicht (YouTube-relevant)

- **Kein Flag nötig**: Upload ist standardmäßig aktiviert!
- `--no-upload`: Deaktiviert YouTube-Upload
- `--youtube-title "Titel"`: Setzt Video-Titel (Standard: Dateiname)
- `--youtube-playlist "PLxxx"`: Überschreibt Standard-Playlist
- `--youtube-privacy {public|private|unlisted}`: Überschreibt Standard-Privatsphäre
- `--youtube-tags "Tag1,Tag2,Tag3"`: Überschreibt Standard-Tags
- `--no-youtube-opt`: Exportiert im Originalformat (nicht YouTube-optimiert)

## 6. Erste Authentifizierung

Beim ersten Upload öffnet sich automatisch ein Browser:
1. Melde dich mit deinem YouTube-Konto an
2. Akzeptiere die Berechtigungen
3. Die Credentials werden in `youtube_token.pickle` gespeichert
4. Bei nächsten Uploads ist keine erneute Anmeldung nötig

## 7. Hinweise & Tipps

- **Quotas**: Google erlaubt 10.000 Units/Tag (ein Upload ≈ 1600 Units, ca. 6 Videos/Tag)
- **Standard-Upload aktiviert**: Das Script lädt Videos standardmäßig zu YouTube hoch (mit `--no-upload` deaktivierbar)
- **Kapitel**: Die Datei `output/yt_chapters.txt` wird automatisch als Beschreibung eingefügt
- **Sicherheit**: Halte `config/client_secrets.json`, `youtube_token.pickle` und `config/youtube_config.py` geheim!
- **Kategorie**: Videos werden als "Sports" (Kategorie 17) hochgeladen
- **CLI-Optionen überschreiben die Defaults aus der Konfigurationsdatei**

## 8. Fehlerbehebung

### "client_secrets.json nicht gefunden"
→ Siehe Schritt 1, Datei muss in `config/` liegen

### "OAuth-Zustimmungsbildschirm nicht konfiguriert"
→ Siehe Schritt 1, muss einmalig eingerichtet werden

### "Insufficient Permission"
→ Prüfe ob YouTube Data API aktiviert ist (Schritt 1)

### "Quota exceeded"
→ Warte bis zum nächsten Tag (Quota wird täglich zurückgesetzt)
