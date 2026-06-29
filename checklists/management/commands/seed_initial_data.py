import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from checklists.models import Position, UserProfile


User = get_user_model()

ROLE_POSITIONS = [
    ('atendente-comercial', 'Atendente Comercial'),
    ('instrutor-aula-livre', 'Instrutor de Aula Livre'),
]


def upsert_user(username, password, display_name, is_admin=False, position=None):
    user, created = User.objects.get_or_create(username=username, defaults={
        'first_name': display_name,
        'is_staff': is_admin,
        'is_superuser': is_admin,
        'is_active': True,
    })
    if created or os.environ.get('RESET_INITIAL_PASSWORDS', 'False').lower() == 'true':
        user.set_password(password)
    user.first_name = display_name
    user.last_name = ''
    user.is_staff = is_admin
    user.is_superuser = is_admin
    user.is_active = True
    user.save()

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.display_name = display_name.strip() or username
    profile.system_role = UserProfile.ROLE_ADMIN if is_admin else UserProfile.ROLE_OPERATOR
    profile.position = position
    profile.active = True
    profile.save()
    return user


class Command(BaseCommand):
    help = 'Cria cargos base e usuário administrador inicial, sem recriar atividades ou indicadores removidos.'

    @transaction.atomic
    def handle(self, *args, **options):
        for code, name in ROLE_POSITIONS:
            position, _ = Position.objects.get_or_create(code=code, defaults={'name': name})
            position.name = name
            position.description = 'Cargo operacional controlado por usuário nominal.'
            position.active = True
            position.save()

        initial_password = os.environ.get('INITIAL_CHECKLISTADMIN_PASSWORD')
        if not initial_password:
            raise CommandError('Defina INITIAL_CHECKLISTADMIN_PASSWORD no ambiente antes de executar o seed inicial.')
        upsert_user('checklistadmin', initial_password, 'Administrador Checklist', True)

        for old_username in ['atendente.comercial', 'instrutor.aula.livre']:
            try:
                old_user = User.objects.get(username=old_username)
            except User.DoesNotExist:
                continue
            old_user.is_active = False
            old_user.save(update_fields=['is_active'])
            profile = getattr(old_user, 'userprofile', None)
            if profile:
                profile.active = False
                profile.save(update_fields=['active'])

        self.stdout.write(self.style.SUCCESS('Seed inicial concluído. Cargos base e checklistadmin atualizados.'))
