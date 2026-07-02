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


HISTORICAL_METRICS_DASHBOARD_UID = 'checklist-historico-indicadores'


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


def _dashboard_datasource():
    return {'type': 'postgres', 'uid': settings.GRAFANA_DATASOURCE_UID}


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


def _historical_metric_timeseries_sql():
    return """
SELECT
  date_trunc('${periodo:raw}', r.date::timestamp) AS "time",
  CONCAT(COALESCE(p.name, 'Geral'), ' / ', m.area, ' / ', m.name) AS metric,
  SUM(r.value)::double precision AS value
FROM checklists_metricrecord r
JOIN checklists_metrictype m ON m.id = r.metric_id
LEFT JOIN checklists_position p ON p.id = r.position_id
WHERE $__timeFilter(r.date::timestamp)
  AND m.active = true
  AND (-1 IN (${indicadores:csv}) OR m.id IN (${indicadores:csv}))
GROUP BY 1, 2
ORDER BY 1, 2
""".strip()


def _historical_metric_table_sql():
    return """
SELECT
  COALESCE(p.name, 'Geral') AS "Tipo/Cargo",
  m.area AS "Área",
  m.name AS "Indicador",
  MIN(r.date) AS "Primeiro registro",
  MAX(r.date) AS "Último registro",
  SUM(r.value)::numeric AS "Realizado no período",
  COALESCE(MAX(m.target_text), '') AS "Meta textual",
  COALESCE(MAX(m.unit), '') AS "Unidade"
FROM checklists_metricrecord r
JOIN checklists_metrictype m ON m.id = r.metric_id
LEFT JOIN checklists_position p ON p.id = r.position_id
WHERE $__timeFilter(r.date::timestamp)
  AND m.active = true
  AND (-1 IN (${indicadores:csv}) OR m.id IN (${indicadores:csv}))
GROUP BY p.name, m.area, m.name
ORDER BY m.area, m.name, p.name
""".strip()


def build_historical_metric_dashboard(metrics):
    datasource = _dashboard_datasource()
    metric_variable_query = """
SELECT
  m.id AS __value,
  CONCAT(m.area, ' / ', COALESCE(p.name, 'Geral'), ' / ', m.name) AS __text
FROM checklists_metrictype m
LEFT JOIN checklists_position p ON p.id = m.position_id
WHERE m.active = true
ORDER BY m.area, COALESCE(p.name, 'Geral'), m.name
""".strip()
    return {
        'uid': HISTORICAL_METRICS_DASHBOARD_UID,
        'title': 'Checklist - Histórico Consolidado de Indicadores',
        'tags': ['checklist', 'automatico', 'metas-indicadores', 'historico-indicadores'],
        'timezone': 'browser',
        'schemaVersion': 39,
        'refresh': '5m',
        'time': {'from': 'now-180d', 'to': 'now'},
        'templating': {
            'list': [
                {
                    'name': 'periodo',
                    'type': 'custom',
                    'label': 'Agrupar por',
                    'query': 'day,week,month,year',
                    'current': {'selected': True, 'text': 'month', 'value': 'month'},
                    'hide': 0,
                },
                {
                    'name': 'indicadores',
                    'type': 'query',
                    'label': 'Indicadores',
                    'datasource': datasource,
                    'definition': metric_variable_query,
                    'query': metric_variable_query,
                    'refresh': 1,
                    'sort': 1,
                    'multi': True,
                    'includeAll': True,
                    'allValue': '-1',
                    'current': {'selected': True, 'text': 'Todos', 'value': ['$__all']},
                    'hide': 0,
                },
            ]
        },
        'panels': [
            {
                'id': 1,
                'type': 'timeseries',
                'title': 'Evolução histórica dos indicadores selecionados',
                'description': (
                    'Use a variável Indicadores para marcar quais séries comparar. '
                    'Exemplo: oportunidades ganhas x oportunidades perdidas ao longo do tempo.'
                ),
                'datasource': datasource,
                'gridPos': {'h': 12, 'w': 24, 'x': 0, 'y': 0},
                'fieldConfig': {
                    'defaults': {
                        'unit': 'short',
                        'custom': {
                            'drawStyle': 'line',
                            'lineInterpolation': 'smooth',
                            'lineWidth': 2,
                            'fillOpacity': 12,
                            'showPoints': 'auto',
                        },
                    },
                    'overrides': [],
                },
                'options': {
                    'legend': {'displayMode': 'table', 'placement': 'bottom', 'calcs': ['lastNotNull', 'sum']},
                    'tooltip': {'mode': 'multi', 'sort': 'desc'},
                },
                'targets': [
                    {
                        'datasource': datasource,
                        'format': 'time_series',
                        'rawQuery': True,
                        'rawSql': _historical_metric_timeseries_sql(),
                        'refId': 'A',
                    }
                ],
            },
            {
                'id': 2,
                'type': 'table',
                'title': 'Resumo dos indicadores no período',
                'datasource': datasource,
                'gridPos': {'h': 9, 'w': 24, 'x': 0, 'y': 12},
                'fieldConfig': {
                    'defaults': {'unit': 'short'},
                    'overrides': [],
                },
                'options': {
                    'showHeader': True,
                    'cellHeight': 'sm',
                    'footer': {'show': True, 'reducer': ['sum'], 'fields': ['Realizado no período']},
                },
                'targets': [
                    {
                        'datasource': datasource,
                        'format': 'table',
                        'rawQuery': True,
                        'rawSql': _historical_metric_table_sql(),
                        'refId': 'A',
                    }
                ],
            },
        ],
    }


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


def sync_historical_metric_dashboard():
    uid = HISTORICAL_METRICS_DASHBOARD_UID
    metrics = list(
        MetricType.objects.filter(active=True)
        .select_related('position')
        .order_by('area', 'position__name', 'name')
    )

    if not settings.GRAFANA_SYNC_ENABLED:
        return GrafanaSyncResult(False, 'Sincronização com Grafana desativada.', uid)

    try:
        if not metrics:
            _delete_dashboard(uid)
            return GrafanaSyncResult(True, f'Dashboard {uid} removido ou já ausente.', uid)
        _post_dashboard(build_historical_metric_dashboard(metrics))
        return GrafanaSyncResult(True, f'Dashboard {uid} sincronizado.', uid)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        logger.warning('Falha ao sincronizar dashboard Grafana %s: %s', uid, exc)
        return GrafanaSyncResult(False, 'Falha ao sincronizar dashboard histórico Grafana.', uid, str(exc))


def sync_all_metric_dashboards():
    areas = list(MetricType.objects.order_by('area').values_list('area', flat=True).distinct())
    results = [sync_metric_area(area) for area in areas]
    results.append(sync_historical_metric_dashboard())
    return results
