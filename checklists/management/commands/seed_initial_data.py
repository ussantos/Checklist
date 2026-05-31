import csv
import os
import re
from datetime import time
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from checklists.models import MetricType, Position, TaskTemplate, UserProfile

User = get_user_model()
BASE_DIR = Path(__file__).resolve().parents[4]

DAY_MAP = {
    'Segunda-feira': 0,
    'Terça-feira': 1,
    'Quarta-feira': 2,
    'Quinta-feira': 3,
    'Sexta-feira': 4,
}

ROLE_FILES = [
    ('atendente-comercial', 'Atendente Comercial', 'atendente_comercial_tasks.csv'),
    ('instrutor-aula-livre', 'Instrutor de Aula Livre', 'instrutor_aula_livre_tasks.csv'),
]


def extract_line(text, label):
    pattern = rf'^{re.escape(label)}:\s*(.+)$'
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(1).strip() if match else ''


def parse_frequency(text):
    raw = extract_line(text, 'Frequência').lower()
    if 'quinzen' in raw:
        return TaskTemplate.FREQ_BIWEEKLY
    if 'mensal' in raw:
        return TaskTemplate.FREQ_MONTHLY
    if 'semanal' in raw:
        return TaskTemplate.FREQ_WEEKLY
    if 'quando houver' in text.lower() or 'se houver' in text.lower():
        return TaskTemplate.FREQ_CONDITIONAL
    return TaskTemplate.FREQ_DAILY


def parse_time_range(text):
    period = extract_line(text, 'Período')
    if not period:
        title_period = re.match(r'^(\d{2}:\d{2})(?:-(\d{2}:\d{2}))?', text)
        if title_period:
            period = title_period.group(0)
    times = re.findall(r'(\d{2}):(\d{2})', period)
    start = end = None
    if times:
        start = time(int(times[0][0]), int(times[0][1]))
    if len(times) > 1:
        end = time(int(times[1][0]), int(times[1][1]))
    return start, end


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
    help = 'Cria cargos, usuário administrador inicial, tarefas modelo e indicadores iniciais.'

    @transaction.atomic
    def handle(self, *args, **options):
        positions = {}
        for code, name, _filename in ROLE_FILES:
            position, _ = Position.objects.get_or_create(code=code, defaults={'name': name})
            position.name = name
            position.description = 'Checklist operacional controlado por cargo, com execução registrada por usuário nominal.'
            position.active = True
            position.save()
            positions[code] = position

        initial_password = os.environ.get('INITIAL_CHECKLISTADMIN_PASSWORD') or os.environ.get('INITIAL_CHECKLISTADMIN_PASSWORD')
        if not initial_password:
            raise CommandError('Defina INITIAL_CHECKLISTADMIN_PASSWORD no ambiente antes de executar o seed inicial.')
        upsert_user('checklistadmin', initial_password, 'Administrador Checklist', True)

        # Usuários administrativos pessoais não são criados automaticamente.
        # Usuários operacionais genéricos antigos são desativados para evitar login compartilhado.
        for old_username in ['atendente.comercial', 'instrutor.aula.livre', 'checklistadmin']:
            try:
                old_user = User.objects.get(username=old_username)
            except User.DoesNotExist:
                continue
            if old_username == 'checklistadmin' and not User.objects.filter(username='checklistadmin').exists():
                continue
            old_user.is_active = False
            old_user.save(update_fields=['is_active'])
            profile = getattr(old_user, 'userprofile', None)
            if profile:
                profile.active = False
                profile.save(update_fields=['active'])

        total = 0
        for code, name, filename in ROLE_FILES:
            position = positions[code]
            path = BASE_DIR / 'seed' / filename
            if not path.exists():
                self.stdout.write(self.style.WARNING(f'Arquivo seed não encontrado: {path}'))
                continue
            with path.open(newline='', encoding='utf-8-sig') as fp:
                reader = csv.DictReader(fp)
                for idx, row in enumerate(reader, start=1):
                    day_label = row.get('List', '').strip()
                    title = row.get('Card Name', '').strip()
                    description = row.get('Card Description', '').strip()
                    if not day_label or not title:
                        continue
                    start_time, end_time = parse_time_range(description or title)
                    evidence = extract_line(description, 'Evidência esperada')
                    category = extract_line(description, 'Categoria original') or extract_line(description, 'Etiquetas sugeridas')
                    goal = extract_line(description, 'Meta/resultado')
                    TaskTemplate.objects.update_or_create(
                        position=position,
                        title=title,
                        day_of_week=DAY_MAP.get(day_label, 0),
                        defaults={
                            'description': description,
                            'frequency': parse_frequency(description),
                            'start_time': start_time,
                            'end_time': end_time,
                            'category': category[:120],
                            'evidence_required': evidence[:255],
                            'monthly_goal': goal[:255],
                            'order': idx,
                            'active': True,
                        }
                    )
                    total += 1

        atendente = positions['atendente-comercial']
        instrutor = positions['instrutor-aula-livre']
        metrics = [
            (atendente, 'leads-mensais', 'Leads registrados no mês', 60, 'leads'),
            (atendente, 'matriculas-mensais', 'Matrículas fechadas no mês', 12, 'matrículas'),
            (atendente, 'pesquisas-concorrentes', 'Pesquisas de concorrentes no mês', 20, 'pesquisas'),
            (atendente, 'avaliacoes-google', 'Avaliações Google solicitadas após aula experimental', 1, 'por aula'),
            (instrutor, 'aulas-registradas', 'Aulas registradas no mês', 1, 'registros'),
            (instrutor, 'projetos-montados', 'Projetos pedagógicos montados/testados no mês', 8, 'projetos'),
            (instrutor, 'feedback-franqueadora', 'Feedbacks quinzenais enviados à franqueadora', 2, 'envios'),
        ]
        for position, code, name, target, unit in metrics:
            obj, _ = MetricType.objects.get_or_create(code=code, defaults={'name': name, 'position': position})
            obj.name = name
            obj.position = position
            obj.monthly_target = target
            obj.unit = unit
            obj.active = True
            obj.save()

        self.stdout.write(self.style.SUCCESS(f'Seed concluído. Tarefas importadas/atualizadas: {total}.'))

