"""
KADERBLICK Video Combiner GUI – Package

Modulstruktur:
    src/gui/dialogs.py      – TimeRangeDialog, YouTubeOptionsDialog
    src/gui/worker.py       – PipelineWorker (QThread)
    src/gui/main_window.py  – VideoSegmentGUI (QMainWindow)
"""

import sys
from PyQt5.QtWidgets import QApplication
from src.gui.main_window import VideoSegmentGUI


def main():
    """Startet die GUI-Anwendung."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    win = VideoSegmentGUI()
    win.show()
    sys.exit(app.exec_())
