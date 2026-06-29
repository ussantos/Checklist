import os
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Course, Lesson, PedagogicalStudent, Room


SPONTE_SOURCE = 'Sponte'
DEFAULT_API_URL = 'https://api.sponteeducacional.net.br/WSAPIEdu.asmx'
DEFAULT_STUDENT_SEARCH_PARAMS = 'Nome=%'
LEGACY_STUDENT_SEARCH_PARAMS = {'Situacao=1'}


class SponteConfigurationError(Exception):
    pass


class SponteClientError(Exception):
    pass


@dataclass
class SponteStudentImportResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_processed(self):
        return self.created + self.updated + self.unchanged


@dataclass
class SponteScheduleSyncResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    cancelled: int = 0
    skipped: int = 0
    students_synced: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_processed(self):
        return self.created + self.updated + self.unchanged + self.cancelled


def _truncate(value, max_length):
    value = (value or '').strip()
    return value[:max_length]


def _local_name(tag):
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


def _child_text(element, name):
    for child in list(element):
        if _local_name(child.tag) == name:
            return (child.text or '').strip()
    return ''


def _first_descendant_text(element, name):
    for child in element.iter():
        if child is not element and _local_name(child.tag) == name:
            return (child.text or '').strip()
    return ''


def _normalize(value):
    value = unicodedata.normalize('NFKD', value or '')
    value = ''.join(char for char in value if not unicodedata.combining(char))
    return value.casefold()


def _status_from_sponte(value):
    normalized = _normalize(value)
    inactive_markers = ('inativo', 'cancelad', 'trancad', 'desistent', 'encerrad')
    if any(marker in normalized for marker in inactive_markers):
        return PedagogicalStudent.STATUS_INACTIVE
    return PedagogicalStudent.STATUS_ACTIVE


def _lesson_status_from_sponte(value):
    normalized = _normalize(value)
    if not normalized:
        return Lesson.STATUS_SCHEDULED
    if 'cancel' in normalized:
        return Lesson.STATUS_CANCELLED
    if 'falta' in normalized or 'ausente' in normalized:
        return Lesson.STATUS_ABSENT
    if 'reagend' in normalized or 'remarc' in normalized:
        return Lesson.STATUS_RESCHEDULED
    if 'nao dada' in normalized or 'nao realizada' in normalized or 'nao ministrada' in normalized:
        return Lesson.STATUS_NOT_GIVEN
    if 'presenc' in normalized or 'realiz' in normalized or 'conclu' in normalized:
        return Lesson.STATUS_DONE
    if 'agend' in normalized:
        return Lesson.STATUS_SCHEDULED
    return Lesson.STATUS_SCHEDULED


def _first_child_text(element, *names):
    for name in names:
        value = _child_text(element, name)
        if value:
            return value
    return ''


def _is_success_message(value):
    return (value or '').strip().startswith('01')


def _is_not_found_message(value):
    return (value or '').strip().startswith('43')


def _responsible_name(student_element):
    for container in student_element.iter():
        if _local_name(container.tag) != 'wsResponsaveis':
            continue
        name = _first_descendant_text(container, 'Nome')
        if name:
            return name
    return ''


