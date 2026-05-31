from django.core.management.base import BaseCommand, CommandError

from checklists.audit import log_activity
from checklists.backup import get_backup_configuration, run_backup


class Command(BaseCommand):
    help = 'Executa backup local e, se configurado, envia para Google Drive ou OneDrive via rclone.'

    def handle(self, *args, **options):
        config = get_backup_configuration()
        try:
            result = run_backup(config)
        except Exception as exc:
            log_activity(
                actor=None,
                action='Falha ao executar backup por comando',
                object_type='BackupConfiguration',
                object_id=str(config.pk),
                object_label=str(config),
                details=str(exc)[:1000],
            )
            raise CommandError(str(exc)) from exc

        log_activity(
            actor=None,
            action='Backup executado por comando',
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
        self.stdout.write(self.style.SUCCESS(f'Backup concluido: {result.local_path}'))
        self.stdout.write(f'Nuvem: {result.cloud_status} - {result.cloud_message}')
