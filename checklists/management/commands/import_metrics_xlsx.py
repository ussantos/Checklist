from django.core.management.base import BaseCommand, CommandError

from checklists.audit import log_activity
from checklists.metric_import import import_metrics_xlsx


class Command(BaseCommand):
    help = 'Importa metas e indicadores de uma planilha XLSX e sincroniza dashboards Grafana.'

    def add_arguments(self, parser):
        parser.add_argument('path', help='Caminho do arquivo XLSX.')
        parser.add_argument(
            '--no-grafana',
            action='store_true',
            help='Importa os dados sem tentar sincronizar o Grafana.',
        )

    def handle(self, *args, **options):
        try:
            result = import_metrics_xlsx(options['path'], sync_grafana=not options['no_grafana'])
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(
            'Importação concluída. '
            f'Criados: {result.created}. Atualizados: {result.updated}. Ignorados: {result.skipped}.'
        ))
        log_activity(
            actor=None,
            action='Importação XLSX de metas e indicadores',
            object_type='MetricType',
            object_label='Metas e Indicadores',
            details=(
                f'Importação via comando: {result.created} criados, {result.updated} atualizados, '
                f'{result.skipped} ignorados. Áreas sincronizadas: {", ".join(result.synced_areas) or "-"}'
            ),
            new_values={
                'created': result.created,
                'updated': result.updated,
                'skipped': result.skipped,
                'synced_areas': result.synced_areas,
                'errors': result.errors[:20],
            },
        )
        if result.synced_areas:
            self.stdout.write(f'Áreas sincronizadas no Grafana: {", ".join(result.synced_areas)}')
        for error in result.errors:
            self.stdout.write(self.style.WARNING(error))
