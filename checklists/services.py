from calendar import monthrange as calendar_monthrange
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.utils import timezone
from .models import (
    ChecklistOccurrence, ChecklistOccurrenceStatusEvent, EmployeeAbsence,
    MetricRecord, MetricType, Position, TaskTemplate, UserProfile,
)

User = get_user_model()

METRIC_PERIOD_DAILY = 'diario'
METRIC_PERIOD_WEEKLY = 'semanal'
METRIC_PERIOD_MONTHLY = 'mensal'
METRIC_PERIOD_ANNUAL = 'anual'
METRIC_PERIOD_CHOICES = [
    (METRIC_PERIOD_DAILY, 'Diário'),
    (METRIC_PERIOD_WEEKLY, 'Semanal'),
    (METRIC_PERIOD_MONTHLY, 'Mensal'),
    (METRIC_PERIOD_ANNUAL, 'Anual'),
]
METRIC_PERIOD_LABELS = dict(METRIC_PERIOD_CHOICES)


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


def active_operator_profiles(position):
    return UserProfile.objects.filter(
        system_role=UserProfile.ROLE_OPERATOR,
        position=position,
        active=True,
        user__is_active=True,
    )


def absence_for_user_on_date(user, target_date):
    profile = get_profile(user)
    if not profile:
        return None
    return EmployeeAbsence.objects.filter(
        profile=profile,
        active=True,
        start_date__lte=target_date,
        end_date__gte=target_date,
    ).select_related('profile', 'profile__position').first()


def user_is_absent_on_date(user, target_date):
    return absence_for_user_on_date(user, target_date) is not None


def position_absences_on_date(position, target_date):
    return EmployeeAbsence.objects.filter(
        profile__position=position,
        profile__system_role=UserProfile.ROLE_OPERATOR,
        profile__active=True,
        profile__user__is_active=True,
        active=True,
        start_date__lte=target_date,
        end_date__gte=target_date,
    ).select_related('profile', 'profile__position').order_by('profile__display_name')


def position_is_fully_absent_on_date(position, target_date):
    profiles = active_operator_profiles(position)
    if not profiles.exists():
        return False
    available = profiles.exclude(
        absences__active=True,
        absences__start_date__lte=target_date,
        absences__end_date__gte=target_date,
    ).exists()
    return not available


def is_occurrence_ignored_by_absence(occurrence):
    if occurrence.status == ChecklistOccurrence.STATUS_DONE:
        return False
    return position_is_fully_absent_on_date(occurrence.position, occurrence.date)


def filter_absence_ignored_occurrences(occurrences):
    return [item for item in occurrences if not is_occurrence_ignored_by_absence(item)]


def create_due_occurrences(position, target_date, user=None):
    """Cria ocorrências previstas para um cargo/data, sem duplicar.

    O método é idempotente: pode ser chamado ao abrir dashboard, checklist ou via
    rotina agendada. A restrição única no banco impede duplicidade.
    """
    if user and user_is_absent_on_date(user, target_date):
        return []
    if position_is_fully_absent_on_date(position, target_date):
        return []

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
                ChecklistOccurrenceStatusEvent.objects.create(
                    occurrence=occurrence,
                    previous_status='',
                    new_status=occurrence.status,
                    changed_by=user,
                )
                created.append(occurrence)
    return created


def format_duration(duration):
    total_seconds = max(0, int(duration.total_seconds()))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f'{hours}h {minutes:02d}min'
    if minutes:
        return f'{minutes}min'
    return f'{seconds}s'


def status_duration_summary(occurrence, as_of=None):
    """Calcula o tempo da ocorrência em cada status no dia da atividade."""
    tz = timezone.get_current_timezone()
    day_start = timezone.make_aware(datetime.combine(occurrence.date, time.min), tz)
    day_end = timezone.make_aware(datetime.combine(occurrence.date + timedelta(days=1), time.min), tz)
    if as_of is None:
        as_of = timezone.now()
    if as_of < day_end:
        day_end = as_of
    if day_end <= day_start:
        day_end = day_start

    tracked_statuses = [status for status, _label in ChecklistOccurrence.OPERATIONAL_STATUS_CHOICES]
    durations = {status: timedelta() for status in tracked_statuses}
    events = list(occurrence.status_events.order_by('changed_at', 'id'))

    if not events:
        start = max(occurrence.created_at, day_start)
        if occurrence.status in durations and start < day_end:
            durations[occurrence.status] += day_end - start
    else:
        current_status = None
        current_start = None
        for event in events:
            if event.changed_at <= day_start:
                current_status = event.new_status
                current_start = day_start
                continue
            if event.changed_at > day_end:
                break
            if current_status in durations and current_start is not None and event.changed_at > current_start:
                durations[current_status] += event.changed_at - current_start
            current_status = event.new_status
            current_start = event.changed_at
        if current_status in durations and current_start is not None and day_end > current_start:
            durations[current_status] += day_end - current_start

    return [
        {
            'status': status,
            'label': ChecklistOccurrence.OPERATIONAL_STATUS_LABELS[status],
            'duration': durations[status],
            'formatted': format_duration(durations[status]),
        }
        for status in tracked_statuses
    ]


