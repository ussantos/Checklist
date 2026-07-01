import json
import os
import re
import hashlib
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
from django.core.cache import cache as default_cache
from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone

from .models import Course, Lesson, PedagogicalStudent, Room
from .sponte_client import (
    DEFAULT_SPONTE_API_BASE_URL, SponteAPIConfigurationError, SponteAPIDisabledError,
    SponteAPIError, SponteAPITimeoutError, SponteSOAPClient,
)


SPONTE_SOURCE = 'Sponte'
DEFAULT_API_URL = DEFAULT_SPONTE_API_BASE_URL
DEFAULT_REST_API_URL = 'https://integracao.sponteweb.net.br'
DEFAULT_STUDENT_SEARCH_PARAMS = 'Nome=%'
DEFAULT_COURSE_SEARCH_PARAMS = 'Situacao=1'
LEGACY_STUDENT_SEARCH_PARAMS = {'Situacao=1'}
REST_SITUATION_STATUS_LABELS = {
    1: 'Presença',
    2: 'Falta',
    3: 'Não dada',
    4: 'Cancelada',
}


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
class SponteCourseImportResult:
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
    deleted: int = 0
    skipped: int = 0
    students_synced: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_processed(self):
        return self.created + self.updated + self.unchanged + self.cancelled + self.deleted


@dataclass
class SponteContractDiscipline:
    external_id: str = ''
    name: str = ''
    module: int | None = None


@dataclass
class SponteStudentContract:
    contract_id: str = ''
    free_contract_id: str = ''
    number: str = ''
    status: str = ''
    course_external_id: str = ''
    course_name: str = ''
    disciplines: list[SponteContractDiscipline] = field(default_factory=list)


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


def _fix_sponte_mojibake(value):
    value = '' if value is None else str(value)
    if not any(marker in value for marker in ('Ã', 'Â', '�')):
        return value
    try:
        return value.encode('latin1').decode('utf-8')
    except (UnicodeDecodeError, UnicodeEncodeError):
        return value


def _normalize(value):
    value = _fix_sponte_mojibake(value)
    value = unicodedata.normalize('NFKD', value or '')
    value = ''.join(char for char in value if not unicodedata.combining(char))
    return value.casefold()


def _status_from_sponte(value):
    normalized = _normalize(value)
    inactive_markers = ('inativo', 'cancelad', 'trancad', 'desistent', 'encerrad')
    if any(marker in normalized for marker in inactive_markers):
        return PedagogicalStudent.STATUS_INACTIVE
    return PedagogicalStudent.STATUS_ACTIVE


def _active_from_sponte(value):
    normalized = _normalize(value)
    if not normalized:
        return True
    if normalized in {'0', 'false', 'falso', 'nao', 'n', 'no'}:
        return False
    if normalized in {'1', 'true', 'verdadeiro', 'sim', 's', 'yes', 'y'}:
        return True
    inactive_markers = ('inativo', 'cancelad', 'trancad', 'desistent', 'encerrad', 'bloquead', 'desativ')
    return not any(marker in normalized for marker in inactive_markers)


def _lesson_status_from_sponte(value):
    normalized = _normalize(value)
    if not normalized:
        return Lesson.STATUS_NOT_GIVEN
    if 'cancel' in normalized:
        return Lesson.STATUS_CANCELLED
    if 'falta' in normalized or 'ausente' in normalized:
        return Lesson.STATUS_ABSENT
    if 'nao dada' in normalized or 'nao realizada' in normalized or 'nao ministrada' in normalized:
        return Lesson.STATUS_NOT_GIVEN
    if 'dada' in normalized or 'ministrada' in normalized:
        return Lesson.STATUS_DONE
    if 'presenc' in normalized or 'realiz' in normalized or 'conclu' in normalized:
        return Lesson.STATUS_DONE
    if 'agend' in normalized:
        return Lesson.STATUS_NOT_GIVEN
    if 'reagend' in normalized or 'remarc' in normalized:
        return Lesson.STATUS_CANCELLED
    return Lesson.STATUS_NOT_GIVEN


def _normalize_key(value):
    return ''.join(char for char in _normalize(value) if char.isalnum())


def _truthy_sponte_flag(value):
    normalized = _normalize(str(value or '')).strip()
    if not normalized:
        return False
    if normalized in {'0', 'false', 'falso', 'nao', 'n', 'no', 'unchecked', 'desmarcado'}:
        return False
    if normalized in {'1', 'true', 'verdadeiro', 'sim', 's', 'yes', 'y', 'checked', 'marcado', 'x'}:
        return True
    try:
        return Decimal(normalized.replace(',', '.')) > 0
    except Exception:
        return False


def _children_text_map(element):
    return {_local_name(child.tag): (child.text or '').strip() for child in list(element)}


def _lesson_status_choice_label(status):
    return dict(Lesson.STATUS_CHOICES).get(status, '')


def _lesson_status_from_sponte_flags(fields):
    normalized_fields = {_normalize_key(key): value for key, value in fields.items()}

    def marked(*keys):
        wanted = {_normalize_key(key) for key in keys}
        return any(
            key in wanted and _truthy_sponte_flag(value)
            for key, value in normalized_fields.items()
        )

    if marked('C', 'Cancelada', 'Cancelado', 'AulaCancelada', 'SituacaoCancelada'):
        return Lesson.STATUS_CANCELLED
    if marked('NaoDada', 'NaoDado', 'NaoMinistrada', 'NaoRealizada', 'AulaNaoDada'):
        return Lesson.STATUS_NOT_GIVEN
    if marked('F', 'Falta', 'Faltou', 'Ausente', 'Ausencia'):
        return Lesson.STATUS_ABSENT
    if marked('P', 'Presenca', 'Presente', 'Realizada', 'AulaRealizada'):
        return Lesson.STATUS_DONE
    if marked('Reagendada', 'Remarcada'):
        return Lesson.STATUS_CANCELLED
    return ''


