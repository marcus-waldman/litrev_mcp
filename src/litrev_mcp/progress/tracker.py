"""
Progress tracking data model for long-running operations.

Provides a thread-safe, async-friendly progress tracker with
observable state for WebSocket broadcasting.
"""

import asyncio
import time
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field


class TaskStage(str, Enum):
    """Processing stages for a single item."""
    PENDING = "pending"
    EXTRACTING = "extracting"     # PDF text extraction
    CHUNKING = "chunking"         # Text chunking
    EMBEDDING = "embedding"       # OpenAI API call
    SAVING = "saving"             # DuckDB insert
    COMPLETE = "complete"
    ERROR = "error"
    SKIPPED = "skipped"


class TaskStatus(BaseModel):
    """Status of a single item being processed."""
    id: str                       # item_key
    citation_key: Optional[str] = None
    title: str
    stage: TaskStage = TaskStage.PENDING
    chunks_total: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ProgressState(BaseModel):
    """Complete progress state for an operation."""
    operation_id: str             # Unique ID for this operation
    operation_type: str           # e.g., "index_papers"
    project: str
    started_at: datetime

    # Overall progress
    total_items: int = 0
    completed_items: int = 0
    skipped_items: int = 0
    error_items: int = 0

    # Currently active tasks (for parallel processing)
    active_tasks: list[TaskStatus] = Field(default_factory=list)

    # Completed task summaries (keep last N)
    recent_completed: list[TaskStatus] = Field(default_factory=list)

    # Timing
    estimated_remaining_seconds: Optional[float] = None
    items_per_second: float = 0.0

    # Final status
    is_complete: bool = False
    final_message: Optional[str] = None


class ProgressTracker:
    """
    Thread-safe progress tracker with async update broadcasting.

    Usage:
        tracker = ProgressTracker(operation_type="index_papers", project="MI-IC")
        tracker.set_total(25)
        tracker.on_update(callback)  # Register WebSocket broadcaster

        await tracker.start_task("ABC123", "smith_2023", "Paper Title")
        await tracker.update_task("ABC123", stage=TaskStage.EXTRACTING)
        await tracker.complete_task("ABC123", TaskStage.COMPLETE)
    """

    def __init__(
        self,
        operation_type: str,
        project: str,
        operation_id: Optional[str] = None,
    ):
        self.state = ProgressState(
            operation_id=operation_id or str(uuid.uuid4()),
            operation_type=operation_type,
            project=project,
            started_at=datetime.now(),
        )
        self._lock = asyncio.Lock()
        self._callbacks: list[Callable[[ProgressState], Any]] = []
        self._start_time = time.time()
        self._recent_completed_limit = 10

    def on_update(self, callback: Callable[[ProgressState], Any]):
        """Register a callback for state updates (e.g., WebSocket broadcast)."""
        self._callbacks.append(callback)

    def set_total(self, total: int):
        """Set total item count (call before processing starts)."""
        self.state.total_items = total
        asyncio.create_task(self._notify())

    async def _notify(self):
        """Notify all registered callbacks of state change."""
        for callback in self._callbacks:
            try:
                result = callback(self.state)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass  # Don't let callback errors break tracking

    def _update_timing(self):
        """Update timing estimates based on completed items."""
        elapsed = time.time() - self._start_time
        completed = self.state.completed_items + self.state.skipped_items + self.state.error_items

        if completed > 0 and elapsed > 0:
            self.state.items_per_second = completed / elapsed
            remaining = self.state.total_items - completed
            if self.state.items_per_second > 0:
                self.state.estimated_remaining_seconds = remaining / self.state.items_per_second

    async def start_task(
        self,
        item_id: str,
        citation_key: Optional[str],
        title: str,
    ) -> TaskStatus:
        """Register a new task as active."""
        async with self._lock:
            task = TaskStatus(
                id=item_id,
                citation_key=citation_key,
                title=title,
                stage=TaskStage.PENDING,
                started_at=datetime.now(),
            )
            self.state.active_tasks.append(task)
            await self._notify()
            return task

    async def update_task(
        self,
        item_id: str,
        stage: Optional[TaskStage] = None,
        chunks_total: Optional[int] = None,
        error_message: Optional[str] = None,
    ):
        """Update a task's status."""
        async with self._lock:
            for task in self.state.active_tasks:
                if task.id == item_id:
                    if stage is not None:
                        task.stage = stage
                    if chunks_total is not None:
                        task.chunks_total = chunks_total
                    if error_message is not None:
                        task.error_message = error_message
                    break
            await self._notify()

    async def complete_task(
        self,
        item_id: str,
        status: TaskStage,  # COMPLETE, ERROR, or SKIPPED
        error_message: Optional[str] = None,
    ):
        """Move a task from active to completed."""
        async with self._lock:
            task = None
            for i, t in enumerate(self.state.active_tasks):
                if t.id == item_id:
                    task = self.state.active_tasks.pop(i)
                    break

            if task:
                task.stage = status
                task.completed_at = datetime.now()
                if error_message:
                    task.error_message = error_message

                # Update counters
                if status == TaskStage.COMPLETE:
                    self.state.completed_items += 1
                elif status == TaskStage.SKIPPED:
                    self.state.skipped_items += 1
                elif status == TaskStage.ERROR:
                    self.state.error_items += 1

                # Keep in recent completed
                self.state.recent_completed.insert(0, task)
                self.state.recent_completed = self.state.recent_completed[:self._recent_completed_limit]

                self._update_timing()

            await self._notify()

    async def finish(self, message: Optional[str] = None):
        """Mark the operation as complete."""
        async with self._lock:
            self.state.is_complete = True
            self.state.final_message = message
            self.state.estimated_remaining_seconds = 0
            await self._notify()
