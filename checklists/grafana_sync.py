import base64
import json
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify

from .models import MetricType


logger = logging.getLogger(__name__)


@dataclass
class GrafanaSyncResult:
    ok: bool
    message: str
    dashboard_uid: str = ''
    error: str = ''


def metric_dashboard_uid(area):
    slug = slugify(area or 'geral')[:70] or 'geral'
    return f'checklist-metricas-{slug}'


def _grafana_unit(unit):
    normalized = (unit or '').strip().lower()
    if normalized in {'%', 'percentual', 'porcentagem'}:
        return 'percent'
    if normalized in {'r$', 'brl', 'real', 'reais'}:
        return 'currencyBRL'
    if normalized in {'min', 'minuto', 'minutos'}:
        return 'm'
    return 'short'


def choose_metric_visualization(metric):
    """Escolhe o painel por regras programáticas, sem decisão manual por item.

    Regras:
    - escolha manual diferente de "Automático" sempre vence;
    - indicadores percentuais com meta numérica viram gauge;
    - metas de tempo/menor ou igual viram stat para leitura rápida;
    - séries diárias, semanais, mensais e anuais usam timeseries por padrão;
    - indicadores sem histórico numérico suficiente caem em stat.
    """
    explicit = {
        MetricType.VIZ_TIMESERIES: 'timeseries',
        MetricType.VIZ_GAUGE: 'gauge',
        MetricType.VIZ_STAT: 'stat',
        MetricType.VIZ_BAR: 'barchart',
        MetricType.VIZ_TABLE: 'table',
    }
    if metric.visualization_type in explicit:
        return explicit[metric.visualization_type]

    unit = (metric.unit or '').lower()
    name = f'{metric.name} {metric.description} {metric.formula}'.lower()
    has_target = bool(metric.monthly_target or metric.target_min or metric.target_max)
    if '%' in unit or 'percent' in unit:
        return 'gauge' if has_target else 'timeseries'
    if metric.target_direction == MetricType.TARGET_AT_MOST or 'tempo' in name or 'minuto' in name:
        return 'stat'
    if metric.frequency in {
        MetricType.FREQ_DAILY,
        MetricType.FREQ_WEEKLY,
        MetricType.FREQ_MONTHLY,
        MetricType.FREQ_ANNUAL,
    }:
        return 'timeseries'
    return 'stat'


def _target(metric):
    if metric.target_max is not None:
        return Decimal(metric.target_max)
    if metric.monthly_target is not None:
        return Decimal(metric.monthly_target)
    return Decimal('0')


def _thresholds(metric):
    target = _target(metric)
    if target <= 0:
        return {'mode': 'absolute', 'steps': [{'color': 'blue', 'value': None}]}

    if metric.target_direction == MetricType.TARGET_AT_MOST:
        return {
            'mode': 'absolute',
            'steps': [
                {'color': 'green', 'value': None},
                {'color': 'orange', 'value': float(target)},
                {'color': 'red', 'value': float(target * Decimal('1.2'))},
            ],
        }

    warn = target * Decimal('0.7')
    return {
        'mode': 'absolute',
        'steps': [
            {'color': 'red', 'value': None},
            {'color': 'orange', 'value': float(warn)},
            {'color': 'green', 'value': float(target)},
        ],
    }


