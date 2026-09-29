"""Idempotent execution wrapper for scheduler and startup jobs."""

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.operations.models import JobRun, JobStatus


def run_idempotent_job(*, job_name, idempotency_key, callback):
    """Run a callback once for a stable key and persist both success and failure."""
    try:
        with transaction.atomic():
            run = JobRun.objects.create(job_name=job_name, idempotency_key=idempotency_key)
    except IntegrityError:
        return JobRun.objects.get(job_name=job_name, idempotency_key=idempotency_key)

    try:
        result = callback() or {}
    except Exception as exc:
        JobRun.objects.filter(pk=run.pk).update(
            status=JobStatus.FAILED,
            finished_at=timezone.now(),
            error_summary=str(exc)[:500],
        )
        raise
    JobRun.objects.filter(pk=run.pk).update(
        status=JobStatus.SUCCEEDED,
        finished_at=timezone.now(),
        result_summary=result,
    )
    run.refresh_from_db()
    return run
