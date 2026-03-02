"""
Hintergrund-Worker für die Video-Pipeline.

Führt run_video_pipeline() in einem QThread aus, damit die GUI nicht einfriert.
Kommuniziert per Signal: log_signal (str) und finished_signal (dict).
"""

from PyQt5.QtCore import QThread, pyqtSignal


class PipelineWorker(QThread):
    """Führt run_video_pipeline in einem Hintergrund-Thread aus."""

    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(dict)

    def __init__(self, segments, options):
        super().__init__()
        self.segments = segments
        self.options = options

    def run(self):
        from src.main_utils import run_video_pipeline

        result = run_video_pipeline(
            self.segments,
            self.options,
            log_callback=self.log_signal.emit,
        )
        self.finished_signal.emit(result)
