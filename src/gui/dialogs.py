"""
Dialoge für die KADERBLICK GUI.

- TimeRangeDialog:       Start-/Endzeit-Eingabe → berechnet Dauer
- YouTubeOptionsDialog:  Erweiterte Video- und YouTube-Optionen
- EditSegmentDialog:     Segment in-place bearbeiten
"""

from pathlib import Path
from PyQt5.QtCore import QTime
from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QFormLayout,
    QTimeEdit, QCheckBox, QLineEdit, QComboBox, QTabWidget, QWidget,
    QSpinBox,
)


class TimeRangeDialog(QDialog):
    """Dialog zur Eingabe eines Zeitbereichs (Start + Ende → Dauer)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Zeitbereich festlegen")
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.start_time_edit = QTimeEdit()
        self.start_time_edit.setDisplayFormat("mm:ss")
        form.addRow("Startzeit (mm:ss):", self.start_time_edit)

        self.end_time_edit = QTimeEdit()
        self.end_time_edit.setDisplayFormat("mm:ss")
        form.addRow("Endzeit (mm:ss):", self.end_time_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def parse_times(self):
        return self.start_time_edit.time(), self.end_time_edit.time()


class YouTubeOptionsDialog(QDialog):
    """Dialog für erweiterte Video- und YouTube-Upload-Optionen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Erweiterte Optionen")
        self.setModal(True)
        self.resize(500, 350)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # ── Video-Tab ────────────────────────────────────────────────────────
        video_tab = QWidget()
        video_layout = QVBoxLayout(video_tab)

        self.no_audio_check = QCheckBox("Keine Audio-Spur in Segmenten und Endvideo")
        video_layout.addWidget(self.no_audio_check)

        self.no_youtube_opt_check = QCheckBox(
            "Verlustlose Ausgabe (nicht YouTube-optimiert)"
        )
        self.no_youtube_opt_check.setToolTip(
            "Exportiert im Originalformat, falls möglich"
        )
        video_layout.addWidget(self.no_youtube_opt_check)

        self.no_bitrate_limit_check = QCheckBox(
            "Kein Bitrate-Limit (YouTube-Begrenzung ignorieren)"
        )
        self.no_bitrate_limit_check.setToolTip(
            "Deaktiviert die automatische Bitrate-Begrenzung auf YouTube-Empfehlungen.\n"
            "Ergibt größere Dateien, kann aber für lokale Archivierung sinnvoll sein."
        )
        video_layout.addWidget(self.no_bitrate_limit_check)

        self.shutdown_check = QCheckBox(
            "Rechner nach Fertigstellung herunterfahren"
        )
        self.shutdown_check.setToolTip(
            "Fährt den Rechner herunter, sobald Verarbeitung und Upload abgeschlossen sind"
        )
        video_layout.addWidget(self.shutdown_check)

        video_layout.addStretch()
        tabs.addTab(video_tab, "Video")

        # ── YouTube-Tab ──────────────────────────────────────────────────────
        yt_tab = QWidget()
        yt_layout = QFormLayout(yt_tab)

        self.youtube_upload_check = QCheckBox("YouTube-Upload aktivieren")
        self.youtube_upload_check.setChecked(True)
        yt_layout.addRow(self.youtube_upload_check)

        self.youtube_title_edit = QLineEdit()
        self.youtube_title_edit.setPlaceholderText("Automatisch aus Spieldaten")
        yt_layout.addRow("Video-Titel:", self.youtube_title_edit)

        self.youtube_playlist_edit = QLineEdit()
        self.youtube_playlist_edit.setPlaceholderText(
            "Aus youtube_config.py oder keine"
        )
        yt_layout.addRow("Playlist-ID:", self.youtube_playlist_edit)

        self.youtube_privacy_combo = QComboBox()
        self.youtube_privacy_combo.addItems(["public", "private", "unlisted"])
        self.youtube_privacy_combo.setCurrentText("unlisted")
        yt_layout.addRow("Privatsphäre:", self.youtube_privacy_combo)

        self.youtube_tags_edit = QLineEdit()
        self.youtube_tags_edit.setPlaceholderText("z.B. Fußball,Analyse,Training")
        yt_layout.addRow("Tags:", self.youtube_tags_edit)

        tabs.addTab(yt_tab, "YouTube")

        # Buttons
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def collect_options(self):
        """Gibt die aktuellen Dialog-Werte als Dict zurück."""
        return {
            "no_audio": self.no_audio_check.isChecked(),
            "no_youtube_opt": self.no_youtube_opt_check.isChecked(),
            "no_bitrate_limit": self.no_bitrate_limit_check.isChecked(),
            "shutdown_after": self.shutdown_check.isChecked(),
            "youtube_upload": self.youtube_upload_check.isChecked(),
            "youtube_title": self.youtube_title_edit.text().strip(),
            "youtube_playlist": self.youtube_playlist_edit.text().strip(),
            "youtube_privacy": self.youtube_privacy_combo.currentText(),
            "youtube_tags": self.youtube_tags_edit.text().strip(),
        }


class EditSegmentDialog(QDialog):
    """Dialog zum In-Place-Bearbeiten eines Segments."""

    def __init__(self, segment, video_paths, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Segment bearbeiten")
        self.setModal(True)
        self.resize(500, 300)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.video_combo = QComboBox()
        for vp in video_paths:
            self.video_combo.addItem(Path(vp).name, vp)
        ci = self.video_combo.findData(segment["videoname"])
        if ci >= 0:
            self.video_combo.setCurrentIndex(ci)
        form.addRow("Video:", self.video_combo)

        total_sec = segment["start_minute"] * 60
        m = int(total_sec // 60)
        s = int(total_sec % 60)
        self.start_time = QTimeEdit()
        self.start_time.setDisplayFormat("mm:ss")
        self.start_time.setTime(QTime(0, m, s))
        form.addRow("Startzeit (mm:ss):", self.start_time)

        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 3600)
        self.duration_spin.setValue(int(segment["length_seconds"]))
        form.addRow("Dauer (Sekunden):", self.duration_spin)

        self.title_edit = QLineEdit(segment.get("title", ""))
        form.addRow("Titel:", self.title_edit)

        self.subtitle_edit = QLineEdit(segment.get("sub_title", ""))
        form.addRow("Untertitel:", self.subtitle_edit)

        self.audio_check = QCheckBox("Audio einschließen")
        self.audio_check.setChecked(segment.get("audio", 1) == 1)
        form.addRow("", self.audio_check)

        layout.addLayout(form)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def collect_segment_data(self):
        t = self.start_time.time()
        return {
            "videoname": self.video_combo.currentData(),
            "start_minute": t.minute() + t.second() / 60.0,
            "length_seconds": self.duration_spin.value(),
            "title": self.title_edit.text(),
            "sub_title": self.subtitle_edit.text(),
            "audio": 1 if self.audio_check.isChecked() else 0,
        }
