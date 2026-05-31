import csv
import re
from datetime import time
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from checklists.models import MetricType, Position, TaskTemplate

BASE_DIR = Path(settings.BASE_DIR)

DAY_MAP = {
    'Segunda-feira': 0,
    'Terça-feira': 1,
    'Quarta-feira': 2,
    'Quinta-feira': 3,
    'Sexta-feira': 4,
    'Sábado': 5,
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
    if 'anual' in raw:
        return TaskTemplate.FREQ_ANNUAL
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


def find_position_by_seed_tasks(filename):
    path = BASE_DIR / 'seed' / filename
    if not path.exists():
        return None
    with path.open(newline='', encoding='utf-8-sig') as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            day_label = row.get('List', '').strip()
            title = row.get('Card Name', '').strip()
            if not title:
                continue
            qs = Position.objects.filter(
                task_templates__title=title,
                task_templates__day_of_week=DAY_MAP.get(day_label, 0),
            ).distinct()
            if qs.count() == 1:
                return qs.first()
            return None
    return None


class Command(BaseCommand):
    help = 'Cria/atualiza cargos, tarefas modelo e indicadores, sem alterar usuários.'

    @transaction.atomic
    def handle(self, *args, **options):
        positions = {}
        for code, name, filename in ROLE_FILES:
            position = Position.objects.filter(code=code).first()
            if not position:
                position = Position.objects.filter(name=name).first()
            if not position:
                position = find_position_by_seed_tasks(filename)
            if not position:
                position = Position.objects.create(
                    code=code,
                    name=name,
                    description='Checklist operacional controlado por cargo, com execução registrada por usuário nominal.',
                    active=True,
                )
            positions[code] = position

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
                    expected_result = extract_line(description, 'Meta/resultado')
                    proof_location = extract_line(description, 'Onde comprovar')
                    category = extract_line(description, 'Categoria original') or extract_line(description, 'Etiquetas sugeridas')
                    template, created = TaskTemplate.objects.get_or_create(
                        position=position,
                        title=title,
                        day_of_week=DAY_MAP.get(day_label, 0),
                        defaults={
                            'description': description,
                            'frequency': parse_frequency(description),
                            'start_time': start_time,
                            'end_time': end_time,
                            'category': category[:120],
                            'expected_result': expected_result[:300],
                            'requires_evidence': bool(evidence),
                            'evidence_required': evidence[:300],
                            'proof_location': proof_location[:300],
                            'monthly_goal': expected_result[:255],
                            'order': idx,
                            'active': True,
                        },
                    )
                    if not created:
                        template.description = description
                        template.frequency = parse_frequency(description)
                        template.start_time = start_time
                        template.end_time = end_time
                        template.category = category[:120]
                        template.expected_result = expected_result[:300]
                        template.requires_evidence = bool(evidence)
                        template.evidence_required = evidence[:300]
                        template.proof_location = proof_location[:300]
                        template.monthly_goal = expected_result[:255]
                        template.order = idx
                        template.save()
                    total += 1

        atendente = positions['atendente-comercial']
        instrutor = positions['instrutor-aula-livre']
        metrics = [
            (atendente, 'Comercial', 'leads-mensais', 'Leads registrados no mês', 60, 'leads'),
            (atendente, 'Comercial', 'matriculas-mensais', 'Matrículas fechadas no mês', 12, 'matrículas'),
            (atendente, 'Comercial', 'pesquisas-concorrentes', 'Pesquisas de concorrentes no mês', 20, 'pesquisas'),
            (atendente, 'Comercial', 'avaliacoes-google', 'Avaliações Google solicitadas após aula experimental', 1, 'por aula'),
            (instrutor, 'Pedagógico', 'aulas-registradas', 'Aulas registradas no mês', 1, 'registros'),
            (instrutor, 'Pedagógico', 'projetos-montados', 'Projetos pedagógicos montados/testados no mês', 8, 'projetos'),
            (instrutor, 'Pedagógico', 'feedback-franqueadora', 'Feedbacks quinzenais enviados à franqueadora', 2, 'envios'),
        ]
        for position, area, code, name, target, unit in metrics:
            obj, created = MetricType.objects.get_or_create(
                code=code,
                defaults={
                    'name': name,
                    'area': area,
                    'frequency': MetricType.FREQ_MONTHLY,
                    'position': position,
                    'monthly_target': target,
                    'unit': unit,
                    'active': True,
                },
            )
            obj.name = name
            obj.area = area
            obj.frequency = MetricType.FREQ_MONTHLY
            obj.position = position
            obj.monthly_target = target
            obj.unit = unit
            if created:
                obj.active = True
            obj.save()

        self.stdout.write(self.style.SUCCESS(f'Seed operacional concluído. Tarefas importadas/atualizadas: {total}.'))