def _metric_sql(metric, panel_type):
    table = 'checklists_metricrecord'
    position_table = 'checklists_position'
    date_expr = "date_trunc('${periodo:raw}', r.date::timestamp)"
    if panel_type in {'gauge', 'stat'}:
        return f"""
SELECT
  COALESCE(SUM(r.value), 0)::numeric AS "Realizado"
FROM {table} r
WHERE r.metric_id = {metric.id}
  AND $__timeFilter(r.date::timestamp)
""".strip()

    if panel_type == 'table':
        return f"""
SELECT
  r.date::timestamp AS "time",
  p.name AS "Cargo",
  COALESCE(r.executor_full_name, '') AS "Responsável",
  r.value AS "Valor",
  COALESCE(r.notes, '') AS "Observações"
FROM {table} r
JOIN {position_table} p ON p.id = r.position_id
WHERE r.metric_id = {metric.id}
  AND $__timeFilter(r.date::timestamp)
ORDER BY r.date DESC
""".strip()

    if panel_type == 'barchart':
        return f"""
SELECT
  p.name AS "Cargo",
  SUM(r.value)::numeric AS "Realizado"
FROM {table} r
JOIN {position_table} p ON p.id = r.position_id
WHERE r.metric_id = {metric.id}
  AND $__timeFilter(r.date::timestamp)
GROUP BY p.name
ORDER BY p.name
""".strip()

    return f"""
SELECT
  {date_expr} AS "time",
  SUM(r.value)::numeric AS "Realizado"
FROM {table} r
WHERE r.metric_id = {metric.id}
  AND $__timeFilter(r.date::timestamp)
GROUP BY 1
ORDER BY 1
""".strip()


def _panel(metric, panel_id, x, y):
    panel_type = choose_metric_visualization(metric)
    target = _target(metric)
    description = '\n'.join(
        part for part in [
            metric.description,
            f'Fórmula: {metric.formula}' if metric.formula else '',
            f'Meta: {metric.target_text}' if metric.target_text else '',
            f'Fonte: {metric.data_source}' if metric.data_source else '',
        ]
        if part
    )
    defaults = {
        'unit': _grafana_unit(metric.unit),
        'min': 0,
        'thresholds': _thresholds(metric),
    }
    if target > 0 and panel_type in {'gauge', 'stat'}:
        defaults['max'] = float(target)

    return {
        'id': panel_id,
        'type': panel_type,
        'title': metric.name,
        'description': description,
        'datasource': {'type': 'postgres', 'uid': settings.GRAFANA_DATASOURCE_UID},
        'gridPos': {'h': 8, 'w': 8, 'x': x, 'y': y},
        'fieldConfig': {
            'defaults': defaults,
            'overrides': [],
        },
        'options': {
            'reduceOptions': {'values': False, 'calcs': ['lastNotNull'], 'fields': ''},
            'legend': {'displayMode': 'list', 'placement': 'bottom'},
            'tooltip': {'mode': 'single', 'sort': 'none'},
        },
        'targets': [
            {
                'datasource': {'type': 'postgres', 'uid': settings.GRAFANA_DATASOURCE_UID},
                'format': 'table' if panel_type in {'table', 'barchart', 'gauge', 'stat'} else 'time_series',
                'rawQuery': True,
                'rawSql': _metric_sql(metric, panel_type),
                'refId': 'A',
            }
        ],
    }


def build_metric_dashboard(area, metrics):
    panels = []
    panel_ids = {}
    for index, metric in enumerate(metrics, start=1):
        col = (index - 1) % 3
        row = (index - 1) // 3
        panel_id = index
        panel_ids[metric.id] = panel_id
        panels.append(_panel(metric, panel_id, col * 8, row * 8))

    uid = metric_dashboard_uid(area)
    dashboard = {
        'uid': uid,
        'title': f'Checklist - Metas e Indicadores - {area or "Geral"}',
        'tags': ['checklist', 'automatico', 'metas-indicadores'],
        'timezone': 'browser',
        'schemaVersion': 39,
        'refresh': '5m',
        'time': {'from': 'now-90d', 'to': 'now'},
        'templating': {
            'list': [
                {
                    'name': 'periodo',
                    'type': 'custom',
                    'label': 'Período',
                    'query': 'day,week,month,year',
                    'current': {'selected': True, 'text': 'month', 'value': 'month'},
                    'hide': 0,
                }
            ]
        },
        'panels': panels,
    }
    return dashboard, panel_ids