def parse_sponte_students(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SponteClientError(f'Resposta XML inválida do Sponte: {exc}') from exc

    records = []
    api_messages = []
    for item in root.iter():
        if _local_name(item.tag) != 'wsAluno':
            continue

        operation_return = _child_text(item, 'RetornoOperacao')
        if operation_return and not _is_success_message(operation_return):
            api_messages.append(operation_return)
            if not _child_text(item, 'Nome'):
                continue

        name = _child_text(item, 'Nome')
        external_id = _child_text(item, 'AlunoID')
        enrollment = _child_text(item, 'NumeroMatricula') or _child_text(item, 'RA')
        records.append({
            'name': name,
            'enrollment_number': enrollment,
            'responsible_name': _responsible_name(item),
            'whatsapp': _child_text(item, 'Celular') or _child_text(item, 'Telefone'),
            'status': _status_from_sponte(_child_text(item, 'Situacao')),
            'source': SPONTE_SOURCE,
            'external_id': external_id,
        })

    if not records and api_messages:
        unique_messages = sorted(set(api_messages))
        if not any(_is_not_found_message(message) for message in unique_messages):
            raise SponteClientError('; '.join(unique_messages))
    return records


def _sponte_setting(name, default=''):
    return getattr(settings, name, os.environ.get(name, default))


def _sponte_auth_config():
    api_url = (_sponte_setting('SPONTE_API_URL', DEFAULT_API_URL) or DEFAULT_API_URL).rstrip('/')
    client_code = str(_sponte_setting('SPONTE_CODIGO_CLIENTE', '') or '').strip()
    token = str(_sponte_setting('SPONTE_TOKEN', '') or '').strip()
    timeout = int(_sponte_setting('SPONTE_TIMEOUT_SECONDS', 30) or 30)

    if not client_code or not token:
        raise SponteConfigurationError(
            'Configure SPONTE_CODIGO_CLIENTE e SPONTE_TOKEN no .env antes de usar a integração com o Sponte.'
        )
    return api_url, client_code, token, timeout


def _sponte_config():
    api_url, client_code, token, timeout = _sponte_auth_config()
    search_params = str(_sponte_setting('SPONTE_STUDENT_SEARCH_PARAMS', DEFAULT_STUDENT_SEARCH_PARAMS) or '').strip()
    if search_params in LEGACY_STUDENT_SEARCH_PARAMS:
        search_params = DEFAULT_STUDENT_SEARCH_PARAMS
    return api_url, client_code, token, search_params, timeout


def fetch_sponte_students_xml():
    api_url, client_code, token, search_params, timeout = _sponte_config()
    payload = urlencode({
        'nCodigoCliente': client_code,
        'sToken': token,
        'sParametrosBusca': search_params,
    }).encode('utf-8')
    request = Request(
        f'{api_url}/GetAlunos',
        data=payload,
        headers={'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8'},
        method='POST',
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode('utf-8')
    except HTTPError as exc:
        raise SponteClientError(f'Sponte retornou HTTP {exc.code} ao importar alunos.') from exc
    except URLError as exc:
        raise SponteClientError(f'Não foi possível conectar ao Sponte: {exc.reason}') from exc
    except TimeoutError as exc:
        raise SponteClientError('Tempo esgotado ao conectar ao Sponte.') from exc


def _student_lookup(record):
    external_id = record.get('external_id')
    if external_id:
        student = PedagogicalStudent.objects.filter(source=SPONTE_SOURCE, external_id=external_id).first()
        if student:
            return student

    enrollment = record.get('enrollment_number')
    if enrollment:
        return PedagogicalStudent.objects.filter(enrollment_number__iexact=enrollment).first()
    return None


def import_sponte_student_records(records):
    result = SponteStudentImportResult()
    with transaction.atomic():
        for record in records:
            name = _truncate(record.get('name'), 160)
            external_id = _truncate(record.get('external_id'), 120)
            enrollment = _truncate(record.get('enrollment_number'), 80)
            if not name:
                result.skipped += 1
                result.errors.append('Aluno ignorado porque veio sem nome.')
                continue
            if not external_id and not enrollment:
                result.skipped += 1
                result.errors.append(f'Aluno "{name}" ignorado porque veio sem AlunoID e sem matrícula.')
                continue

            values = {
                'name': name,
                'enrollment_number': enrollment,
                'responsible_name': _truncate(record.get('responsible_name'), 160),
                'whatsapp': _truncate(record.get('whatsapp'), 30),
                'status': record.get('status') or PedagogicalStudent.STATUS_ACTIVE,
                'source': SPONTE_SOURCE,
                'external_id': external_id,
            }
            student = _student_lookup(values)
            if student is None:
                PedagogicalStudent.objects.create(**values)
                result.created += 1
                continue

            changed = False
            for field_name, value in values.items():
                if getattr(student, field_name) != value:
                    setattr(student, field_name, value)
                    changed = True
            if changed:
                student.save(update_fields=[*values.keys(), 'updated_at'])
                result.updated += 1
            else:
                result.unchanged += 1
    return result


def import_sponte_students(fetcher: Callable[[], str] | None = None):
    xml_text = (fetcher or fetch_sponte_students_xml)()
    records = parse_sponte_students(xml_text)
    return import_sponte_student_records(records)


def _parse_sponte_date(value):
    value = (value or '').strip()
    if not value:
        return None
    value = value.split('T', 1)[0].split(' ', 1)[0]
    for date_format in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    return None


def _parse_sponte_time(value):
    value = (value or '').strip()
    if not value:
        return None
    value = value.split(' ', 1)[0]
    for time_format in ('%H:%M:%S', '%H:%M'):
        try:
            return datetime.strptime(value, time_format).time()
        except ValueError:
            continue
    return None


def parse_sponte_free_class_schedule(xml_text, *, student_external_id=''):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SponteClientError(f'Resposta XML inválida do Sponte: {exc}') from exc

    records = []
    api_messages = []
    for agenda in root.iter():
        if _local_name(agenda.tag) != 'wsAgendaAluno':
            continue
        operation_return = _child_text(agenda, 'RetornoOperacao')
        if operation_return:
            api_messages.append(operation_return)
        agenda_student_id = _child_text(agenda, 'AlunoID') or student_external_id
        for item in agenda.iter():
            if _local_name(item.tag) != 'wsAulasLivresAluno':
                continue
            free_class_id = _child_text(item, 'AulaLivreID')
            class_date = _child_text(item, 'DataAula')
            start_time = _child_text(item, 'HorarioInicial')
            end_time = _child_text(item, 'HorarioFinal')
            if not any([free_class_id, class_date, start_time, end_time]):
                continue
            lesson_status = _first_child_text(
                item,
                'SituacaoAula',
                'SituacaoDaAula',
                'Situacao',
                'NomeSituacao',
                'DescricaoSituacao',
                'StatusAula',
                'Status',
            )
            records.append({
                'student_external_id': agenda_student_id,
                'free_class_id': free_class_id,
                'date': class_date,
                'start_time': start_time,
                'end_time': end_time,
                'lesson_status': lesson_status,
                'course_name': _child_text(item, 'NomeCurso') or _child_text(item, 'NomeDisciplina') or 'Curso Sponte',
                'room_name': _child_text(item, 'Sala'),
                'teacher_name': _child_text(item, 'NomeProfessor'),
                'course_external_id': _child_text(item, 'CursoID'),
                'discipline_external_id': _child_text(item, 'DisciplinaID'),
                'teacher_external_id': _child_text(item, 'ProfessorID'),
            })

    if not records and api_messages:
        unique_messages = sorted(set(api_messages))
        if not any(message.startswith('43') for message in unique_messages):
            raise SponteClientError('; '.join(unique_messages))
    return records


def _post_sponte_form(operation, data, error_context):
    api_url, client_code, token, timeout = _sponte_auth_config()
    payload = urlencode({
        'nCodigoCliente': client_code,
        'sToken': token,
        **data,
    }).encode('utf-8')
    request = Request(
        f'{api_url}/{operation}',
        data=payload,
        headers={'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8'},
        method='POST',
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode('utf-8')
    except HTTPError as exc:
        raise SponteClientError(f'Sponte retornou HTTP {exc.code} ao {error_context}.') from exc
    except URLError as exc:
        raise SponteClientError(f'Não foi possível conectar ao Sponte: {exc.reason}') from exc
    except TimeoutError as exc:
        raise SponteClientError(f'Tempo esgotado ao {error_context}.') from exc


def fetch_sponte_student_schedule_xml(student_external_id, start_date, end_date):
    return _post_sponte_form(
        'GetAgendaAluno',
        {
            'nAlunoID': student_external_id,
            'sTurmaID': '',
            'sCursoID': '',
            'dDataInicio': start_date.strftime('%d/%m/%Y'),
            'dDataTermino': end_date.strftime('%d/%m/%Y'),
        },
        'sincronizar agenda do Sponte',
    )


def _course_for_schedule(record):
    name = _truncate(record.get('course_name') or 'Curso Sponte', 160)
    course, _ = Course.objects.get_or_create(
        name=name,
        defaults={
            'description': 'Criado automaticamente pela sincronização de agenda do Sponte.',
            'value': Decimal('0.00'),
            'kit_quantity': 1,
            'max_students_per_slot': 1,
            'active': True,
        },
    )
    return course


def _room_for_schedule(record):
    name = _truncate(record.get('room_name'), 120)
    if not name:
        name = 'Sponte - Sala não informada'
    room, _ = Room.objects.get_or_create(
        name=name,
        defaults={'capacity': 999 if name == 'Sponte - Sala não informada' else 1, 'active': True},
    )
    return room


def import_sponte_free_class_records(student, records, *, start_date, end_date):
    result = SponteScheduleSyncResult(students_synced=1)
    now = timezone.now()
    seen_external_ids = set()
    with transaction.atomic():
        for record in records:
            class_date = _parse_sponte_date(record.get('date'))
            start_time = _parse_sponte_time(record.get('start_time'))
            end_time = _parse_sponte_time(record.get('end_time'))
            free_class_id = _truncate(record.get('free_class_id'), 80)
            if not all([class_date, start_time, end_time, free_class_id]):
                result.skipped += 1
                result.errors.append(f'Aula livre ignorada para {student.name}: dados de data/horário incompletos.')
                continue
            external_id = f'aula_livre:{student.external_id}:{free_class_id}:{class_date.isoformat()}'
            seen_external_ids.add(external_id)
            course = _course_for_schedule(record)
            room = _room_for_schedule(record)
            notes_parts = [
                'Aula Livre sincronizada do Sponte.',
                f'Professor: {record.get("teacher_name") or "-"}',
                f'Situação no Sponte: {record.get("lesson_status") or "-"}',
                f'CursoID: {record.get("course_external_id") or "-"}',
                f'DisciplinaID: {record.get("discipline_external_id") or "-"}',
            ]
            values = {
                'student': student,
                'student_name_snapshot': student.name,
                'responsible_name_snapshot': student.responsible_name,
                'whatsapp_snapshot': student.whatsapp,
                'lesson_type': Lesson.TYPE_REGULAR,
                'course': course,
                'room': room,
                'date': class_date,
                'start_time': start_time,
                'end_time': end_time,
                'status': _lesson_status_from_sponte(record.get('lesson_status')),
                'notes': '\n'.join(notes_parts),
                'source': Lesson.SOURCE_SPONTE,
                'external_id': external_id,
                'synced_at': now,
            }
            lesson = Lesson.objects.filter(source=Lesson.SOURCE_SPONTE, external_id=external_id).first()
            if lesson is None:
                Lesson.objects.create(**values)
                result.created += 1
                continue

            changed = False
            for field_name, value in values.items():
                if getattr(lesson, field_name) != value:
                    setattr(lesson, field_name, value)
                    changed = True
            if changed:
                lesson.save(update_fields=[*values.keys(), 'updated_at'])
                result.updated += 1
            else:
                result.unchanged += 1

        stale_lessons = Lesson.objects.filter(
            source=Lesson.SOURCE_SPONTE,
            student=student,
            date__gte=start_date,
            date__lte=end_date,
            status__in=Lesson.OCCUPYING_STATUSES,
        ).exclude(external_id__in=seen_external_ids)
        result.cancelled = stale_lessons.update(status=Lesson.STATUS_CANCELLED, synced_at=now)
    return result


def sync_sponte_free_class_schedule(start_date, end_date, fetcher=None):
    students = PedagogicalStudent.objects.filter(
        source=SPONTE_SOURCE,
        external_id__gt='',
        status=PedagogicalStudent.STATUS_ACTIVE,
    ).order_by('name')
    result = SponteScheduleSyncResult()
    for student in students:
        try:
            xml_text = (fetcher or fetch_sponte_student_schedule_xml)(student.external_id, start_date, end_date)
            records = parse_sponte_free_class_schedule(xml_text, student_external_id=student.external_id)
            student_result = import_sponte_free_class_records(
                student,
                records,
                start_date=start_date,
                end_date=end_date,
            )
        except SponteClientError as exc:
            result.errors.append(f'{student.name}: {exc}')
            continue
        result.created += student_result.created
        result.updated += student_result.updated
        result.unchanged += student_result.unchanged
        result.cancelled += student_result.cancelled
        result.skipped += student_result.skipped
        result.students_synced += student_result.students_synced
        result.errors.extend(student_result.errors)
    return result


def default_sponte_schedule_window(target_date=None):
    target_date = target_date or timezone.localdate()
    days_back = int(_sponte_setting('SPONTE_SCHEDULE_SYNC_DAYS_BACK', 7) or 7)
    days_ahead = int(_sponte_setting('SPONTE_SCHEDULE_SYNC_DAYS_AHEAD', 90) or 90)
    return target_date - timedelta(days=days_back), target_date + timedelta(days=days_ahead)
