from decimal import Decimal
from datetime import date, time, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from checklists.models import (
    CommercialFunnel, Course, FunnelModel, FunnelModelField, FunnelStage,
    FunnelType, OpportunityOrigin, Position, Room, SchoolHoliday, TimeSlot,
)


ROLE_POSITIONS = [
    ('atendente-comercial', 'Atendente Comercial'),
    ('instrutor-aula-livre', 'Instrutor de Aula Livre'),
]

DEFAULT_COURSE_VALUE = Decimal('3690.00')
PREMIUM_COURSE_VALUE = Decimal('4190.00')
MY_ROBOT_PLAY_VALUE = Decimal('89.90')
VACATION_CAMP_VALUE = Decimal('129.90')

SAMPLE_COURSES = [
    {'name': 'Firtsbot', 'value': DEFAULT_COURSE_VALUE, 'kit_quantity': 2},
    {'name': 'Onebot', 'value': DEFAULT_COURSE_VALUE, 'kit_quantity': 2},
    {'name': 'Electrobot', 'value': DEFAULT_COURSE_VALUE, 'kit_quantity': 1},
    {'name': 'Skillbot', 'value': DEFAULT_COURSE_VALUE, 'kit_quantity': 1},
    {'name': 'My Robot Business', 'value': DEFAULT_COURSE_VALUE, 'kit_quantity': 4},
    {'name': 'Gamebot', 'value': DEFAULT_COURSE_VALUE, 'kit_quantity': 1},
    {'name': 'Techbot', 'value': DEFAULT_COURSE_VALUE, 'kit_quantity': 2},
    {'name': 'Autobot', 'value': DEFAULT_COURSE_VALUE, 'kit_quantity': 1},
    {'name': '3D Print Lab', 'value': PREMIUM_COURSE_VALUE, 'kit_quantity': 4},
    {'name': 'Inteligência Artificial', 'value': PREMIUM_COURSE_VALUE, 'kit_quantity': 4},
    {'name': 'APP Developer', 'value': DEFAULT_COURSE_VALUE, 'kit_quantity': 4},
    {'name': 'My Robot Play', 'value': MY_ROBOT_PLAY_VALUE, 'kit_quantity': 4},
    {'name': 'Colônia de Férias', 'value': VACATION_CAMP_VALUE, 'kit_quantity': 6},
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
    ]


def rio_local_holidays():
    current_year = date.today().year
    years = range(current_year, current_year + 2)
    return [
        holiday
        for year in years
        for holiday in rio_local_holidays_for_year(year)
    ]


def national_holidays_for_year(year):
    easter = easter_date(year)
    holidays = [
        (date(year, 1, 1), 'Feriado nacional - Confraternizacao Universal'),
        (easter - timedelta(days=2), 'Feriado nacional - Paixao de Cristo'),
        (date(year, 4, 21), 'Feriado nacional - Tiradentes'),
        (date(year, 5, 1), 'Feriado nacional - Dia do Trabalho'),
        (date(year, 9, 7), 'Feriado nacional - Independencia do Brasil'),
        (date(year, 10, 12), 'Feriado nacional - Nossa Senhora Aparecida'),
        (date(year, 11, 2), 'Feriado nacional - Finados'),
        (date(year, 11, 15), 'Feriado nacional - Proclamacao da Republica'),
        (date(year, 11, 20), 'Feriado nacional - Zumbi e Consciencia Negra'),
        (date(year, 12, 25), 'Feriado nacional - Natal'),
    ]
    return [
        {'date': holiday_date, 'description': description}
        for holiday_date, description in holidays
    ]


def national_holidays():
    current_year = date.today().year
    years = range(current_year, current_year + 2)
    return [
        holiday
        for year in years
        for holiday in national_holidays_for_year(year)
    ]


YEAR_END_RECESSES = [
    {
        'start_date': date(2026, 12, 21),
        'end_date': date(2027, 1, 10),
        'description': 'Recesso de fim de ano 2026/2027',
    },
]


COMMERCIAL_FUNNEL_TYPES = [
    {'code': 'interessados', 'name': 'Interessados', 'active': True},
    {'code': 'qualificados', 'name': 'Qualificados', 'active': True},
    {'code': 'parcerias', 'name': 'Parcerias', 'active': True},
    {'code': 'posvenda', 'name': 'Pós-Venda', 'active': True},
]