def _grafana_request(method, path, payload=None):
    url = f'{settings.GRAFANA_API_URL}{path}'
    data = None
    headers = {'Accept': 'application/json'}
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    credentials = f'{settings.GRAFANA_ADMIN_USER}:{settings.GRAFANA_ADMIN_PASSWORD}'.encode('utf-8')
    headers['Authorization'] = f'Basic {base64.b64encode(credentials).decode("ascii")}'
    request = Request(url, data=data, headers=headers, method=method)
    retries = max(1, getattr(settings, 'GRAFANA_SYNC_RETRIES', 3))
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            with urlopen(request, timeout=settings.GRAFANA_SYNC_TIMEOUT_SECONDS) as response:
                raw = response.read().decode('utf-8') or '{}'
                return json.loads(raw)
        except HTTPError as exc:
            last_error = exc
            if exc.code < 500 or attempt == retries:
                raise
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt == retries:
                raise
        time.sleep(min(attempt, 3))
    raise last_error


def _post_dashboard(dashboard):
    return _grafana_request('POST', '/api/dashboards/db', {
        'dashboard': dashboard,
        'overwrite': True,
        'message': 'Sincronização automática do Checklist',
    })


def _delete_dashboard(uid):
    try:
        _grafana_request('DELETE', f'/api/dashboards/uid/{uid}')
    except HTTPError as exc:
        if exc.code != 404:
            raise


def clear_metric_dashboards():
    """Remove dashboards automáticos de metas/indicadores do Grafana."""
    removed = []
    if not settings.GRAFANA_SYNC_ENABLED:
        return removed

    dashboards = _grafana_request('GET', '/api/search?tag=metas-indicadores')
    for item in dashboards:
        uid = item.get('uid')
        if not uid:
            continue
        _delete_dashboard(uid)
        removed.append(uid)
    return removed


def _mark_area_failed(area, error):
    MetricType.objects.filter(area=area).update(
        grafana_sync_status=MetricType.GRAFANA_FAILED,
        grafana_last_error=str(error)[:2000],
        grafana_last_sync_at=timezone.now(),
    )


def sync_metric_area(area):
    uid = metric_dashboard_uid(area)
    area_metrics = list(
        MetricType.objects.filter(area=area, active=True)
        .select_related('position', 'activity')
        .order_by('position__name', 'name')
    )

    if not settings.GRAFANA_SYNC_ENABLED:
        MetricType.objects.filter(area=area).update(
            grafana_dashboard_uid=uid,
            grafana_sync_status=MetricType.GRAFANA_DISABLED,
            grafana_last_error='Sincronização com Grafana desativada por configuração.',
            grafana_last_sync_at=timezone.now(),
        )
        return GrafanaSyncResult(False, 'Sincronização com Grafana desativada.', uid)

    try:
        if not area_metrics:
            _delete_dashboard(uid)
            MetricType.objects.filter(area=area).update(
                grafana_dashboard_uid=uid,
                grafana_panel_id=None,
                grafana_sync_status=MetricType.GRAFANA_DISABLED,
                grafana_last_error='',
                grafana_last_sync_at=timezone.now(),
            )
            return GrafanaSyncResult(True, f'Dashboard {uid} removido ou já ausente.', uid)

        dashboard, panel_ids = build_metric_dashboard(area, area_metrics)
        _post_dashboard(dashboard)
        now = timezone.now()
        for metric in area_metrics:
            MetricType.objects.filter(pk=metric.pk).update(
                grafana_dashboard_uid=uid,
                grafana_panel_id=panel_ids.get(metric.id),
                grafana_sync_status=MetricType.GRAFANA_SYNCED,
                grafana_last_error='',
                grafana_last_sync_at=now,
            )
        MetricType.objects.filter(area=area, active=False).update(
            grafana_dashboard_uid=uid,
            grafana_panel_id=None,
            grafana_sync_status=MetricType.GRAFANA_DISABLED,
            grafana_last_sync_at=now,
        )
        return GrafanaSyncResult(True, f'Dashboard {uid} sincronizado.', uid)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        logger.warning('Falha ao sincronizar dashboard Grafana %s: %s', uid, exc)
        _mark_area_failed(area, exc)
        return GrafanaSyncResult(False, 'Falha ao sincronizar dashboard Grafana.', uid, str(exc))


def sync_metric(metric):
    return sync_metric_area(metric.area)


def sync_all_metric_dashboards():
    areas = list(MetricType.objects.order_by('area').values_list('area', flat=True).distinct())
    return [sync_metric_area(area) for area in areas]
