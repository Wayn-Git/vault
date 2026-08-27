"""Task domain: one write path, shared by the tool, the API and the sync."""

from psok.tasks.service import (
    TaskError,
    TaskService,
    describe_task,
)

__all__ = ["TaskError", "TaskService", "describe_task"]