COMMERCIAL_FUNNEL_STAGES = [
    {'code': '1-contato', 'name': '1 - Contato', 'order': 0, 'active': True},
    {'code': '2-negociando', 'name': '2 - Negociando', 'order': 0, 'active': True},
    {'code': '3-aula-experimental', 'name': '3 - Aula Experimental', 'order': 0, 'active': True},
    {'code': '4-follow-up', 'name': '4 - Follow-Up', 'order': 0, 'active': True},
    {'code': '5-matricula', 'name': '5 - Matricula', 'order': 0, 'active': True},
    {'code': '5-perdido', 'name': '5 - Perdido', 'order': 0, 'active': True},
    {'code': '6-pos-venda', 'name': '6 - Pós-Venda', 'order': 0, 'active': True},
]

COMMERCIAL_OPPORTUNITY_ORIGINS = [
    {'code': 'whatsapp', 'name': 'WhatsApp', 'active': True},
    {'code': 'telefone', 'name': 'Telefone', 'active': True},
    {'code': 'google', 'name': 'Google', 'active': True},
    {'code': 'instagram', 'name': 'Instagram', 'active': True},
    {'code': 'facebook', 'name': 'Facebook', 'active': True},
    {'code': 'presencial', 'name': 'Presencial', 'active': True},
    {'code': 'evento', 'name': 'Evento', 'active': True},
    {'code': 'indicacao', 'name': 'Indicação', 'active': True},
    {'code': 'site', 'name': 'Site', 'active': True},
    {'code': 'youtube', 'name': 'YouTube', 'active': True},
    {'code': 'tiktok', 'name': 'TikTok', 'active': True},
    {
        'code': 'sistema',
        'name': 'Sistema',
        'description': 'Oportunidades criadas automaticamente pelo Checklist.',
        'active': True,
    },
]

COMMERCIAL_FUNNEL_MODELS = [
    {
        'name': 'Modelo Cursos e Aulas Avulsas',
        'active': True,
        'fields': [
            {
                'name': 'Faixa Etária',
                'field_type': FunnelModelField.TYPE_SELECT,
                'required': False,
                'options': ['3-4', '5-6', '7-8', '9-10', '11-12', '13-14', '15-16', '17-18', '18+'],
                'order': 0,
            },
            {
                'name': 'Observações',
                'field_type': FunnelModelField.TYPE_TEXT,
                'required': True,
                'options': [],
                'order': 1,
            },
        ],
    },
    {
        'name': 'Modelo Parcerias',
        'active': True,
        'fields': [
            {
                'name': 'Observações',
                'field_type': FunnelModelField.TYPE_TEXT,
                'required': True,
                'options': [],
                'order': 0,
            },
        ],
    },
    {
        'name': 'Modelo Pós-Venda',
        'funnel_type_code': 'posvenda',
        'stage_code': '6-pos-venda',
        'origin_code': 'sistema',
        'active': True,
        'fields': [],
    },
]