def _lesson_status_label_from_sponte_fields(fields):
    status_from_flags = _lesson_status_from_sponte_flags(fields)
    if status_from_flags:
        return _lesson_status_choice_label(status_from_flags)

    status_text = ''
    for key in (
        'SituacaoAula',
        'SituacaoDaAula',
        'Situacao',
        'NomeSituacao',
        'DescricaoSituacao',
        'StatusAula',
        'StatusDaAula',
        'Status',
    ):
        status_text = fields.get(key, '').strip()
        if status_text:
            break

    if not status_text:
        return ''
    return _lesson_status_choice_label(_lesson_status_from_sponte(status_text)) or status_text


def _parse_int(value):
    value = str(value or '').strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _is_success_message(value):
    return (value or '').strip().startswith('01')


def _is_not_found_message(value):
    return (value or '').strip().startswith('43')


def _is_invalid_search_parameter_message(value):
    return '02 - Parâmetros de busca inválidos' in str(value or '')


def _parse_sponte_decimal(value):
    value = (value or '').strip()
    if not value:
        return None
    cleaned = re.sub(r'[^\d,.-]', '', value)
    if not cleaned:
        return None
    if ',' in cleaned and '.' in cleaned:
        cleaned = cleaned.replace('.', '').replace(',', '.')
    elif ',' in cleaned:
        cleaned = cleaned.replace(',', '.')
    try:
        return Decimal(cleaned)
    except Exception:
        return None


def _course_conflict_key(name):
    normalized = _normalize(name)
    normalized = re.sub(r'\b[12](?:[,.]0)?\b', '', normalized)
    return ''.join(char for char in normalized if char.isalnum())


def _course_has_version_two(name):
    return bool(re.search(r'(?<!\d)2(?:[,.]0)?(?!\d)', _normalize(name or '')))


def _course_is_legacy_version(name):
    return bool(re.search(r'(?<!\d)1(?:[,.]0)?(?!\d)', _normalize(name or '')))


COURSE_NAME_FIELDS = ('NomeCurso', 'Curso', 'Nome', 'DescricaoCurso', 'Descricao')
COURSE_ID_FIELDS = ('CursoID', 'IDCurso', 'CodigoCurso', 'Codigo')
COURSE_STATUS_FIELDS = ('Situacao', 'Status', 'StatusCurso')
COURSE_VALUE_FIELDS = ('Valor', 'ValorCurso', 'ValorMensalidade', 'Preco', 'Preço')


def _first_present_field(fields, candidates):
    for field_name in candidates:
        value = fields.get(field_name, '').strip()
        if value:
            return value
    return ''


