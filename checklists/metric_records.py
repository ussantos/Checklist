import calendar
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from .models import CommercialOpportunity, CommercialOpportunityStageEvent, MetricRecord, MetricType, Position


AUTO_METRIC_RECORD_PREFIX = 'Atualização automática de indicadores comerciais'


@dataclass
class MetricRefreshResult:
    metrics: int = 0
    periods: int = 0
    records_deleted: int = 0
    records_created: int = 0


def _normalize(value):
    text = str(value or '').strip().lower()
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(char for char in text if not unicodedata.combining(char))
    return re.sub(r'\s+', ' ', text)


def _stage_order(label):
    match = re.search(r'\d+', str(label or ''))
    return int(match.group(0)) if match else 0


def _stage_label_from_event(event):
    return event.new_stage_label or getattr(event.new_stage, 'name', '')


def _stage_label_from_opportunity(opportunity):
    return getattr(opportunity.stage, 'name', '')


def _is_won(label):
    normalized = _normalize(label)
    return 'ganha' in normalized or 'matricula' in normalized


def _is_lost(label):
    return 'perdido' in _normalize(label)


def _is_post_sale(label):
    normalized = _normalize(label)
    return 'pos-venda' in normalized or 'pos venda' in normalized


def _period_end(target_date, frequency):
    if frequency == MetricType.FREQ_DAILY:
        return target_date
    if frequency == MetricType.FREQ_ANNUAL:
        return date(target_date.year, 12, 31)
    if frequency == MetricType.FREQ_MONTHLY:
        last_day = calendar.monthrange(target_date.year, target_date.month)[1]
        return date(target_date.year, target_date.month, last_day)
    # Weekly metrics are grouped Monday-Sunday.
    return target_date + timedelta(days=6 - target_date.weekday())


def _period_start(target_date, frequency):
    if frequency == MetricType.FREQ_DAILY:
        return target_date
    if frequency == MetricType.FREQ_ANNUAL:
        return date(target_date.year, 1, 1)
    if frequency == MetricType.FREQ_MONTHLY:
        return date(target_date.year, target_date.month, 1)
    return target_date - timedelta(days=target_date.weekday())


def _iter_periods(start_date, end_date, frequency):
    current = _period_start(start_date, frequency)
    seen = set()
    while current <= end_date:
        period_end = min(_period_end(current, frequency), end_date)
        if period_end not in seen:
            seen.add(period_end)
            yield period_end
        if frequency == MetricType.FREQ_DAILY:
            current += timedelta(days=1)
        elif frequency == MetricType.FREQ_ANNUAL:
            current = date(current.year + 1, 1, 1)
        elif frequency == MetricType.FREQ_MONTHLY:
            year = current.year + (1 if current.month == 12 else 0)
            month = 1 if current.month == 12 else current.month + 1
            current = date(year, month, 1)
        else:
            current += timedelta(days=7)


def _local_date(value):
    if not value:
        return None
    if hasattr(value, 'date') and hasattr(value, 'hour'):
        return timezone.localtime(value).date()
    return value


