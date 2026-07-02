from django.core.management.base import BaseCommand, CommandError

from checklists.audit import log_activity
from checklists.nps_import import import_nps_xlsx


class Command(BaseCommand):
    help = 'Importa respostas NPS de uma planilha XLSX e atualiza o indicador no Grafana.'

    def add_arguments(self, parser):
        parser.add_argument('path', help='Caminho do arquivo XLSX.')
        parser.add_argument(
            '--source-file',
            default='',
            help='Nome amigável do arquivo de origem.',
        )
        parser.add_argument(
            '--replace',
            action='store_true',
            help='Apaga importações NPS anteriores antes de importar.',
        )
        parser.add_argument(
            '--no-grafana',
            action='store_true',
            help='Importa os dados sem tentar sincronizar o Grafana.',
        )

    def handle(self, *args, **options):
        try:
            result = import_nps_xlsx(
                options['path'],
                source_file=options['source_file'] or options['path'],
                replace_existing=options['replace'],
                sync_grafana=not options['no_grafana'],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        batch = result.batch
        self.stdout.write(self.style.SUCCESS(
            'Importação NPS concluída. '
            f'Respostas: {result.imported}. Ignoradas: {result.skipped}. '
            f'Promotores: {batch.promoter_percent if batch else 0}%.'
        ))
        log_activity(
            actor=None,
            action='Importação XLSX de NPS',
            object_type='NPSImport',
            object_id=str(batch.pk if batch else ''),
            object_label=options['source_file'] or options['path'],
            details=(
                f'Importação NPS via comando: {result.imported} respostas válidas, '
                f'{result.skipped} ignoradas.'
            ),
            new_values={
                'imported': result.imported,
                'skipped': result.skipped,
                'errors': result.errors[:20],
                'metric_record': result.metric_record.pk if result.metric_record else None,
            },
        )
        for error in result.errors:
            self.stdout.write(self.style.WARNING(error))