def parse_sponte_courses(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SponteClientError(f'Resposta XML inválida do Sponte: {exc}') from exc

    records_by_key = {}
    api_messages = []
    for item in root.iter():
        local_name = _local_name(item.tag)
        fields = _children_text_map(item)
        if 'curso' not in _normalize(local_name) and not any(field in fields for field in COURSE_ID_FIELDS):
            continue

        operation_return = fields.get('RetornoOperacao', '')
        if operation_return and not _is_success_message(operation_return):
            api_messages.append(operation_return)
            if not _first_present_field(fields, COURSE_NAME_FIELDS):
                continue

        name = _first_present_field(fields, COURSE_NAME_FIELDS)
        if not name:
            continue
        if _course_is_legacy_version(name):
            continue

        conflict_key = _course_conflict_key(name)
        if not conflict_key:
            continue

        record = {
            'name': name,
            'external_id': _first_present_field(fields, COURSE_ID_FIELDS),
            'active': _active_from_sponte(_first_present_field(fields, COURSE_STATUS_FIELDS)),
            'value': _parse_sponte_decimal(_first_present_field(fields, COURSE_VALUE_FIELDS)),
        }
        previous = records_by_key.get(conflict_key)
        if previous is None or (_course_has_version_two(name) and not _course_has_version_two(previous['name'])):
            records_by_key[conflict_key] = record

    if not records_by_key and api_messages:
        unique_messages = sorted(set(api_messages))
        if not any(_is_not_found_message(message) for message in unique_messages):
            raise SponteClientError('; '.join(unique_messages))
    return list(records_by_key.values())


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


def _sponte_bool_setting(name, default=False):
    value = _sponte_setting(name, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on', 'sim'}


def _sponte_auth_config():
    api_url = (_sponte_setting('SPONTE_API_BASE_URL', '') or _sponte_setting('SPONTE_API_URL', DEFAULT_API_URL) or DEFAULT_API_URL).rstrip('/')
    client_code = str(_sponte_setting('SPONTE_API_CLIENT_CODE', '') or _sponte_setting('SPONTE_CODIGO_CLIENTE', '') or '').strip()
    token = str(_sponte_setting('SPONTE_API_TOKEN', '') or _sponte_setting('SPONTE_TOKEN', '') or '').strip()
    timeout = int(_sponte_setting('SPONTE_API_TIMEOUT_SECONDS', '') or _sponte_setting('SPONTE_TIMEOUT_SECONDS', 30) or 30)

    if not client_code or not token:
        raise SponteConfigurationError(
            'Configure SPONTE_API_CLIENT_CODE e SPONTE_API_TOKEN no .env antes de usar a integração com o Sponte.'
        )
    return api_url, client_code, token, timeout


def _sponte_rest_api_enabled():
    return _sponte_bool_setting('SPONTE_REST_API_ENABLED', False)


def _sponte_rest_required_for_schedule_status():
    return _sponte_bool_setting('SPONTE_REST_API_REQUIRED_FOR_SCHEDULE_STATUS', False)


def _sponte_rest_config():
    api_url = str(_sponte_setting('SPONTE_REST_API_BASE_URL', DEFAULT_REST_API_URL) or DEFAULT_REST_API_URL).rstrip('/')
    client_code = str(
        _sponte_setting('SPONTE_REST_API_CLIENT_CODE', '') or _sponte_setting('SPONTE_API_CLIENT_CODE', '') or ''
    ).strip()
    login = str(_sponte_setting('SPONTE_REST_API_LOGIN', '') or '').strip()
    password = str(_sponte_setting('SPONTE_REST_API_PASSWORD', '') or '').strip()
    timeout = int(_sponte_setting('SPONTE_REST_API_TIMEOUT_SECONDS', '') or _sponte_setting('SPONTE_API_TIMEOUT_SECONDS', 30) or 30)
    token_ttl_minutes = int(_sponte_setting('SPONTE_REST_API_TOKEN_TTL_MINUTES', 50) or 50)

    if not api_url or not client_code or not login or not password:
        raise SponteConfigurationError(
            'Configure SPONTE_REST_API_CLIENT_CODE, SPONTE_REST_API_LOGIN e '
            'SPONTE_REST_API_PASSWORD no .env para sincronizar a Situação da Aula pelo REST do Sponte.'
        )
    return api_url, client_code, login, password, timeout, max(token_ttl_minutes, 1)


def _json_request(url, *, method='GET', payload=None, headers=None, timeout=30, purpose='consultar Sponte REST'):
    headers = {
        'Accept': 'application/json',
        **(headers or {}),
    }
    body = None
    if payload is not None:
        body = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode('utf-8')
    except HTTPError as exc:
        if exc.code == 401:
            raise SponteClientError(
                f'Credenciais REST do Sponte recusadas ao {purpose}. '
                'Revise SPONTE_REST_API_LOGIN e SPONTE_REST_API_PASSWORD.'
            ) from exc
        raise SponteClientError(f'Falha HTTP {exc.code} ao {purpose}.') from exc
    except URLError as exc:
        raise SponteClientError(f'Falha de conexão ao {purpose}: {exc.reason}') from exc
    except TimeoutError as exc:
        raise SponteClientError(f'Tempo esgotado ao {purpose}.') from exc

    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SponteClientError(f'Resposta JSON inválida ao {purpose}.') from exc


def _sponte_rest_login_token(api_url, login, password, timeout, ttl_minutes):
    cache_basis = f'{api_url}|{login}'
    cache_key = 'sponte_rest_token:' + hashlib.sha256(cache_basis.encode('utf-8')).hexdigest()
    cached_token = default_cache.get(cache_key)
    if cached_token:
        return cached_token

    response = _json_request(
        f'{api_url}/api/v1/login',
        method='POST',
        payload={'login': login, 'senha': password},
        timeout=timeout,
        purpose='autenticar no Sponte REST',
    )
    token = (response.get('token') or response.get('Token') or '').strip()
    if not token:
        raise SponteClientError('Sponte REST autenticou sem devolver token JWT.')
    default_cache.set(cache_key, token, ttl_minutes * 60)
    return token


def _sponte_config():
    api_url, client_code, token, timeout = _sponte_auth_config()
    search_params = str(_sponte_setting('SPONTE_STUDENT_SEARCH_PARAMS', DEFAULT_STUDENT_SEARCH_PARAMS) or '').strip()
    if search_params in LEGACY_STUDENT_SEARCH_PARAMS:
        search_params = DEFAULT_STUDENT_SEARCH_PARAMS
    return api_url, client_code, token, search_params, timeout


def fetch_sponte_students_xml():
    *_, search_params, _timeout = _sponte_config()
    return _post_sponte_form(
        'GetAlunos',
        {'sParametrosBusca': search_params},
        'importar alunos do Sponte',
        use_cache=False,
    )


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


def fetch_sponte_courses_xml():
    search_params = str(_sponte_setting('SPONTE_COURSE_SEARCH_PARAMS', DEFAULT_COURSE_SEARCH_PARAMS) or '').strip()
    return _post_sponte_form(
        'GetCursos',
        {'sParametrosBusca': search_params},
        'sincronizar cursos do Sponte',
        use_cache=False,
    )


def _course_lookup(record):
    external_id = _truncate(record.get('external_id'), 120)
    if external_id:
        course = Course.objects.filter(source=Course.SOURCE_SPONTE, external_id=external_id).first()
        if course:
            return course

    name = _truncate(record.get('name'), 160)
    if name:
        course = Course.objects.filter(name__iexact=name).first()
        if course:
            return course

    conflict_key = _course_conflict_key(name)
    if not conflict_key:
        return None

    for course in Course.objects.order_by('-active', 'name'):
        if _course_conflict_key(course.name) == conflict_key:
            return course
    return None


def _deactivate_conflicting_courses(course, record, now):
    conflict_key = _course_conflict_key(record.get('name'))
    if not conflict_key:
        return 0
    count = 0
    for candidate in Course.objects.exclude(pk=course.pk).order_by('name'):
        if _course_conflict_key(candidate.name) != conflict_key:
            continue
        if not candidate.active:
            continue
        candidate.active = False
        candidate.synced_at = now
        candidate.save(update_fields=['active', 'synced_at', 'updated_at'])
        count += 1
    return count


def import_sponte_course_records(records):
    result = SponteCourseImportResult()
    now = timezone.now()
    with transaction.atomic():
        for record in records:
            name = _truncate(record.get('name'), 160)
            external_id = _truncate(record.get('external_id'), 120)
            if not name:
                result.skipped += 1
                result.errors.append('Curso ignorado porque veio sem nome.')
                continue

            course = _course_lookup({'name': name, 'external_id': external_id})
            if course is None:
                Course.objects.create(
                    name=name,
                    description='Criado automaticamente pela sincronização de cursos do Sponte.',
                    value=record.get('value') if record.get('value') is not None else Decimal('0.00'),
                    kit_quantity=1,
                    max_students_per_slot=1,
                    active=record.get('active', True),
                    source=Course.SOURCE_SPONTE,
                    external_id=external_id,
                    synced_at=now,
                )
                result.created += 1
                continue

            resolved_name_conflict = False
            exact_name_conflict = Course.objects.filter(name__iexact=name).exclude(pk=course.pk).first()
            if exact_name_conflict:
                if external_id and course.external_id == external_id and course.name == name:
                    if exact_name_conflict.active:
                        exact_name_conflict.active = False
                        exact_name_conflict.synced_at = now
                        exact_name_conflict.save(update_fields=['active', 'synced_at', 'updated_at'])
                        resolved_name_conflict = True
                elif external_id and exact_name_conflict.external_id == external_id:
                    if course.active:
                        course.active = False
                        course.synced_at = now
                        course.save(update_fields=['active', 'synced_at', 'updated_at'])
                        resolved_name_conflict = True
                    course = exact_name_conflict
                elif external_id and course.external_id == external_id and not exact_name_conflict.external_id:
                    course.external_id = ''
                    course.source = Course.SOURCE_LOCAL
                    course.active = False
                    course.synced_at = now
                    course.save(update_fields=['external_id', 'source', 'active', 'synced_at', 'updated_at'])
                    resolved_name_conflict = True
                    course = exact_name_conflict
                else:
                    result.skipped += 1
                    result.errors.append(f'Curso "{name}" ignorado porque já existe com outro ID externo.')
                    continue

            values = {
                'name': name,
                'active': record.get('active', True),
                'source': Course.SOURCE_SPONTE,
                'external_id': external_id,
                'synced_at': now,
            }
            if course.value == Decimal('0.00') and record.get('value') is not None:
                values['value'] = record['value']

            changed = False
            for field_name, value in values.items():
                if getattr(course, field_name) != value:
                    setattr(course, field_name, value)
                    changed = True

            deactivated = _deactivate_conflicting_courses(course, {'name': name}, now)
            if changed:
                course.save(update_fields=[*values.keys(), 'updated_at'])
                result.updated += 1
            elif deactivated or resolved_name_conflict:
                result.updated += 1
            else:
                result.unchanged += 1
    return result


def import_sponte_courses(fetcher: Callable[[], str] | None = None):
    xml_text = (fetcher or fetch_sponte_courses_xml)()
    records = parse_sponte_courses(xml_text)
    return import_sponte_course_records(records)


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
            item_fields = _children_text_map(item)
            explicit_lesson_status = _lesson_status_label_from_sponte_fields(item_fields)
            lesson_status = explicit_lesson_status or _lesson_status_choice_label(Lesson.STATUS_NOT_GIVEN)
            records.append({
                'student_external_id': agenda_student_id,
                'free_class_id': free_class_id,
                'date': class_date,
                'start_time': start_time,
                'end_time': end_time,
                'lesson_status': lesson_status,
                'lesson_status_from_sponte': bool(explicit_lesson_status),
                'course_name': _child_text(item, 'NomeCurso') or _child_text(item, 'NomeDisciplina') or 'Curso Sponte',
                'room_name': _child_text(item, 'Sala'),
                'teacher_name': _child_text(item, 'NomeProfessor'),
                'course_external_id': _child_text(item, 'CursoID'),
                'discipline_external_id': _child_text(item, 'DisciplinaID'),
                'teacher_external_id': _child_text(item, 'ProfessorID'),
            })

    if not records and api_messages:
        unique_messages = sorted(set(api_messages))
        unexpected_messages = [
            message for message in unique_messages
            if not (_is_success_message(message) or _is_not_found_message(message))
        ]
        if unexpected_messages:
            raise SponteClientError('; '.join(unexpected_messages))
    return records


def _rest_status_label_from_value(value):
    if value in (None, ''):
        return ''
    parsed_int = _parse_int(value)
    if parsed_int is not None and parsed_int in REST_SITUATION_STATUS_LABELS:
        return REST_SITUATION_STATUS_LABELS[parsed_int]
    normalized = _normalize(value)
    if normalized in {'p', 'presenca', 'presente', 'dada', 'realizada', 'ministrada'}:
        return _lesson_status_choice_label(Lesson.STATUS_DONE)
    if normalized in {'f', 'falta', 'ausente'}:
        return _lesson_status_choice_label(Lesson.STATUS_ABSENT)
    if normalized in {'c', 'cancelada', 'cancelado'}:
        return _lesson_status_choice_label(Lesson.STATUS_CANCELLED)
    if normalized in {'n', 'nao dada', 'nao realizado', 'nao realizada', 'nao ministrada'}:
        return _lesson_status_choice_label(Lesson.STATUS_NOT_GIVEN)
    if 'cancel' in normalized:
        return _lesson_status_choice_label(Lesson.STATUS_CANCELLED)
    if 'falta' in normalized or 'ausente' in normalized:
        return _lesson_status_choice_label(Lesson.STATUS_ABSENT)
    if 'presenc' in normalized or 'dada' in normalized or 'realiz' in normalized or 'ministrad' in normalized:
        return _lesson_status_choice_label(Lesson.STATUS_DONE)
    if 'nao' in normalized:
        return _lesson_status_choice_label(Lesson.STATUS_NOT_GIVEN)
    return ''


def _rest_status_label_from_item(item):
    for key in (
        'situacaoDescricao',
        'situacaoAula',
        'situacaoTexto',
        'statusAula',
        'status',
        'presenca',
    ):
        label = _rest_status_label_from_value(item.get(key))
        if label:
            return label
    return _rest_status_label_from_value(item.get('situacao'))


def parse_sponte_free_class_rest_statuses(payload, *, student_external_id=''):
    if isinstance(payload, dict):
        items = payload.get('listDados') or payload.get('ListDados') or payload.get('dados') or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []

    records = []
    for item in items:
        if not isinstance(item, dict):
            continue
        free_class_id = str(item.get('aulaLivreID') or item.get('AulaLivreID') or '').strip()
        class_date = item.get('dataAula') or item.get('DataAula') or ''
        lesson_status = _rest_status_label_from_item(item)
        if not free_class_id or not lesson_status:
            continue
        records.append({
            'student_external_id': str(item.get('alunoID') or item.get('AlunoID') or student_external_id or '').strip(),
            'free_class_id': free_class_id,
            'date': class_date,
            'lesson_status': lesson_status,
            'lesson_status_raw': str(item.get('situacao') or item.get('presenca') or '').strip(),
            'lesson_status_from_sponte': True,
            'lesson_status_source': 'rest_aulaslivres',
        })
    return records


def fetch_sponte_free_class_status_records(student_external_id, start_date, end_date):
    api_url, client_code, login, password, timeout, token_ttl_minutes = _sponte_rest_config()
    token = _sponte_rest_login_token(api_url, login, password, timeout, token_ttl_minutes)
    page = 1
    records = []
    while True:
        params = {
            'CodCliSponte': client_code,
            'DataInicio': start_date.isoformat(),
            'DataTermino': end_date.isoformat(),
            'Pagina': page,
            'SituacaoAula': 0,
            'AlunoID': student_external_id,
            'TurmaAulaLivreID': 0,
        }
        query = urlencode(params)
        payload = _json_request(
            f'{api_url}/api/v1/aulaslivres?{query}',
            headers={'Authorization': f'Bearer {token}'},
            timeout=timeout,
            purpose='consultar Situação da Aula no Sponte REST',
        )
        records.extend(parse_sponte_free_class_rest_statuses(payload, student_external_id=student_external_id))
        total_pages = _parse_int(payload.get('totalPaginas') if isinstance(payload, dict) else None) or page
        if page >= total_pages:
            break
        page += 1
    return records


def parse_sponte_free_class_diary(xml_text, *, student_external_id=''):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SponteClientError(f'Resposta XML inválida do Sponte: {exc}') from exc

    records = []
    api_messages = []
    for diary in root.iter():
        if _local_name(diary.tag) != 'wsDiarioAulasLivres':
            continue
        operation_return = _child_text(diary, 'RetornoOperacao')
        if operation_return:
            api_messages.append(operation_return)
        diary_student_id = _child_text(diary, 'AlunoID') or student_external_id
        course_name = _child_text(diary, 'Curso')
        course_external_id = _child_text(diary, 'CursoID')
        discipline_name = _child_text(diary, 'Disciplina')
        discipline_external_id = _child_text(diary, 'DisciplinaID')
        for item in diary.iter():
            if _local_name(item.tag) != 'wsAulasLivreDiario':
                continue
            free_class_id = _child_text(item, 'AulaLivreID')
            class_date = _child_text(item, 'DataAula')
            start_time = _child_text(item, 'HorarioInicial')
            end_time = _child_text(item, 'HorarioFinal')
            if not any([free_class_id, class_date, start_time, end_time]):
                continue
            item_fields = _children_text_map(item)
            status_label = _lesson_status_label_from_sponte_fields(item_fields)
            records.append({
                'student_external_id': diary_student_id,
                'free_class_id': free_class_id,
                'date': class_date,
                'start_time': start_time,
                'end_time': end_time,
                'lesson_status': status_label or _lesson_status_choice_label(Lesson.STATUS_NOT_GIVEN),
                'lesson_status_raw': _child_text(item, 'Situacao'),
                'lesson_status_from_sponte': bool(status_label),
                'course_name': course_name or discipline_name or 'Curso Sponte',
                'room_name': _child_text(item, 'Sala'),
                'teacher_name': _child_text(item, 'Professor') or _child_text(item, 'NomeProfessor'),
                'course_external_id': course_external_id,
                'discipline_external_id': discipline_external_id,
                'discipline_name': discipline_name,
                'teacher_external_id': _child_text(item, 'ProfessorID'),
            })

    if not records and api_messages:
        unique_messages = sorted(set(api_messages))
        unexpected_messages = [
            message for message in unique_messages
            if not (_is_success_message(message) or _is_not_found_message(message))
        ]
        if unexpected_messages:
            raise SponteClientError('; '.join(unexpected_messages))
    return records


def parse_sponte_student_contracts(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SponteClientError(f'Resposta XML inválida do Sponte: {exc}') from exc

    contracts = []
    api_messages = []
    for item in root.iter():
        if _local_name(item.tag) != 'wsMatricula':
            continue
        operation_return = _child_text(item, 'RetornoOperacao')
        if operation_return:
            api_messages.append(operation_return)
        free_contract_id = _child_text(item, 'ContratoAulaLivreID')
        if not free_contract_id:
            continue
        contract = SponteStudentContract(
            contract_id=_child_text(item, 'ContratoID'),
            free_contract_id=free_contract_id,
            number=_child_text(item, 'NumeroContrato'),
            status=_child_text(item, 'Situacao'),
            course_external_id=_child_text(item, 'CursoID'),
            course_name=_child_text(item, 'NomeCurso'),
        )
        for discipline in item.iter():
            if _local_name(discipline.tag) != 'wsDisciplinas':
                continue
            contract.disciplines.append(SponteContractDiscipline(
                external_id=_child_text(discipline, 'DisciplinaID'),
                name=_child_text(discipline, 'Nome'),
                module=_parse_int(_child_text(discipline, 'Modulo')),
            ))
        contracts.append(contract)

    if not contracts and api_messages:
        unique_messages = sorted(set(api_messages))
        unexpected_messages = [
            message for message in unique_messages
            if not (_is_success_message(message) or _is_not_found_message(message))
        ]
        if unexpected_messages:
            raise SponteClientError('; '.join(unexpected_messages))
    return contracts


def _post_sponte_form(operation, data, error_context, *, use_cache=True):
    try:
        return SponteSOAPClient().call(operation, data, use_cache=use_cache).xml_text
    except SponteAPIDisabledError as exc:
        raise SponteConfigurationError(str(exc)) from exc
    except SponteAPIConfigurationError as exc:
        raise SponteConfigurationError(str(exc)) from exc
    except SponteAPITimeoutError as exc:
        raise SponteClientError(f'Tempo esgotado ao {error_context}.') from exc
    except SponteAPIError as exc:
        raise SponteClientError(f'{error_context}: {exc}') from exc


def _forward_schedule_window(start_date=None, end_date=None, *, allow_past=False):
    today = timezone.localdate()
    days_ahead = int(_sponte_setting('SPONTE_SCHEDULE_SYNC_DAYS_AHEAD', 90) or 90)
    requested_start = start_date or today
    effective_start = requested_start if allow_past else max(requested_start, today)
    effective_end = end_date or (today + timedelta(days=days_ahead))
    if effective_end < effective_start:
        effective_end = effective_start
    return effective_start, effective_end


def fetch_sponte_student_schedule_xml(student_external_id, start_date, end_date, *, allow_past=False):
    start_date, end_date = _forward_schedule_window(start_date, end_date, allow_past=allow_past)
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
        use_cache=False,
    )


def fetch_sponte_student_contracts_xml(student_external_id):
    return _post_sponte_form(
        'GetMatriculas',
        {'sParametrosBusca': f'AlunoID={student_external_id}'},
        'consultar contratos do Sponte',
        use_cache=False,
    )


def fetch_sponte_student_contracts(student_external_id):
    return parse_sponte_student_contracts(fetch_sponte_student_contracts_xml(student_external_id))


def _sponte_diary_candidate_modules(record, contracts=None):
    candidates = []
    course_id = (record.get('course_external_id') or '').strip()
    discipline_id = (record.get('discipline_external_id') or '').strip()
    for contract in contracts or []:
        if course_id and contract.course_external_id and contract.course_external_id != course_id:
            continue
        for discipline in contract.disciplines:
            if discipline_id and discipline.external_id and discipline.external_id != discipline_id:
                continue
            if discipline.module is not None:
                candidates.append(discipline.module)
    for key in ('module', 'modulo', 'Modulo', 'ModuloID', 'NumeroModulo'):
        parsed = _parse_int(record.get(key))
        if parsed is not None:
            candidates.append(parsed)
    candidates.extend([0, 1, 2, 3])
    seen = set()
    unique = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return unique


def fetch_sponte_student_diary_xml(student_external_id, record, module):
    class_date = _parse_sponte_date(record.get('date'))
    course_id = (record.get('course_external_id') or '').strip()
    discipline_id = (record.get('discipline_external_id') or '').strip()
    if not (class_date and course_id and discipline_id):
        return ''
    return _post_sponte_form(
        'GetDiarioAulasLivres',
        {
            'nAlunoID': student_external_id,
            'nCursoID': course_id,
            'nDisciplinaID': discipline_id,
            'dDataInicio': class_date.strftime('%d/%m/%Y'),
            'dDataTermino': class_date.strftime('%d/%m/%Y'),
            'nModulo': module,
            'sParametrosBusca': '',
        },
        'consultar diário de aulas livres do Sponte',
        use_cache=False,
    )


def _matching_sponte_diary_record(agenda_record, diary_records):
    if not diary_records:
        return None
    free_class_id = (agenda_record.get('free_class_id') or '').strip()
    if free_class_id:
        for record in diary_records:
            if (record.get('free_class_id') or '').strip() == free_class_id:
                return record

    agenda_date = _parse_sponte_date(agenda_record.get('date'))
    agenda_start = _parse_sponte_time(agenda_record.get('start_time'))
    agenda_end = _parse_sponte_time(agenda_record.get('end_time'))
    for record in diary_records:
        if (
            _parse_sponte_date(record.get('date')) == agenda_date
            and _parse_sponte_time(record.get('start_time')) == agenda_start
            and _parse_sponte_time(record.get('end_time')) == agenda_end
        ):
            return record
    return diary_records[0] if len(diary_records) == 1 else None


def _overlay_sponte_rest_statuses(records, rest_status_records):
    if not records or not rest_status_records:
        return records
    by_free_class_id = {
        (record.get('free_class_id') or '').strip(): record
        for record in rest_status_records
        if (record.get('free_class_id') or '').strip()
    }
    merged_records = []
    for record in records:
        free_class_id = (record.get('free_class_id') or '').strip()
        rest_record = by_free_class_id.get(free_class_id)
        if not rest_record:
            merged_records.append(record)
            continue
        merged = {**record}
        for field_name in (
            'lesson_status',
            'lesson_status_raw',
            'lesson_status_from_sponte',
            'lesson_status_source',
        ):
            if field_name in rest_record:
                merged[field_name] = rest_record[field_name]
        merged_records.append(merged)
    return merged_records


def _merge_sponte_diary_status(agenda_record, diary_record):
    if not diary_record:
        return agenda_record
    merged = {**agenda_record}
    for field_name, value in diary_record.items():
        if (
            agenda_record.get('lesson_status_source') == 'rest_aulaslivres'
            and field_name in {'lesson_status', 'lesson_status_raw', 'lesson_status_from_sponte'}
        ):
            continue
        if value or field_name in {'lesson_status_from_sponte'}:
            merged[field_name] = value
    return merged


def _overlay_sponte_diary_statuses(student_external_id, records, diary_fetcher, contracts=None):
    if not records:
        return records, []
    merged_records = []
    errors = []
    diary_cache = {}
    for record in records:
        class_date = _parse_sponte_date(record.get('date'))
        course_id = (record.get('course_external_id') or '').strip()
        discipline_id = (record.get('discipline_external_id') or '').strip()
        if not (class_date and course_id and discipline_id):
            merged_records.append(record)
            continue

        diary_records = []
        record_errors = []
        for module in _sponte_diary_candidate_modules(record, contracts=contracts):
            cache_key = (class_date, course_id, discipline_id, module)
            if cache_key not in diary_cache:
                try:
                    xml_text = diary_fetcher(student_external_id, record, module)
                    diary_cache[cache_key] = (
                        parse_sponte_free_class_diary(xml_text, student_external_id=student_external_id)
                        if xml_text else []
                    )
                except (SponteClientError, SponteAPIError) as exc:
                    diary_cache[cache_key] = []
                    if not _is_invalid_search_parameter_message(exc):
                        record_errors.append(f'Diário Sponte {class_date:%d/%m/%Y}: {exc}')
            if diary_cache[cache_key]:
                diary_records = diary_cache[cache_key]
                break

        if not diary_records and record_errors:
            errors.extend(record_errors[:1])

        merged_records.append(_merge_sponte_diary_status(
            record,
            _matching_sponte_diary_record(record, diary_records),
        ))
    return merged_records, errors


def _course_for_schedule(record):
    name = _truncate(record.get('course_name') or 'Curso Sponte', 160)
    external_id = _truncate(record.get('course_external_id'), 120)
    lookup_record = {'name': name, 'external_id': external_id}
    course = _course_lookup(lookup_record)
    if course is None:
        course = Course.objects.create(
            name=name,
            description='Criado automaticamente pela sincronização de agenda do Sponte.',
            value=Decimal('0.00'),
            kit_quantity=1,
            max_students_per_slot=1,
            active=True,
            source=Course.SOURCE_SPONTE,
            external_id=external_id,
            synced_at=timezone.now(),
        )
        return course

    values = {
        'source': Course.SOURCE_SPONTE,
        'external_id': external_id,
        'synced_at': timezone.now(),
    }
    if name and _course_has_version_two(name) and not _course_has_version_two(course.name):
        values['name'] = name
    changed = False
    for field_name, value in values.items():
        if getattr(course, field_name) != value:
            setattr(course, field_name, value)
            changed = True
    if changed:
        course.save(update_fields=[*values.keys(), 'updated_at'])
    return course


def _lesson_feedback(lesson):
    try:
        return lesson.feedback
    except Exception:
        return None


def _move_feedback_if_possible(source_lesson, target_lesson):
    if source_lesson.pk == target_lesson.pk:
        return
    source_feedback = _lesson_feedback(source_lesson)
    if source_feedback is None or _lesson_feedback(target_lesson) is not None:
        return
    source_feedback.lesson = target_lesson
    source_feedback.save(update_fields=['lesson', 'updated_at'])


def _delete_sponte_lessons_or_cancel(queryset, *, target_lesson=None, now=None):
    deleted = 0
    cancelled = 0
    now = now or timezone.now()
    for lesson in list(queryset):
        if target_lesson is not None:
            _move_feedback_if_possible(lesson, target_lesson)
        try:
            lesson.delete()
            deleted += 1
        except ProtectedError:
            if lesson.status != Lesson.STATUS_CANCELLED or lesson.synced_at != now:
                lesson.status = Lesson.STATUS_CANCELLED
                lesson.synced_at = now
                lesson.save(update_fields=['status', 'synced_at', 'updated_at'])
            cancelled += 1
    return deleted, cancelled


def _room_for_schedule(record):
    name = _truncate(record.get('room_name'), 120)
    if not name:
        name = 'Sponte - Sala não informada'
    room, _ = Room.objects.get_or_create(
        name=name,
        defaults={'capacity': 999 if name == 'Sponte - Sala não informada' else 1, 'active': True},
    )
    return room


def _sponte_record_natural_key(record):
    return (
        _parse_sponte_date(record.get('date')),
        _parse_sponte_time(record.get('start_time')),
        _parse_sponte_time(record.get('end_time')),
        (record.get('course_external_id') or record.get('course_name') or '').strip(),
        (record.get('discipline_external_id') or record.get('discipline_name') or '').strip(),
        (record.get('room_name') or '').strip(),
    )


def _sponte_record_choice_score(record):
    status = _lesson_status_from_sponte(record.get('lesson_status'))
    free_class_id = _parse_int(record.get('free_class_id')) or 0
    status_priority = {
        Lesson.STATUS_CANCELLED: 4,
        Lesson.STATUS_ABSENT: 3,
        Lesson.STATUS_DONE: 2,
        Lesson.STATUS_NOT_GIVEN: 1,
    }.get(status, 0)
    return (
        int(bool(record.get('lesson_status_from_sponte'))),
        status_priority,
        free_class_id,
    )


def _dedupe_sponte_schedule_records(records):
    selected = {}
    for record in records:
        key = _sponte_record_natural_key(record)
        current = selected.get(key)
        if current is None or _sponte_record_choice_score(record) >= _sponte_record_choice_score(current):
            selected[key] = record
    return list(selected.values()), max(len(records) - len(selected), 0)


def import_sponte_free_class_records(student, records, *, start_date, end_date, allow_past=False):
    start_date, end_date = _forward_schedule_window(start_date, end_date, allow_past=allow_past)
    records, duplicated_records = _dedupe_sponte_schedule_records(records)
    result = SponteScheduleSyncResult(students_synced=1)
    result.skipped += duplicated_records
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
            if class_date < start_date or class_date > end_date:
                result.skipped += 1
                continue
            external_id = f'aula_livre:{student.external_id}:{free_class_id}:{class_date.isoformat()}'
            seen_external_ids.add(external_id)
            course = _course_for_schedule(record)
            room = _room_for_schedule(record)
            status_note = (
                f'Situação no Sponte: {record.get("lesson_status") or "-"}'
                if record.get('lesson_status_from_sponte')
                else 'Situação no Sponte: não informada pela API; padrão/preservação Checklist.'
            )
            notes_parts = [
                'Aula Livre sincronizada do Sponte.',
                f'Professor: {record.get("teacher_name") or "-"}',
                status_note,
                f'CursoID: {record.get("course_external_id") or "-"}',
                f'DisciplinaID: {record.get("discipline_external_id") or "-"}',
            ]
            incoming_status = _lesson_status_from_sponte(record.get('lesson_status'))
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
                'notes': '\n'.join(notes_parts),
                'source': Lesson.SOURCE_SPONTE,
                'external_id': external_id,
                'synced_at': now,
            }
            lesson = Lesson.objects.filter(source=Lesson.SOURCE_SPONTE, external_id=external_id).first()
            if lesson is None:
                lesson = (
                    Lesson.objects
                    .filter(
                        source=Lesson.SOURCE_SPONTE,
                        student=student,
                        date=class_date,
                        start_time=start_time,
                        end_time=end_time,
                        course=course,
                        room=room,
                    )
                    .order_by('-synced_at', '-id')
                    .first()
                )
                if lesson is None:
                    values['status'] = incoming_status
                    lesson = Lesson.objects.create(**values)
                    result.created += 1
                    stale_duplicates = Lesson.objects.none()
                    continue
                values['status'] = incoming_status
                stale_duplicates = (
                    Lesson.objects
                    .filter(
                        source=Lesson.SOURCE_SPONTE,
                        student=student,
                        date=class_date,
                        start_time=start_time,
                        end_time=end_time,
                        course=course,
                        room=room,
                    )
                    .exclude(pk=lesson.pk)
                )
            else:
                stale_duplicates = (
                    Lesson.objects
                    .filter(
                        source=Lesson.SOURCE_SPONTE,
                        student=student,
                        date=class_date,
                        start_time=start_time,
                        end_time=end_time,
                        course=course,
                        room=room,
                    )
                    .exclude(pk=lesson.pk)
                )
            if record.get('lesson_status_from_sponte'):
                values['status'] = incoming_status

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

            deleted, cancelled = _delete_sponte_lessons_or_cancel(
                stale_duplicates,
                target_lesson=lesson,
                now=now,
            )
            result.deleted += deleted
            result.cancelled += cancelled

        stale_lessons = Lesson.objects.filter(
            source=Lesson.SOURCE_SPONTE,
            student=student,
            date__gte=start_date,
            date__lte=end_date,
        ).exclude(external_id__in=seen_external_ids)
        deleted, cancelled = _delete_sponte_lessons_or_cancel(stale_lessons, now=now)
        result.deleted += deleted
        result.cancelled += cancelled
    return result


def sync_sponte_free_class_schedule(
    start_date,
    end_date,
    fetcher=None,
    diary_fetcher=None,
    contracts_fetcher=None,
    status_fetcher=None,
    *,
    allow_past=False,
    include_inactive_students=False,
    require_rest_status=False,
):
    start_date, end_date = _forward_schedule_window(start_date, end_date, allow_past=allow_past)
    require_rest_status = require_rest_status or _sponte_rest_required_for_schedule_status()
    students_qs = PedagogicalStudent.objects.filter(
        source=SPONTE_SOURCE,
        external_id__gt='',
    )
    if not include_inactive_students:
        students_qs = students_qs.filter(status=PedagogicalStudent.STATUS_ACTIVE)
    students = list(students_qs.order_by('name'))
    result = SponteScheduleSyncResult()
    attempted_student_ids = {student.pk for student in students}
    for student in students:
        try:
            if fetcher is None:
                xml_text = fetch_sponte_student_schedule_xml(
                    student.external_id,
                    start_date,
                    end_date,
                    allow_past=allow_past,
                )
            else:
                xml_text = fetcher(student.external_id, start_date, end_date)
            records = parse_sponte_free_class_schedule(xml_text, student_external_id=student.external_id)
            if records:
                effective_status_fetcher = status_fetcher
                if effective_status_fetcher is None and _sponte_rest_api_enabled():
                    effective_status_fetcher = fetch_sponte_free_class_status_records
                if effective_status_fetcher is not None:
                    try:
                        status_records = effective_status_fetcher(student.external_id, start_date, end_date)
                    except (SponteClientError, SponteAPIError) as exc:
                        if require_rest_status:
                            raise SponteClientError(f'Situação da Aula via Sponte REST: {exc}') from exc
                        result.errors.append(f'{student.name}: Situação da Aula via Sponte REST indisponível: {exc}')
                    else:
                        records = _overlay_sponte_rest_statuses(records, status_records)
                        if require_rest_status:
                            missing_status_ids = [
                                record.get('free_class_id') or '?'
                                for record in records
                                if record.get('lesson_status_source') != 'rest_aulaslivres'
                            ]
                            if missing_status_ids:
                                sample = ', '.join(missing_status_ids[:5])
                                raise SponteClientError(
                                    'Sponte REST não devolveu Situação da Aula para '
                                    f'{len(missing_status_ids)} aula(s) da agenda. AulaLivreID: {sample}.'
                                )
                elif require_rest_status:
                    raise SponteClientError(
                        'SPONTE_REST_API_ENABLED precisa estar True para usar a Situação da Aula oficial do Sponte.'
                    )
            if records and (diary_fetcher is not None or fetcher is None):
                contracts = []
                if contracts_fetcher is not None or fetcher is None:
                    try:
                        contracts = (contracts_fetcher or fetch_sponte_student_contracts)(student.external_id)
                    except (SponteClientError, SponteAPIError) as exc:
                        result.errors.append(f'{student.name}: contratos Sponte: {exc}')
                records, diary_errors = _overlay_sponte_diary_statuses(
                    student.external_id,
                    records,
                    diary_fetcher or fetch_sponte_student_diary_xml,
                    contracts=contracts,
                )
                result.errors.extend(f'{student.name}: {error}' for error in diary_errors[:5])
            student_result = import_sponte_free_class_records(
                student,
                records,
                start_date=start_date,
                end_date=end_date,
                allow_past=allow_past,
            )
        except SponteClientError as exc:
            result.errors.append(f'{student.name}: {exc}')
            continue
        result.created += student_result.created
        result.updated += student_result.updated
        result.unchanged += student_result.unchanged
        result.cancelled += student_result.cancelled
        result.deleted += student_result.deleted
        result.skipped += student_result.skipped
        result.students_synced += student_result.students_synced
        result.errors.extend(student_result.errors)
    now = timezone.now()
    orphan_stale_lessons = Lesson.objects.filter(
        source=Lesson.SOURCE_SPONTE,
        date__gte=start_date,
        date__lte=end_date,
    ).exclude(student_id__in=attempted_student_ids)
    deleted, cancelled = _delete_sponte_lessons_or_cancel(orphan_stale_lessons, now=now)
    result.deleted += deleted
    result.cancelled += cancelled
    return result


def default_sponte_schedule_window(target_date=None):
    return _forward_schedule_window()