def create_occurrences_for_positions(positions, target_date):
    for position in positions:
        create_due_occurrences(position, target_date)


def working_days_between(start_date, end_date):
    current = start_date
    while current <= end_date:
        if current.weekday() < 6:
            yield current
        current += timedelta(days=1)


def month_range(year, month):
    start = timezone.datetime(year, month, 1).date()
    if month == 12:
        end = timezone.datetime(year + 1, 1, 1).date() - timedelta(days=1)
    else:
        end = timezone.datetime(year, month + 1, 1).date() - timedelta(days=1)
    return start, end


def metric_period_range(period, reference_date=None):
    if period not in METRIC_PERIOD_LABELS:
        period = METRIC_PERIOD_MONTHLY
    reference_date = reference_date or timezone.localdate()

    if period == METRIC_PERIOD_DAILY:
        start = end = reference_date
    elif period == METRIC_PERIOD_WEEKLY:
        start = reference_date - timedelta(days=reference_date.weekday())
        end = start + timedelta(days=6)
    elif period == METRIC_PERIOD_ANNUAL:
        start = date(reference_date.year, 1, 1)
        end = date(reference_date.year, 12, 31)
    else:
        start, end = month_range(reference_date.year, reference_date.month)

    return start, end, METRIC_PERIOD_LABELS[period], period


def monthly_summary(year, month, positions):
    start, end = month_range(year, month)
    qs = ChecklistOccurrence.objects.filter(date__range=(start, end), position__in=positions).select_related('position')
    ignored_ids = [
        item.id
        for item in qs
        if is_occurrence_ignored_by_absence(item)
    ]
    qs = qs.exclude(id__in=ignored_ids)
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
    qs = ChecklistOccurrence.objects.filter(
        position__in=positions,
        date__lt=today,
    ).exclude(status__in=[ChecklistOccurrence.STATUS_DONE, ChecklistOccurrence.STATUS_NOT_APPLICABLE]).select_related(
        'position', 'template'
    ).order_by('-date', 'position__name')
    return filter_absence_ignored_occurrences(qs)[:limit]


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


def _quantize_moneyless(value, places='0.01'):
    return Decimal(value).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _rate(value, target):
    if not target:
        return None
    return _quantize_moneyless((value / target) * Decimal('100'), '0.1')


def _days_in_year(year):
    return (date(year + 1, 1, 1) - date(year, 1, 1)).days


def _month_factor(start, end):
    if start.year == end.year and start.month == end.month:
        _, days_in_month = calendar_monthrange(start.year, start.month)
        return Decimal((end - start).days + 1) / Decimal(days_in_month)
    return Decimal((end.year - start.year) * 12 + end.month - start.month + 1)


def metric_target_for_period(metric, start, end):
    """Calcula meta proporcional do indicador para o intervalo selecionado.

    O valor de meta cadastrado no indicador é interpretado conforme a frequência
    configurada nele: diária, semanal, mensal ou anual.
    """
    base = Decimal(metric.monthly_target or 0)
    days = Decimal((end - start).days + 1)
    if metric.frequency == MetricType.FREQ_DAILY:
        factor = days
    elif metric.frequency == MetricType.FREQ_WEEKLY:
        factor = days / Decimal('7')
    elif metric.frequency == MetricType.FREQ_ANNUAL:
        if start.year == end.year:
            factor = days / Decimal(_days_in_year(start.year))
        else:
            factor = Decimal('0')
            cursor = start
            while cursor <= end:
                year_end = min(date(cursor.year, 12, 31), end)
                factor += Decimal((year_end - cursor).days + 1) / Decimal(_days_in_year(cursor.year))
                cursor = year_end + timedelta(days=1)
    else:
        factor = _month_factor(start, end)
    return _quantize_moneyless(base * factor)


