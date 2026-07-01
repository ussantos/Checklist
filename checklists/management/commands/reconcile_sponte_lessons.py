from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from checklists.sponte import sync_sponte_free_class_schedule


def _parse_date(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError as exc:
        raise CommandError(f'Data inválida: {value}. Use AAAA-MM-DD.') from exc


def _month_end(day):
    next_month = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return next_month - timedelta(days=1)


def _month_chunks(start_date, end_date):
    current = start_date
    while current <= end_date:
        current_end = min(_month_end(current), end_date)
        yield current, current_end
        current = current_end + timedelta(days=1)


class Command(BaseCommand):
    help = 'Reconcilia aulas livres do Sponte no Checklist, usando o Sponte como fonte de verdade.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--start-date',
            default='2025-11-01',
            help='Data inicial no formato AAAA-MM-DD. Padrão: 2025-11-01.',
        )
        parser.add_argument(
            '--end-date',
            default=None,
            help='Data final no formato AAAA-MM-DD. Padrão: hoje.',
        )

    def handle(self, *args, **options):
        start_date = _parse_date(options['start_date'])
        end_date = _parse_date(options['end_date']) if options['end_date'] else timezone.localdate()
        if start_date > end_date:
            raise CommandError('A data inicial não pode ser maior que a data final.')

        totals = {
            'created': 0,
            'updated': 0,
            'unchanged': 0,
            'cancelled': 0,
            'deleted': 0,
            'skipped': 0,
            'students_synced': 0,
            'errors': 0,
        }

        for chunk_start, chunk_end in _month_chunks(start_date, end_date):
            self.stdout.write(f'Reconciliando {chunk_start:%d/%m/%Y} a {chunk_end:%d/%m/%Y}...')
            result = sync_sponte_free_class_schedule(
                chunk_start,
                chunk_end,
                allow_past=True,
                include_inactive_students=True,
            )
            totals['created'] += result.created
            totals['updated'] += result.updated
            totals['unchanged'] += result.unchanged
            totals['cancelled'] += result.cancelled
            totals['deleted'] += result.deleted
            totals['skipped'] += result.skipped
            totals['students_synced'] += result.students_synced
            totals['errors'] += len(result.errors)
            self.stdout.write(
                '  '
                f'criados={result.created}, atualizados={result.updated}, '
                f'inalterados={result.unchanged}, removidos={result.deleted}, '
                f'cancelados={result.cancelled}, ignorados={result.skipped}, '
                f'alunos={result.students_synced}, erros={len(result.errors)}'
            )
            for error in result.errors[:10]:
                self.stdout.write(self.style.WARNING(f'  - {error}'))
            if len(result.errors) > 10:
                self.stdout.write(self.style.WARNING(f'  - ... mais {len(result.errors) - 10} erro(s).'))

        self.stdout.write(self.style.SUCCESS(
            'Reconciliação concluída: '
            f'criados={totals["created"]}, atualizados={totals["updated"]}, '
            f'inalterados={totals["unchanged"]}, removidos={totals["deleted"]}, '
            f'cancelados={totals["cancelled"]}, ignorados={totals["skipped"]}, '
            f'alunos={totals["students_synced"]}, erros={totals["errors"]}.'
        ))
