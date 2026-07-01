import threading
from dataclasses import asdict, is_dataclass

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from .audit import log_activity
from .models import SponteSyncJob
from .sponte import import_sponte_courses, import_sponte_students, sync_sponte_free_class_schedule


_ACTIVE_THREADS = set()
_ACTIVE_THREADS_LOCK = threading.Lock()


def enqueue_sponte_sync_job(*, kind, requested_by, period_start=None, period_end=None, allow_past=False):
    active_job = (
        SponteSyncJob.objects
        .filter(
            requested_by=requested_by,
            kind=kind,
            status__in=[SponteSyncJob.STATUS_QUEUED, SponteSyncJob.STATUS_RUNNING],
            period_start=period_start,
            period_end=period_end,
            allow_past=allow_past,
        )
        .order_by('-created_at')
        .first()
    )
    if active_job:
        return active_job, False

    job = SponteSyncJob.objects.create(
        requested_by=requested_by,
        kind=kind,
        period_start=period_start,
        period_end=period_end,
        allow_past=allow_past,
    )
    if getattr(settings, 'SPONTE_SYNC_RUN_INLINE', False):
        run_sponte_sync_job(job.pk)
    else:
        start_sponte_sync_job(job.pk)
    return job, True


def start_sponte_sync_job(job_id):
    with _ACTIVE_THREADS_LOCK:
        if job_id in _ACTIVE_THREADS:
            return
        _ACTIVE_THREADS.add(job_id)
    thread = threading.Thread(target=run_sponte_sync_job, args=(job_id,), daemon=True)
    thread.start()


def run_sponte_sync_job(job_id):
    close_old_connections()
    try:
        job = SponteSyncJob.objects.select_related('requested_by').get(pk=job_id)
        if job.status not in {SponteSyncJob.STATUS_QUEUED, SponteSyncJob.STATUS_RUNNING}:
            return

        job.status = SponteSyncJob.STATUS_RUNNING
        job.started_at = timezone.now()
        job.error_message = ''
        job.save(update_fields=['status', 'started_at', 'error_message', 'updated_at'])

        result = _execute_job(job)
        job.result = _serialize_result(result)
        job.status = SponteSyncJob.STATUS_SUCCEEDED
        job.finished_at = timezone.now()
        job.save(update_fields=['result', 'status', 'finished_at', 'updated_at'])
        _log_job_success(job)
    except Exception as exc:
        SponteSyncJob.objects.filter(pk=job_id).update(
            status=SponteSyncJob.STATUS_FAILED,
            error_message=str(exc)[:2000],
            finished_at=timezone.now(),
            updated_at=timezone.now(),
        )
        _log_job_failure(job_id, exc)
    finally:
        with _ACTIVE_THREADS_LOCK:
            _ACTIVE_THREADS.discard(job_id)
        close_old_connections()


def _execute_job(job):
    if job.kind == SponteSyncJob.KIND_STUDENTS:
        return import_sponte_students()
    if job.kind == SponteSyncJob.KIND_COURSES:
        return import_sponte_courses()
    if job.kind in {SponteSyncJob.KIND_SCHEDULE, SponteSyncJob.KIND_INSTRUCTOR_SCHEDULE}:
        if not job.period_start or not job.period_end:
            raise ValueError('Informe periodo inicial e final para sincronizar agenda Sponte.')
        return sync_sponte_free_class_schedule(
            job.period_start,
            job.period_end,
            allow_past=job.allow_past,
        )
    raise ValueError(f'Tipo de sincronizacao Sponte desconhecido: {job.kind}')


def _serialize_result(result):
    if is_dataclass(result):
        return asdict(result)
    if isinstance(result, dict):
        return result
    return {'result': str(result)}


def _log_job_success(job):
    log_activity(
        actor=job.requested_by,
        action='Sincronizacao Sponte concluida',
        object_type='SponteSyncJob',
        object_id=job.pk,
        object_label=str(job),
        details=_job_details(job),
        new_values=job.result,
    )


def _log_job_failure(job_id, exc):
    try:
        job = SponteSyncJob.objects.select_related('requested_by').get(pk=job_id)
    except SponteSyncJob.DoesNotExist:
        return
    log_activity(
        actor=job.requested_by,
        action='Sincronizacao Sponte falhou',
        object_type='SponteSyncJob',
        object_id=job.pk,
        object_label=str(job),
        details=str(exc)[:2000],
        new_values={'status': job.status, 'error': str(exc)[:500]},
    )


def _job_details(job):
    if job.period_label:
        return f'{job.get_kind_display()} - periodo {job.period_label}.'
    return job.get_kind_display()