def metric_dashboard_data(period, reference_date, positions, user=None):
    start, end, period_label, period = metric_period_range(period, reference_date)
    positions = list(positions)
    position_ids = [position.id for position in positions]

    metrics = list(
        MetricType.objects.filter(active=True)
        .filter(Q(position__in=positions) | Q(position__isnull=True))
        .select_related('position', 'activity')
        .order_by('position__name', 'area', 'name')
    )

    profiles_by_position = defaultdict(list)
    if user:
        profile = get_profile(user)
        if profile and profile.position_id in position_ids:
            profiles_by_position[profile.position_id].append(profile)
    else:
        profiles = UserProfile.objects.filter(
            system_role=UserProfile.ROLE_OPERATOR,
            position_id__in=position_ids,
            active=True,
            user__is_active=True,
        ).select_related('user', 'position').order_by('position__name', 'display_name')
        for profile in profiles:
            profiles_by_position[profile.position_id].append(profile)

    records = MetricRecord.objects.filter(
        date__range=(start, end),
        position_id__in=position_ids,
    ).select_related('metric', 'position', 'created_by', 'created_by__userprofile')
    if user:
        records = records.filter(created_by=user)

    record_totals = defaultdict(Decimal)
    user_totals = defaultdict(Decimal)
    user_labels = {}
    for record in records:
        record_totals[(record.position_id, record.metric_id)] += Decimal(record.value or 0)
        user_id = record.created_by_id or 0
        user_name = record.executor_full_name or 'Sem usuário'
        if record.created_by_id:
            profile = get_profile(record.created_by)
            if profile and profile.display_name:
                user_name = profile.display_name
            else:
                user_name = record.created_by.get_full_name().strip() or record.created_by.username
        user_totals[(record.position_id, record.metric_id, user_id)] += Decimal(record.value or 0)
        user_labels[(record.position_id, user_id)] = user_name

    rows = []
    user_rows = []
    totals_by_position = {}
    for position in positions:
        profiles = profiles_by_position.get(position.id, [])
        operator_count = len(profiles) if profiles else 1
        totals_by_position[position.id] = {
            'position': position.name,
            'target': Decimal('0'),
            'value': Decimal('0'),
            'metric_count': 0,
            'operator_count': len(profiles),
        }

        applicable_metrics = [
            metric for metric in metrics
            if metric.position_id in (None, position.id)
        ]
        for metric in applicable_metrics:
            user_target = metric_target_for_period(metric, start, end)
            target = user_target if user else user_target * Decimal(operator_count)
            value = record_totals.get((position.id, metric.id), Decimal('0'))
            row = {
                'position_id': position.id,
                'position': position.name,
                'area': metric.area,
                'metric': metric.name,
                'activity': metric.activity.title if metric.activity else '',
                'frequency': metric.get_frequency_display(),
                'unit': metric.unit,
                'target': target,
                'value': value,
                'rate': _rate(value, target),
            }
            rows.append(row)
            totals_by_position[position.id]['target'] += target
            totals_by_position[position.id]['value'] += value
            totals_by_position[position.id]['metric_count'] += 1

            if not user and len(profiles) > 1:
                for profile in profiles:
                    person_value = user_totals.get((position.id, metric.id, profile.user_id), Decimal('0'))
                    user_rows.append({
                        'position': position.name,
                        'user': profile.display_name,
                        'area': metric.area,
                        'metric': metric.name,
                        'activity': metric.activity.title if metric.activity else '',
                        'unit': metric.unit,
                        'target': user_target,
                        'value': person_value,
                        'rate': _rate(person_value, user_target),
                    })

    for item in totals_by_position.values():
        item['rate'] = _rate(item['value'], item['target'])
        item['target'] = _quantize_moneyless(item['target'])
        item['value'] = _quantize_moneyless(item['value'])

    for row in rows:
        row['target'] = _quantize_moneyless(row['target'])
        row['value'] = _quantize_moneyless(row['value'])
    for row in user_rows:
        row['target'] = _quantize_moneyless(row['target'])
        row['value'] = _quantize_moneyless(row['value'])

    return {
        'period': period,
        'period_label': period_label,
        'start': start,
        'end': end,
        'position_totals': sorted(totals_by_position.values(), key=lambda item: item['position']),
        'metric_rows': sorted(rows, key=lambda item: (item['position'], item['area'], item['metric'])),
        'user_rows': sorted(user_rows, key=lambda item: (item['position'], item['user'], item['metric'])),
    }
