from django.core.management.base import BaseCommand

from checklists.audit import log_activity
from checklists.backup import get_backup_configuration, run_scheduled_backup_if_due, scheduled_backup_is_due


class Command(BaseCommand):
    help = 'Executa o backup diario se o horario configurado ja venceu e ainda nao rodou hoje.'

    def handle(self, *args, **options):
        config = get_backup_configuration()
        if not scheduled_backup_is_due(config):
            self.stdout.write('Backup agendado ainda nao esta devido.')
            return

        result = run_scheduled_backup_if_due()
        if result is None:
            self.stdout.write('Backup agendado ja executado ou ainda nao devido.')
            return

        log_activity(
            actor=None,
            action='Backup diario agendado executado',
            object_type='BackupConfiguration',
            object_id=str(config.pk),
            object_label=str(config),
            new_values={
                'local_path': str(result.local_path),
                'package_path': str(result.package_path) if result.package_path else '',
                'cloud_status': result.cloud_status,
                'cloud_message': result.cloud_message,
            },
        )
        self.stdout.write(self.style.SUCCESS(f'Backup agendado concluido: {result.local_path}'))
