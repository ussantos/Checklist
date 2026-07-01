from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone

from .models import SponteSyncJob


@login_required
def sponte_sync_notifications(request):
    cutoff = timezone.now() - timedelta(hours=2)
    jobs = (
        SponteSyncJob.objects
        .filter(requested_by=request.user)
        .filter(
            Q(status__in=[SponteSyncJob.STATUS_QUEUED, SponteSyncJob.STATUS_RUNNING])
            | Q(updated_at__gte=cutoff)
        )
        .order_by('-updated_at')[:8]
    )
    return JsonResponse({'jobs': [_job_payload(job) for job in jobs]})


def _job_payload(job):
    return {
        'id': job.pk,
        'key': f'{job.pk}:{job.status}:{int(job.updated_at.timestamp())}',
        'kind': job.kind,
        'kind_label': job.get_kind_display(),
        'status': job.status,
        'status_label': job.get_status_display(),
        'period': job.period_label,
        'message': _job_message(job),
        'created_at': job.created_at.isoformat(),
        'updated_at': job.updated_at.isoformat(),
    }


def _job_message(job):
    if job.status == SponteSyncJob.STATUS_QUEUED:
        return f'{job.get_kind_display()} Sponte entrou na fila.'
    if job.status == SponteSyncJob.STATUS_RUNNING:
        return f'{job.get_kind_display()} Sponte em execucao. Voce pode continuar usando o sistema.'
    if job.status == SponteSyncJob.STATUS_FAILED:
        return f'{job.get_kind_display()} Sponte falhou: {job.error_message or "erro nao informado"}'

    result = job.result or {}
    if job.kind in {SponteSyncJob.KIND_SCHEDULE, SponteSyncJob.KIND_INSTRUCTOR_SCHEDULE}:
        return (
            f'{job.get_kind_display()} Sponte concluida: '
            f'{result.get("created", 0)} criada(s), {result.get("updated", 0)} atualizada(s), '
            f'{result.get("unchanged", 0)} sem alteracao, {result.get("cancelled", 0)} cancelada(s), '
            f'{result.get("deleted", 0)} removida(s).'
        )
    if job.kind == SponteSyncJob.KIND_COURSES:
        return (
            'Cursos Sponte concluidos: '
            f'{result.get("created", 0)} criado(s), {result.get("updated", 0)} atualizado(s), '
            f'{result.get("unchanged", 0)} sem alteracao.'
        )
    if job.kind == SponteSyncJob.KIND_STUDENTS:
        return (
            'Alunos Sponte concluidos: '
            f'{result.get("created", 0)} criado(s), {result.get("updated", 0)} atualizado(s), '
            f'{result.get("unchanged", 0)} sem alteracao.'
        )
    return f'{job.get_kind_display()} Sponte concluida.'
