from django.core.management.base import BaseCommand
from django.db import transaction

from checklists.models import Position


ROLE_POSITIONS = [
    ('atendente-comercial', 'Atendente Comercial'),
    ('instrutor-aula-livre', 'Instrutor de Aula Livre'),
]


class Command(BaseCommand):
    help = 'Cria/atualiza apenas cargos operacionais base, sem recriar atividades ou indicadores removidos.'

    @transaction.atomic
    def handle(self, *args, **options):
        total = 0
        for code, name in ROLE_POSITIONS:
            position, _ = Position.objects.get_or_create(code=code, defaults={'name': name})
            position.name = name
            position.description = 'Cargo operacional controlado por usuário nominal.'
            position.active = True
            position.save()
            total += 1

        self.stdout.write(self.style.SUCCESS(f'Seed operacional concluído. Cargos criados/atualizados: {total}.'))