def _decimal_percent(part, total):
    if not total:
        return Decimal('0.00')
    return (Decimal(part) * Decimal('100') / Decimal(total)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _metric_kind(metric):
    text = _normalize(f'{metric.name} {metric.description} {metric.formula}')
    if 'nps' in text:
        return 'nps'
    if 'renovacao' in text:
        return 'renewal_rate'
    if 'nao imediata' in text or 'conversao adicional' in text:
        return 'followup'
    if 'avaliacao google' in text:
        return 'google_review'
    if 'matricula' in text or 'matriculas' in text or 'ganha' in text:
        return 'won'
    if 'compareceu' in text or 'follow-up' in text or 'follow up' in text:
        return 'followup_or_beyond'
    if 'aula experimental' in text:
        return 'trial_or_beyond'
    if 'lead' in text:
        return 'leads'
    return 'stage_count'


def _event_matches(kind, label):
    order = _stage_order(label)
    if kind == 'trial_or_beyond':
        return order >= 3 and not _is_lost(label)
    if kind == 'followup_or_beyond':
        return order >= 4 and not _is_lost(label)
    if kind in {'won', 'google_review'}:
        return _is_won(label)
    if kind == 'followup':
        return order == 4 and not _is_lost(label)
    if kind == 'stage_count':
        return order > 0
    return False


def _count_events_by_period(metric, kind, events):
    values = defaultdict(Decimal)
    for event in events:
        label = _stage_label_from_event(event)
        if not _event_matches(kind, label):
            continue
        event_date = _local_date(event.created_at)
        if not event_date:
            continue
        values[_period_end(event_date, metric.frequency)] += Decimal('1')
    return values


def _count_leads_by_period(metric, opportunities):
    values = defaultdict(Decimal)
    for opportunity in opportunities:
        created_date = _local_date(opportunity.created_at)
        if created_date:
            values[_period_end(created_date, metric.frequency)] += Decimal('1')
    return values


def _fallback_current_stage_counts(metric, kind, opportunities):
    today = timezone.localdate()
    values = defaultdict(Decimal)
    for opportunity in opportunities:
        label = _stage_label_from_opportunity(opportunity)
        if kind == 'renewal_rate':
            continue
        if _event_matches(kind, label):
            values[_period_end(today, metric.frequency)] += Decimal('1')
    return values


def _renewal_rate_by_period(metric, events):
    post_sale = defaultdict(int)
    won = defaultdict(int)
    for event in events:
        label = _stage_label_from_event(event)
        event_date = _local_date(event.created_at)
        if not event_date:
            continue
        period = _period_end(event_date, metric.frequency)
        if _is_post_sale(label):
            post_sale[period] += 1
        if _is_won(label):
            won[period] += 1
    periods = set(post_sale) | set(won)
    return {period: _decimal_percent(post_sale[period], post_sale[period] + won[period]) for period in periods}


def _source_values(metric, opportunities, events):
    kind = _metric_kind(metric)
    if kind == 'nps':
        return {}
    if kind == 'leads':
        return _count_leads_by_period(metric, opportunities)
    if kind == 'renewal_rate':
        return _renewal_rate_by_period(metric, events)

    values = _count_events_by_period(metric, kind, events)
    if not values:
        values = _fallback_current_stage_counts(metric, kind, opportunities)
    return values


@transaction.atomic
def refresh_commercial_metric_records(*, start_date=None, end_date=None):
    """Materializa registros de indicadores a partir dos dados comerciais reais.

    Os dashboards do Grafana consultam MetricRecord. Esta rotina mantém os
    registros automáticos previsíveis e não toca nos lançamentos de NPS.
    """
    position, _ = Position.objects.get_or_create(
        code='atendente-comercial',
        defaults={'name': 'Atendente Comercial', 'active': True},
    )
    metrics = list(
        MetricType.objects.filter(active=True)
        .exclude(name__icontains='NPS')
        .select_related('position')
        .order_by('area', 'name')
    )
    today = timezone.localdate()
    first_opportunity = CommercialOpportunity.objects.order_by('created_at').values_list('created_at', flat=True).first()
    first_event = CommercialOpportunityStageEvent.objects.order_by('created_at').values_list('created_at', flat=True).first()
    inferred_start = min(
        [item for item in [_local_date(first_opportunity), _local_date(first_event), today] if item]
    )
    start_date = start_date or inferred_start
    end_date = end_date or today
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    opportunities = list(
        CommercialOpportunity.objects.select_related('stage', 'commercial_funnel')
        .filter(created_at__date__lte=end_date)
    )
    events = list(
        CommercialOpportunityStageEvent.objects.select_related('new_stage')
        .filter(created_at__date__range=(start_date, end_date))
    )

    deleted, _ = MetricRecord.objects.filter(
        metric__in=metrics,
        notes__startswith=AUTO_METRIC_RECORD_PREFIX,
    ).delete()
    records = []
    period_count = 0
    for metric in metrics:
        raw_values = _source_values(metric, opportunities, events)
        values = defaultdict(Decimal)
        for period, value in raw_values.items():
            values[min(period, end_date)] += value
        metric_position = metric.position or position
        periods = list(_iter_periods(start_date, end_date, metric.frequency))
        period_count = max(period_count, len(periods))
        for period in periods:
            value = Decimal(values.get(period, Decimal('0'))).quantize(Decimal('0.01'))
            records.append(MetricRecord(
                metric=metric,
                position=metric_position,
                date=period,
                value=value,
                notes=f'{AUTO_METRIC_RECORD_PREFIX}: {metric.name}.',
            ))

    if records:
        MetricRecord.objects.bulk_create(records, batch_size=500)

    return MetricRefreshResult(
        metrics=len(metrics),
        periods=period_count,
        records_deleted=deleted,
        records_created=len(records),
    )