COMMERCIAL_FUNNELS = [
    {'name': 'Interessados', 'model_name': 'Modelo Cursos e Aulas Avulsas', 'active': True},
    {'name': 'Qualificados', 'model_name': 'Modelo Cursos e Aulas Avulsas', 'active': True},
    {'name': 'Parcerias', 'model_name': 'Modelo Parcerias', 'active': True},
    {'name': 'Pós-Venda', 'model_name': 'Modelo Pós-Venda', 'active': True},
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
        courses_updated = 0
        for data in SAMPLE_COURSES:
            max_students_per_slot = data.get('max_students_per_slot', data['kit_quantity'])
            course, created = Course.objects.get_or_create(
                name=data['name'],
                defaults={
                    'value': data['value'],
                    'kit_quantity': data['kit_quantity'],
                    'max_students_per_slot': max_students_per_slot,
                    'active': True,
                },
            )
            if created:
                courses_created += 1
            else:
                changed = False
                if course.value != data['value']:
                    course.value = data['value']
                    changed = True
                if course.kit_quantity != data['kit_quantity']:
                    course.kit_quantity = data['kit_quantity']
                    changed = True
                if course.max_students_per_slot != max_students_per_slot:
                    course.max_students_per_slot = max_students_per_slot
                    changed = True
                if not course.active:
                    course.active = True
                    changed = True
                if changed:
                    course.save(update_fields=['value', 'kit_quantity', 'max_students_per_slot', 'active', 'updated_at'])
                    courses_updated += 1

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

        national_holidays_created = 0
        national_holidays_updated = 0
        for data in national_holidays():
            holiday = SchoolHoliday.objects.filter(
                start_date=data['date'],
                end_date=data['date'],
                kind=SchoolHoliday.KIND_NATIONAL,
                description=data['description'],
            ).first()

            if holiday is None and data['date'].month == 11 and data['date'].day == 20:
                holiday = SchoolHoliday.objects.filter(
                    start_date=data['date'],
                    end_date=data['date'],
                    description__icontains='Zumbi',
                ).first()

            if holiday is None:
                SchoolHoliday.objects.create(
                    start_date=data['date'],
                    end_date=data['date'],
                    kind=SchoolHoliday.KIND_NATIONAL,
                    description=data['description'],
                    active=True,
                )
                national_holidays_created += 1
            else:
                changed = False
                if holiday.kind != SchoolHoliday.KIND_NATIONAL:
                    holiday.kind = SchoolHoliday.KIND_NATIONAL
                    changed = True
                if holiday.description != data['description']:
                    holiday.description = data['description']
                    changed = True
                if not holiday.active:
                    holiday.active = True
                    changed = True
                if changed:
                    holiday.save(update_fields=['kind', 'description', 'active', 'updated_at'])
                    national_holidays_updated += 1

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

        funnel_types_created = 0
        for data in COMMERCIAL_FUNNEL_TYPES:
            _, created = FunnelType.objects.get_or_create(
                code=data['code'],
                defaults={'name': data['name'], 'active': data['active']},
            )
            if created:
                funnel_types_created += 1

        funnel_stages_created = 0
        for data in COMMERCIAL_FUNNEL_STAGES:
            _, created = FunnelStage.objects.get_or_create(
                code=data['code'],
                defaults={
                    'name': data['name'],
                    'description': data.get('description', ''),
                    'order': data['order'],
                    'active': data['active'],
                },
            )
            if created:
                funnel_stages_created += 1

        opportunity_origins_created = 0
        for data in COMMERCIAL_OPPORTUNITY_ORIGINS:
            _, created = OpportunityOrigin.objects.get_or_create(
                code=data['code'],
                defaults={
                    'name': data['name'],
                    'description': data.get('description', ''),
                    'active': data['active'],
                },
            )
            if created:
                opportunity_origins_created += 1

        funnel_models_created = 0
        funnel_model_fields_created = 0
        for data in COMMERCIAL_FUNNEL_MODELS:
            funnel_type = FunnelType.objects.filter(code=data.get('funnel_type_code', '')).first()
            stage = FunnelStage.objects.filter(code=data.get('stage_code', '')).first()
            origin = OpportunityOrigin.objects.filter(code=data.get('origin_code', '')).first()
            defaults = {'active': data['active']}
            if funnel_type:
                defaults['funnel_type'] = funnel_type
            if stage:
                defaults['stage'] = stage
            if origin:
                defaults['origin'] = origin
            funnel_model, created = FunnelModel.objects.get_or_create(
                name=data['name'],
                defaults=defaults,
            )
            if created:
                funnel_models_created += 1
            updates = []
            if funnel_type and not funnel_model.funnel_type_id:
                funnel_model.funnel_type = funnel_type
                updates.append('funnel_type')
            if stage and not funnel_model.stage_id:
                funnel_model.stage = stage
                updates.append('stage')
            if origin and not funnel_model.origin_id:
                funnel_model.origin = origin
                updates.append('origin')
            if updates:
                funnel_model.save(update_fields=[*updates, 'updated_at'])
            for field_data in data['fields']:
                _, field_created = FunnelModelField.objects.get_or_create(
                    funnel_model=funnel_model,
                    name=field_data['name'],
                    defaults={
                        'field_type': field_data['field_type'],
                        'required': field_data['required'],
                        'options': field_data['options'],
                        'order': field_data['order'],
                    },
                )
                if field_created:
                    funnel_model_fields_created += 1

        commercial_funnels_created = 0
        for data in COMMERCIAL_FUNNELS:
            funnel_model = FunnelModel.objects.filter(name=data['model_name']).first()
            if not funnel_model:
                continue
            _, created = CommercialFunnel.objects.get_or_create(
                name=data['name'],
                defaults={'funnel_model': funnel_model, 'active': data['active']},
            )
            if created:
                commercial_funnels_created += 1

        self.stdout.write(
            self.style.SUCCESS(
                'Seed operacional concluído. '
                f'Cargos criados/atualizados: {total}. '
                f'Cursos novos: {courses_created}. '
                f'Cursos atualizados: {courses_updated}. '
                f'Salas novas: {rooms_created}. '
                f'Horários novos: {slots_created}. '
                f'Feriados locais novos: {holidays_created}. '
                f'Feriados nacionais novos: {national_holidays_created}. '
                f'Feriados nacionais atualizados: {national_holidays_updated}. '
                f'Recessos novos: {recesses_created}. '
                f'Tipos de funis novos: {funnel_types_created}. '
                f'Etapas de funis novas: {funnel_stages_created}. '
                f'Origens novas: {opportunity_origins_created}. '
                f'Modelos de funis novos: {funnel_models_created}. '
                f'Campos de modelos novos: {funnel_model_fields_created}. '
                f'Funis novos: {commercial_funnels_created}.'
            )
        )
