from datetime import date, time, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from checklists.models import Course, Position, Room, SchoolHoliday, TimeSlot


ROLE_POSITIONS = [
    ('atendente-comercial', 'Atendente Comercial'),
    ('instrutor-aula-livre', 'Instrutor de Aula Livre'),
]

SAMPLE_COURSES = [
    {'name': 'Techbot', 'value': '0.00', 'kit_quantity': 2},
    {'name': 'Programação', 'value': '0.00', 'kit_quantity': 2},
]

SAMPLE_ROOMS = [
    {'name': 'Sala Maker', 'capacity': 4},
    {'name': 'Sala Multiuso', 'capacity': 3},
]

WEEKDAY_SLOT_TIMES = [
    (time(9, 0), time(11, 0)),
    (time(9, 30), time(11, 30)),
    (time(10, 0), time(12, 0)),
    (time(13, 0), time(15, 0)),
    (time(13, 30), time(15, 30)),
    (time(14, 0), time(16, 0)),
    (time(14, 30), time(16, 30)),
    (time(15, 0), time(17, 0)),
    (time(15, 30), time(17, 30)),
    (time(16, 0), time(18, 0)),
    (time(16, 30), time(18, 30)),
]

SATURDAY_SLOT_TIMES = [
    (time(9, 0), time(11, 0)),
    (time(9, 30), time(11, 30)),
    (time(10, 0), time(12, 0)),
    (time(13, 0), time(15, 0)),
    (time(13, 30), time(15, 30)),
]

SAMPLE_TIME_SLOTS = [
    {'weekday': weekday, 'start_time': start_time, 'end_time': end_time}
    for weekday in range(0, 5)
    for start_time, end_time in WEEKDAY_SLOT_TIMES
] + [
    {'weekday': 5, 'start_time': start_time, 'end_time': end_time}
    for start_time, end_time in SATURDAY_SLOT_TIMES
]


def easter_date(year):
    """Return Gregorian Easter for calculating local movable holidays."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def rio_local_holidays_for_year(year):
    easter = easter_date(year)
    return [
        {
            'date': date(year, 1, 20),
            'description': 'Feriado municipal RJ - Sao Sebastiao',
        },
        {
            'date': easter - timedelta(days=47),
            'description': 'Feriado estadual RJ - Terca-feira de Carnaval',
        },
        {
            'date': date(year, 4, 23),
            'description': 'Feriado estadual RJ - Sao Jorge',
        },
        {
            'date': easter + timedelta(days=60),
            'description': 'Feriado estadual RJ - Corpus Christi',
        },
        {
            'date': date(year, 11, 20),
            'description': 'Feriado estadual RJ - Zumbi e Consciencia Negra',
        },
    ]


def rio_local_holidays():
    current_year = date.today().year
    years = range(current_year, current_year + 2)
    return [
        holiday
        for year in years
        for holiday in rio_local_holidays_for_year(year)
    ]


YEAR_END_RECESSES = [
    {
        'start_date': date(2026, 12, 21),
        'end_date': date(2027, 1, 10),
        'description': 'Recesso de fim de ano 2026/2027',
    },
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

        courses_created = 0
        for data in SAMPLE_COURSES:
            _, created = Course.objects.get_or_create(
                name=data['name'],
                defaults={
                    'value': data['value'],
                    'kit_quantity': data['kit_quantity'],
                    'active': True,
                },
            )
            if created:
                courses_created += 1

        rooms_created = 0
        for data in SAMPLE_ROOMS:
            _, created = Room.objects.get_or_create(
                name=data['name'],
                defaults={'capacity': data['capacity'], 'active': True},
            )
            if created:
                rooms_created += 1

        slots_created = 0
        for data in SAMPLE_TIME_SLOTS:
            _, created = TimeSlot.objects.get_or_create(
                weekday=data['weekday'],
                start_time=data['start_time'],
                end_time=data['end_time'],
                defaults={'active': True},
            )
            if created:
                slots_created += 1

        holidays_created = 0
        for data in rio_local_holidays():
            _, created = SchoolHoliday.objects.get_or_create(
                start_date=data['date'],
                end_date=data['date'],
                kind=SchoolHoliday.KIND_INSTITUTIONAL,
                description=data['description'],
                defaults={'active': True},
            )
            if created:
                holidays_created += 1

        recesses_created = 0
        for data in YEAR_END_RECESSES:
            _, created = SchoolHoliday.objects.get_or_create(
                start_date=data['start_date'],
                end_date=data['end_date'],
                kind=SchoolHoliday.KIND_RECESS,
                description=data['description'],
                defaults={'active': True},
            )
            if created:
                recesses_created += 1

        self.stdout.write(
            self.style.SUCCESS(
                'Seed operacional concluído. '
                f'Cargos criados/atualizados: {total}. '
                f'Cursos novos: {courses_created}. '
                f'Salas novas: {rooms_created}. '
                f'Horários novos: {slots_created}. '
                f'Feriados locais novos: {holidays_created}. '
                f'Recessos novos: {recesses_created}.'
            )
        )
