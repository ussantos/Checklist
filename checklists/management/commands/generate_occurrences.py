from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from checklists.models import Position
from checklists.services import create_occurrences_for_positions


class Command(BaseCommand):
    help = 'Gera ocorrências de checklist para uma data ou intervalo de dias úteis.'

    def add_arguments(self, parser):
        parser.add_argument('--date', help='Data YYYY-MM-DD. Padrão: hoje.')
        parser.add_argument('--days', type=int, default=1, help='Quantidade de dias a gerar a partir da data.')

    def handle(self, *args, **options):
        if options['date']:
            start = datetime.strptime(options['date'], '%Y-%m-%d').date()
        else:
            start = timezone.localdate()
        positions = Position.objects.filter(active=True)
        created_days = 0
        for offset in range(options['days']):
            day = start + timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            create_occurrences_for_positions(positions, day)
            created_days += 1
        self.stdout.write(self.style.SUCCESS(f'Ocorrências geradas para {created_days} dia(s).'))
