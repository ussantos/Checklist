from collections import defaultdict
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.utils import timezone
from .models import ChecklistOccurrence, MetricRecord, Position, TaskTemplate

User = get_user_model()


def get_profile(user):
    return getattr(user, 'userprofile', None)


def is_admin_user(user):
    profile = get_profile(user)
    return bool(user.is_staff or user.is_superuser or (profile and profile.is_admin_role))


def get_user_position(user):
    profile = get_profile(user)
    if profile and profile.position and profile.position.active:
        return profile.position
    return None


def visible_positions(user):
    if is_admin_user(user):
        return Position.objects.filter(active=True).order_by('name')
    position = get_user_position(user)
    if position:
        return Position.objects.filter(pk=position.pk)
    return Position.objects.none()


def create_due_occurrences(position, target_date):
    """Cria ocorrências previstas para um cargo/data, sem duplicar.

    O método é idempotente: pode ser chamado ao abrir dashboard, checklist ou via
    rotina agendada. A restrição única no banco impede duplicidade.
    """
    created = []
    templates = TaskTemplate.objects.filter(position=position, active=True)
    for template in templates:
        if template.is_due_on(target_date):
            occurrence, was_created = ChecklistOccurrence.objects.get_or_create(
                template=template,
                position=position,
                date=target_date,
                defaults={'status': ChecklistOccurrence.STATUS_PLANNED},
            )
            if was_created:
                created.append(occurrence)
    return created


def create_occurrences_for_positions(positions, target_date):
    for position in positions:
        create_due_occurrences(position, target_date)


def working_days_between(start_date, end_date):
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            yield current
        current += timedelta(days=1)


def month_range(year, month):
    start = timezone.datetime(year, month, 1).date()
    if month == 12:
        end = timezone.datetime(year + 1, 1, 1).date() - timedelta(days=1)
    else:
        end = timezone.datetime(year, month + 1, 1).date() - timedelta(days=1)
    return start, end


def monthly_summary(year, month, positions):
    start, end = month_range(year, month)
    qs = ChecklistOccurrence.objects.filter(date__range=(start, end), position__in=positions)
    rows = qs.values('position__id', 'position__name').annotate(
        total=Count('id'),
        previsto=Count('id', filter=Q(status=ChecklistOccurrence.STATUS_PLANNED)),
        andamento=Count('id', filter=Q(status=ChecklistOccurrence.STATUS_IN_PROGRESS)),
        concluido=Count('id', filter=Q(status=ChecklistOccurrence.STATUS_DONE)),
        nao_aplica=Count('id', filter=Q(status=ChecklistOccurrence.STATUS_NOT_APPLICABLE)),
        bloqueado=Count('id', filter=Q(status=ChecklistOccurrence.STATUS_BLOCKED)),
    ).order_by('position__name')
    result = []
    for row in rows:
        valid_total = row['total'] - row['nao_aplica']
        done = row['concluido']
        row['completion_rate'] = round((done / valid_total) * 100, 1) if valid_total else 0
        result.append(row)
    return result


def overdue_occurrences(positions, limit=50):
    today = timezone.localdate()
    return ChecklistOccurrence.objects.filter(
        position__in=positions,
        date__lt=today,
    ).exclude(status__in=[ChecklistOccurrence.STATUS_DONE, ChecklistOccurrence.STATUS_NOT_APPLICABLE]).select_related(
        'position', 'template'
    ).order_by('-date', 'position__name')[:limit]


def metrics_summary(year, month, positions):
    start, end = month_range(year, month)
    qs = MetricRecord.objects.filter(date__range=(start, end), position__in=positions).select_related('metric', 'position')
    grouped = defaultdict(lambda: {'value': 0, 'target': 0, 'unit': '', 'position': '', 'metric': ''})
    for rec in qs:
        key = (rec.position_id, rec.metric_id)
        grouped[key]['value'] += float(rec.value)
        grouped[key]['target'] = float(rec.metric.monthly_target)
        grouped[key]['unit'] = rec.metric.unit
        grouped[key]['position'] = rec.position.name
        grouped[key]['metric'] = rec.metric.name
    rows = []
    for item in grouped.values():
        target = item['target']
        item['rate'] = round((item['value'] / target) * 100, 1) if target else None
        rows.append(item)
    return sorted(rows, key=lambda x: (x['position'], x['metric']))
