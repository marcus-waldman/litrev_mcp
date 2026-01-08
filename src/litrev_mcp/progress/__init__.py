"""
Progress monitoring module for long-running operations.

Provides a browser-based real-time progress dashboard using WebSockets.
"""

from .tracker import ProgressTracker, TaskStage, TaskStatus, ProgressState
from .server import progress_server, ProgressServer

__all__ = [
    "ProgressTracker",
    "TaskStage",
    "TaskStatus",
    "ProgressState",
    "progress_server",
    "ProgressServer",
]
