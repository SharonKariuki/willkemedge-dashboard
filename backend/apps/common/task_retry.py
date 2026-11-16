"""Retrying a Celery task only where a retry can wait.

Production runs tasks inline (CELERY_TASK_ALWAYS_EAGER, no worker). There,
`self.retry()` re-runs the task on the spot, several times in a row, and then
raises out of `.delay()` - so a failed email repeated the SMS sent before it
and turned the request that queued it into a 500. Inline, a failure is logged
and given up on; with a worker it retries after `countdown` as before.
"""
import logging

logger = logging.getLogger(__name__)


def retry_later(task, exc: Exception, countdown: int):
    """Call as `return retry_later(self, exc, countdown)` from a task's except block."""
    if task.request.is_eager:
        logger.error("%s failed and was not retried (no worker): %s", task.name, exc, exc_info=exc)
        return None
    raise task.retry(exc=exc, countdown=countdown) from exc
