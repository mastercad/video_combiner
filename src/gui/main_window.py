"""
Hauptfenster der KADERBLICK Video Combiner GUI.

Zuständigkeiten:
- Video-Liste & externes Hinzufügen
- Segment-Eingabe, Tabelle mit Drag&Drop
- Logo-Auswahl mit Vorschau (direkt im Hauptfenster)
- Pipeline starten (über PipelineWorker, kein subprocess)
- Konfiguration laden/speichern (settings.json)
"""

import csv
import json
import os
from pathlib import Path

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QComboBox,
    QLineEdit, QSpinBox, QTimeEdit, QCheckBox, QFileDialog, QMessageBox,
    QHeaderView, QSplitter, QGroupBox, QFormLayout,
    QDialog, QTextEdit,
)
from PyQt5.QtCore import Qt, QTime, QTimer
from PyQt5.QtGui import QFont, QIcon, QPixmap

from src.gui.dialogs import TimeRangeDialog, YouTubeOptionsDialog
from src.gui.worker import PipelineWorker


class VideoSegmentGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.segments = []
        self._csv_dirty = False
        self.input_dir = Path("input")
        self.external_videos = []
        self.csv_file = "segments.csv"
        self.config_file = "config/settings.json"
        self.pipeline_worker = None

        self.options = {
            "no_audio": False,
            "no_youtube_opt": False,
            "no_bitrate_limit": False,
            "shutdown_after": False,
            "youtube_upload": True,
            "youtube_title": "",
            "youtube_playlist": "",
            "youtube_privacy": "unlisted",
            "youtube_tags": "",
            "logo_path": "",
        }
        self._load_config()
        self._init_ui()
        self._load_videos()
        self._load_segments()

    # ── Konfiguration ────────────────────────────────────────────────────────

    def _load_config(self):
        try:
            if Path(self.config_file).exists():
                with open(self.config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    self.external_videos = [
                        v for v in cfg.get("external_videos", []) if Path(v).exists()
                    ]
                    self.options.update(cfg.get("options", {}))
        except Exception as e:
            print(f"Warnung: Konnte GUI-Konfiguration nicht laden: {e}")

    def _save_config(self):
        try:
            cfg = {
                "external_videos": self.external_videos,
                "options": self.options,
            }
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warnung: Konnte GUI-Konfiguration nicht speichern: {e}")

    def closeEvent(self, event):
        self._save_config()
        # Laufende ffmpeg-Prozesse sauber beenden
        if hasattr(self, 'pipeline_worker') and self.pipeline_worker and self.pipeline_worker.isRunning():
            from src.processing import cancel_pipeline
            cancel_pipeline()
            self.pipeline_worker.wait(5000)
        super().closeEvent(event)

    # ── UI aufbauen ──────────────────────────────────────────────────────────

    def _init_ui(self):
        self.setWindowTitle("KADERBLICK Video Combiner")
        self.setGeometry(100, 100, 1200, 800)

        # App-Icon setzen (Taskleiste + Fenster)
        icon_path = Path(__file__).resolve().parent.parent.parent / "assets" / "kaderblick.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([400, 800])

    # ── Linkes Panel ─────────────────────────────────────────────────────────

    def _build_left_panel(self):
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.addWidget(self._build_segment_input_group())
        lay.addWidget(self._build_logo_group())
        lay.addLayout(self._build_action_buttons())
        return panel

    def _build_segment_input_group(self):
        grp = QGroupBox("Neues Segment hinzufügen")
        form = QFormLayout(grp)

        self.video_combo = QComboBox()
        add_video_btn = QPushButton("+")
        add_video_btn.setFixedWidth(32)
        add_video_btn.setToolTip("Weitere Videodatei hinzufügen …")
        add_video_btn.clicked.connect(self._add_video)
        rm_video_btn = QPushButton("−")
        rm_video_btn.setFixedWidth(32)
        rm_video_btn.setToolTip("Ausgewähltes Video aus der Liste entfernen")
        rm_video_btn.clicked.connect(self._remove_video)
        video_row = QHBoxLayout()
        video_row.addWidget(self.video_combo, 1)
        video_row.addWidget(add_video_btn)
        video_row.addWidget(rm_video_btn)
        form.addRow("Video:", video_row)

        self.start_time = QTimeEdit()
        self.start_time.setDisplayFormat("mm:ss")

        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 3600)
        self.duration_spin.setValue(30)

        range_btn = QPushButton("Zeitbereich …")
        range_btn.setToolTip("Start- und Endzeit eingeben → Dauer wird berechnet")
        range_btn.clicked.connect(self._apply_time_range)

        time_row = QHBoxLayout()
        time_row.addWidget(self.start_time)
        time_row.addWidget(QLabel("Dauer (s):"))
        time_row.addWidget(self.duration_spin)
        time_row.addWidget(range_btn)
        form.addRow("Start (mm:ss):", time_row)

        self.title_edit = QLineEdit()
        form.addRow("Titel:", self.title_edit)

        self.subtitle_edit = QLineEdit()
        form.addRow("Untertitel:", self.subtitle_edit)

        self.audio_check = QCheckBox("Audio einschließen")
        self.audio_check.setChecked(True)
        form.addRow("", self.audio_check)

        btns = QHBoxLayout()
        add_btn = QPushButton("Hinzufügen")
        add_btn.clicked.connect(self._add_segment)
        btns.addWidget(add_btn)
        form.addRow(btns)

        return grp

    def _build_logo_group(self):
        grp = QGroupBox("Logo")
        lay = QHBoxLayout(grp)

        # Logo-Preview zentriert (horizontal + vertikal)
        preview_col = QVBoxLayout()
        preview_col.addStretch()
        self.logo_preview = QLabel()
        self.logo_preview.setFixedSize(80, 80)
        self.logo_preview.setScaledContents(True)
        self.logo_preview.setStyleSheet(
            "border: 1px solid #999; background: #f0f0f0;"
        )
        self.logo_preview.setAlignment(Qt.AlignCenter)
        self.logo_preview.setText("Kein\nLogo")
        preview_col.addWidget(self.logo_preview, 0, Qt.AlignHCenter)
        self.logo_path_label = QLabel("Kein Logo ausgewählt")
        self.logo_path_label.setWordWrap(True)
        self.logo_path_label.setAlignment(Qt.AlignCenter)
        self.logo_path_label.setStyleSheet("font-size: 9px; color: #666;")
        preview_col.addWidget(self.logo_path_label, 0, Qt.AlignHCenter)
        preview_col.addStretch()
        lay.addLayout(preview_col)

        right = QVBoxLayout()

        btn_row = QHBoxLayout()
        sel_btn = QPushButton("Auswählen...")
        sel_btn.clicked.connect(self._select_logo)
        btn_row.addWidget(sel_btn)
        clr_btn = QPushButton("Entfernen")
        clr_btn.clicked.connect(self._clear_logo)
        btn_row.addWidget(clr_btn)
        right.addLayout(btn_row)
        lay.addLayout(right)

        self._update_logo_preview()
        return grp

    def _build_action_buttons(self):
        row = QHBoxLayout()
        save_btn = QPushButton("CSV speichern")
        save_btn.clicked.connect(self._save_csv)
        row.addWidget(save_btn)

        opts_btn = QPushButton("Erweiterte Optionen")
        opts_btn.clicked.connect(self._show_advanced_options)
        row.addWidget(opts_btn)

        self.run_btn = QPushButton("Video erstellen")
        self.run_btn.clicked.connect(self._run_pipeline)
        row.addWidget(self.run_btn)
        return row

    # ── Rechtes Panel ────────────────────────────────────────────────────────

    def _build_right_panel(self):
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.addWidget(self._build_table_group())
        lay.addWidget(self._build_log_group())
        return panel

    def _build_table_group(self):
        grp = QGroupBox("Segmente")
        lay = QVBoxLayout(grp)

        self.segments_table = QTableWidget()
        self.segments_table.setColumnCount(6)
        self.segments_table.setHorizontalHeaderLabels(
            ["Video", "Start (min)", "Dauer (s)", "Titel", "Untertitel", "Audio"]
        )
        header = self.segments_table.horizontalHeader()
        # Alle Spalten manuell verstellbar
        header.setSectionResizeMode(QHeaderView.Interactive)
        # Titel und Untertitel dehnen sich aus, um den Restplatz zu füllen
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.segments_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.segments_table.cellChanged.connect(self._on_cell_changed)
        lay.addWidget(self.segments_table)

        btns = QHBoxLayout()
        up_btn = QPushButton("▲ Hoch")
        up_btn.setToolTip("Segment nach oben verschieben")
        up_btn.clicked.connect(self._move_segment_up)
        btns.addWidget(up_btn)
        down_btn = QPushButton("▼ Runter")
        down_btn.setToolTip("Segment nach unten verschieben")
        down_btn.clicked.connect(self._move_segment_down)
        btns.addWidget(down_btn)
        edit_btn = QPushButton("Bearbeiten")
        edit_btn.setToolTip("Segment in-place bearbeiten")
        edit_btn.clicked.connect(self._edit_segment)
        btns.addWidget(edit_btn)
        rm_btn = QPushButton("Entfernen")
        rm_btn.setToolTip("Entfernt das markierte Segment")
        rm_btn.clicked.connect(self._remove_segment)
        btns.addWidget(rm_btn)
        lay.addLayout(btns)

        # Gesamtdauer-Anzeige
        self.total_duration_label = QLabel("Gesamtdauer: 00:00:00  (0 Segmente)")
        self.total_duration_label.setStyleSheet("font-weight: bold; padding: 4px;")
        lay.addWidget(self.total_duration_label)

        return grp

    def _build_log_group(self):
        grp = QGroupBox("Log")
        lay = QVBoxLayout(grp)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(200)
        self.log_text.setFont(QFont("Monospace", 9))
        lay.addWidget(self.log_text)
        return grp

    # ── Logo ─────────────────────────────────────────────────────────────────

    def _update_logo_preview(self):
        logo = self.options.get("logo_path", "")
        if logo and Path(logo).exists():
            pix = QPixmap(logo)
            if not pix.isNull():
                self.logo_preview.setPixmap(pix)
                self.logo_preview.setText("")
                self.logo_path_label.setText(Path(logo).name)
                return
        self.logo_preview.clear()
        self.logo_preview.setText("Kein\nLogo")
        self.logo_path_label.setText("Kein Logo ausgewählt")

    def _select_logo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Logo auswählen", "",
            "Bilder (*.png *.jpg *.jpeg *.bmp *.svg);;Alle Dateien (*)",
        )
        if path:
            self.options["logo_path"] = path
            self._update_logo_preview()

    def _clear_logo(self):
        self.options["logo_path"] = ""
        self._update_logo_preview()

    # ── Videos ───────────────────────────────────────────────────────────────

    def _load_videos(self):
        if not self.input_dir.exists():
            self.input_dir.mkdir(parents=True, exist_ok=True)

        exts = [".mp4", ".avi", ".mov", ".mkv", ".wmv"]
        videos = []
        for f in self.input_dir.iterdir():
            if f.is_file() and f.suffix.lower() in exts:
                videos.append(str(f.resolve()))
        videos.extend(self.external_videos)

        self.video_combo.clear()
        for vp in sorted(set(videos)):
            name = Path(vp).name
            self.video_combo.addItem(name, vp)

    def _add_video(self):
        dlg = QFileDialog()
        dlg.setFileMode(QFileDialog.ExistingFiles)
        dlg.setNameFilter(
            "Videodateien (*.mp4 *.avi *.mov *.mkv *.wmv);;Alle Dateien (*)"
        )
        dlg.setWindowTitle("Video-Dateien auswählen")
        if dlg.exec_():
            added = 0
            for fp in dlg.selectedFiles():
                if fp not in self.external_videos:
                    self.external_videos.append(fp)
                    added += 1
            if added:
                QMessageBox.information(
                    self, "Erfolg", f"{added} Video(s) hinzugefügt!"
                )
                self._load_videos()

    def _remove_video(self):
        idx = self.video_combo.currentIndex()
        if idx < 0:
            return
        vp = self.video_combo.itemData(idx)
        # Nur extern hinzugefügte Videos dürfen entfernt werden
        if vp in self.external_videos:
            self.external_videos.remove(vp)
            self._load_videos()
        else:
            QMessageBox.information(
                self, "Hinweis",
                "Videos aus dem input/-Ordner können nur dort entfernt werden."
            )

    # ── Segmente laden / speichern ───────────────────────────────────────────

    def _collect_video_paths(self):
        """Sammelt alle Video-Pfade aus der ComboBox."""
        paths = []
        for i in range(self.video_combo.count()):
            vp = self.video_combo.itemData(i)
            if vp:
                paths.append(vp)
        return paths

    def _load_segments(self):
        if not Path(self.csv_file).exists():
            return
        self.segments = []
        try:
            with open(self.csv_file, "r", newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    vp = row.get("videoname", "")
                    if (
                        vp
                        and Path(vp).is_absolute()
                        and not vp.startswith(str(self.input_dir))
                    ):
                        if vp not in self.external_videos:
                            self.external_videos.append(vp)
                    self.segments.append({
                        "videoname": vp,
                        "start_minute": float(row.get("start_minute", 0)),
                        "length_seconds": int(row.get("length_seconds", 0)),
                        "title": row.get("title", ""),
                        "sub_title": row.get("sub_title", ""),
                        "audio": int(row.get("audio", 1)),
                    })
        except Exception as e:
            QMessageBox.warning(self, "Fehler", f"CSV laden: {e}")
        self._update_table()

    def _save_csv(self, silent=False):
        try:
            with open(self.csv_file, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(
                    f,
                    fieldnames=[
                        "videoname", "start_minute", "length_seconds",
                        "title", "sub_title", "audio",
                    ],
                )
                w.writeheader()
                w.writerows(self.segments)
            self._csv_dirty = False
            if not silent:
                QMessageBox.information(
                    self, "Erfolg", f"Gespeichert: {self.csv_file}"
                )
        except Exception as e:
            QMessageBox.warning(self, "Fehler", f"CSV speichern: {e}")

    # ── Tabelle ──────────────────────────────────────────────────────────────

    def _update_table(self):
        self.segments_table.blockSignals(True)
        self.segments_table.setRowCount(len(self.segments))
        for r, seg in enumerate(self.segments):
            name = Path(seg["videoname"]).name
            m = seg["start_minute"]
            mins = int(m)
            secs = int((m - mins) * 60)
            def _ro_item(text):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                return item

            self.segments_table.setItem(r, 0, _ro_item(name))

            start_item = _ro_item(f"{mins:02d}:{secs:02d}")
            start_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.segments_table.setItem(r, 1, start_item)

            dur_item = _ro_item(str(seg["length_seconds"]))
            dur_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.segments_table.setItem(r, 2, dur_item)

            self.segments_table.setItem(r, 3, QTableWidgetItem(seg["title"]))
            self.segments_table.setItem(r, 4, QTableWidgetItem(seg["sub_title"]))

            audio_item = _ro_item("Ja" if seg["audio"] else "Nein")
            audio_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.segments_table.setItem(r, 5, audio_item)
        self.segments_table.blockSignals(False)
        self._resize_columns_to_content()
        self._update_total_duration()

    def _resize_columns_to_content(self):
        """Passt Spaltenbreite an Inhalt an (außer Stretch-Spalten Titel/Untertitel)."""
        for col in (0, 1, 2, 5):  # Video, Start, Dauer, Audio
            self.segments_table.resizeColumnToContents(col)

    def _update_total_duration(self):
        """Aktualisiert die Gesamtdauer-Anzeige (Segmente + je 1s Textclip)."""
        n = len(self.segments)
        total_secs = sum(seg.get('length_seconds', 0) for seg in self.segments) + n  # +1s pro Textclip
        h = int(total_secs // 3600)
        m = int((total_secs % 3600) // 60)
        s = int(total_secs % 60)
        self.total_duration_label.setText(
            f"Gesamtdauer: {h:02d}:{m:02d}:{s:02d}  ({n} Segment{'e' if n != 1 else ''})"
        )

    def _on_cell_changed(self, row, col):
        if row < 0 or row >= len(self.segments):
            return
        if col == 3:
            self.segments[row]["title"] = self.segments_table.item(row, 3).text()
            self._csv_dirty = True
        elif col == 4:
            self.segments[row]["sub_title"] = self.segments_table.item(row, 4).text()
            self._csv_dirty = True

    def _move_segment_up(self):
        row = self.segments_table.currentRow()
        if row <= 0:
            return
        self.segments[row - 1], self.segments[row] = self.segments[row], self.segments[row - 1]
        self._csv_dirty = True
        self._update_table()
        self.segments_table.selectRow(row - 1)

    def _move_segment_down(self):
        row = self.segments_table.currentRow()
        if row < 0 or row >= len(self.segments) - 1:
            return
        self.segments[row], self.segments[row + 1] = self.segments[row + 1], self.segments[row]
        self._csv_dirty = True
        self._update_table()
        self.segments_table.selectRow(row + 1)

    # ── Segment-Aktionen ─────────────────────────────────────────────────────

    def _add_segment(self):
        idx = self.video_combo.currentIndex()
        if idx < 0:
            QMessageBox.warning(self, "Warnung", "Bitte ein Video auswählen!")
            return
        vp = self.video_combo.itemData(idx)
        if not vp:
            QMessageBox.warning(self, "Warnung", "Bitte ein Video auswählen!")
            return

        t = self.start_time.time()
        start_min = t.minute() + t.second() / 60.0

        self._csv_dirty = True
        self.segments.append({
            "videoname": vp,
            "start_minute": start_min,
            "length_seconds": self.duration_spin.value(),
            "title": self.title_edit.text(),
            "sub_title": self.subtitle_edit.text(),
            "audio": 1 if self.audio_check.isChecked() else 0,
        })
        self._update_table()
        self.title_edit.clear()
        self.subtitle_edit.clear()
        self.start_time.setTime(QTime(0, 0))
        self.duration_spin.setValue(30)

    def _apply_time_range(self):
        dlg = TimeRangeDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            start, end = dlg.parse_times()
            start_sec = start.minute() * 60 + start.second()
            end_sec = end.minute() * 60 + end.second()
            dur = end_sec - start_sec
            if dur <= 0:
                QMessageBox.warning(
                    self, "Warnung", "Endzeit muss nach Startzeit liegen!"
                )
                return
            self.start_time.setTime(start)
            self.duration_spin.setValue(dur)

    def _edit_segment(self):
        row = self.segments_table.currentRow()
        if row < 0:
            QMessageBox.warning(
                self, "Warnung", "Bitte ein Segment zum Bearbeiten auswählen!"
            )
            return
        seg = self.segments[row]

        from src.gui.dialogs import EditSegmentDialog
        dlg = EditSegmentDialog(seg, self._collect_video_paths(), self)
        if dlg.exec_() == QDialog.Accepted:
            self.segments[row] = dlg.collect_segment_data()
            self._csv_dirty = True
            self._update_table()
            self.segments_table.selectRow(row)

    def _remove_segment(self):
        row = self.segments_table.currentRow()
        if row < 0:
            QMessageBox.warning(
                self, "Warnung", "Bitte ein Segment zum Entfernen auswählen!"
            )
            return
        reply = QMessageBox.question(
            self, "Bestätigung", "Segment wirklich entfernen?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.segments.pop(row)
            self._csv_dirty = True
            self._update_table()

    # ── Erweiterte Optionen ──────────────────────────────────────────────────

    def _show_advanced_options(self):
        dlg = YouTubeOptionsDialog(self)
        dlg.no_audio_check.setChecked(self.options["no_audio"])
        dlg.no_youtube_opt_check.setChecked(self.options["no_youtube_opt"])
        dlg.no_bitrate_limit_check.setChecked(self.options.get("no_bitrate_limit", False))
        dlg.shutdown_check.setChecked(self.options["shutdown_after"])
        dlg.youtube_upload_check.setChecked(self.options["youtube_upload"])
        dlg.youtube_title_edit.setText(self.options["youtube_title"])
        dlg.youtube_playlist_edit.setText(self.options["youtube_playlist"])
        dlg.youtube_privacy_combo.setCurrentText(self.options["youtube_privacy"])
        dlg.youtube_tags_edit.setText(self.options["youtube_tags"])

        if dlg.exec_() == QDialog.Accepted:
            self.options.update(dlg.collect_options())

    # ── Pipeline ─────────────────────────────────────────────────────────────

    def _run_pipeline(self):
        if not self.segments:
            QMessageBox.warning(self, "Warnung", "Keine Segmente vorhanden!")
            return
        if self.pipeline_worker and self.pipeline_worker.isRunning():
            QMessageBox.warning(self, "Warnung", "Pipeline läuft bereits!")
            return

        if self._csv_dirty:
            self._save_csv(silent=True)

        pipeline_opts = {
            "input_dir": str(self.input_dir),
            "output_file": None,
            "no_audio": self.options["no_audio"],
            "youtube_opt": not self.options["no_youtube_opt"],
            "no_bitrate_limit": self.options.get("no_bitrate_limit", False),
            "workers": None,
            "debug_cache": False,
            "logo_path": self.options.get("logo_path", "") or "input/teamlogo.png",
            "upload_only": False,
            "youtube_upload": self.options["youtube_upload"],
            "youtube_title": self.options["youtube_title"],
            "youtube_playlist": self.options["youtube_playlist"],
            "youtube_privacy": self.options["youtube_privacy"],
            "youtube_tags": self.options["youtube_tags"],
            "youtube_category": "17",
        }

        self.log_text.clear()
        self.run_btn.setText("⛔ Abbrechen")
        self.run_btn.clicked.disconnect()
        self.run_btn.clicked.connect(self._cancel_pipeline)

        self.pipeline_worker = PipelineWorker(list(self.segments), pipeline_opts)
        self.pipeline_worker.log_signal.connect(self._on_log)
        self.pipeline_worker.finished_signal.connect(self._on_pipeline_done)
        self.pipeline_worker.start()

    def _on_log(self, msg):
        self.log_text.append(msg)
        # Auto-Scroll ans Ende
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _cancel_pipeline(self):
        """Bricht die laufende Pipeline ab."""
        self.run_btn.setEnabled(False)
        self._on_log("⚠️  Abbruch angefordert – ffmpeg-Prozesse werden beendet...")
        from src.processing import cancel_pipeline
        cancel_pipeline()

    def _on_pipeline_done(self, result):
        self.run_btn.clicked.disconnect()
        self.run_btn.clicked.connect(self._run_pipeline)
        self.run_btn.setEnabled(True)
        self.run_btn.setText("Video erstellen")
        if result["success"]:
            msg = f"Video erstellt: {result['output_file']}"
            vid = result.get("video_id")
            if vid:
                msg += f"\nYouTube: https://www.youtube.com/watch?v={vid}"

            if self.options.get("shutdown_after"):
                self._on_log(f"✅ {msg}")
                self._shutdown_system()
            else:
                QMessageBox.information(self, "Fertig", msg)
        else:
            QMessageBox.critical(
                self, "Fehler", f"Pipeline fehlgeschlagen:\n{result['error']}"
            )

    def _shutdown_system(self):
        """Fährt den Rechner nach einem Countdown herunter (nicht-blockierend)."""
        self._shutdown_remaining = 10
        self._shutdown_dialog = QDialog(self)
        self._shutdown_dialog.setWindowTitle("Herunterfahren")
        self._shutdown_dialog.setFixedSize(370, 130)
        self._shutdown_dialog.setWindowFlags(
            self._shutdown_dialog.windowFlags() | Qt.WindowStaysOnTopHint
        )

        layout = QVBoxLayout(self._shutdown_dialog)
        self._shutdown_label = QLabel(
            f"Rechner wird in {self._shutdown_remaining} Sekunden heruntergefahren…"
        )
        self._shutdown_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._shutdown_label)

        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.clicked.connect(self._cancel_shutdown)
        layout.addWidget(cancel_btn, alignment=Qt.AlignCenter)

        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setInterval(1000)
        self._shutdown_timer.timeout.connect(self._shutdown_tick)
        self._shutdown_timer.start()

        self._on_log(f"🔌 Rechner wird in {self._shutdown_remaining}s heruntergefahren...")
        self._shutdown_dialog.show()

    def _shutdown_tick(self):
        """Countdown-Tick – führt bei 0 das Herunterfahren aus."""
        self._shutdown_remaining -= 1
        if self._shutdown_remaining <= 0:
            self._shutdown_timer.stop()
            self._shutdown_dialog.close()
            self._execute_shutdown()
        else:
            self._shutdown_label.setText(
                f"Rechner wird in {self._shutdown_remaining} Sekunden heruntergefahren…"
            )

    def _cancel_shutdown(self):
        """Bricht den Shutdown-Countdown ab."""
        self._shutdown_timer.stop()
        self._shutdown_dialog.close()
        self._on_log("⚠️  Herunterfahren abgebrochen.")

    def _execute_shutdown(self):
        """Führt den eigentlichen Shutdown-Befehl aus."""
        import platform
        self._on_log("🔌 Rechner wird jetzt heruntergefahren...")
        system = platform.system()
        if system == 'Linux':
            os.system('shutdown -h now "KADERBLICK: Verarbeitung abgeschlossen"')
        elif system == 'Windows':
            os.system('shutdown /s /t 0 /c "KADERBLICK: Verarbeitung abgeschlossen"')
        elif system == 'Darwin':
            os.system('sudo shutdown -h now')
