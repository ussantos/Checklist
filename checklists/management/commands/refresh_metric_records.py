from django.core.management.base import BaseCommand

from checklists.grafana_sync import sync_all_metric_dashboards
from checklists.metric_records import refresh_commercial_metric_records


class Command(BaseCommand):
    help = 'Recalcula registros automáticos de indicadores e, opcionalmente, sincroniza o Grafana.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--no-grafana',
            action='store_true',
            help='Recalcula apenas os registros do Checklist, sem chamar a API do Grafana.',
        )

    def handle(self, *args, **options):
        result = refresh_commercial_metric_records()
        self.stdout.write(self.style.SUCCESS(
            f'Registros recalculados: {result.records_created} criados, {result.records_deleted} removidos.'
        ))
        if options['no_grafana']:
            return

        grafana_results = sync_all_metric_dashboards()
        ok_count = sum(1 for item in grafana_results if item.ok)
        fail_count = len(grafana_results) - ok_count
        if fail_count:
            self.stdout.write(self.style.WARNING(
                f'Grafana sincronizado parcialmente: {ok_count} OK, {fail_count} falha(s).'
            ))
            for item in grafana_results:
                if not item.ok:
                    self.stdout.write(f'- {item.dashboard_uid}: {item.error or item.message}')
        else:
            self.stdout.write(self.style.SUCCESS(f'Grafana sincronizado: {ok_count} dashboard(s).'))
