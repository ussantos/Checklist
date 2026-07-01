import hashlib
import json
import logging
import os
import time
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from django.conf import settings
from django.core.cache import cache as default_cache


DEFAULT_SPONTE_API_BASE_URL = 'https://api.sponteeducacional.net.br/WSAPIEdu.asmx'
LOGGER = logging.getLogger('checklists.sponte')

SENSITIVE_FIELD_MARKERS = {
    'cpf',
    'rg',
    'documento',
    'senha',
    'password',
    'login',
    'usuario',
    'user',
    'token',
    'chave',
    'key',
}


class SponteAPIError(Exception):
    """Base exception for safe Sponte API failures."""


class SponteAPIConfigurationError(SponteAPIError):
    pass


class SponteAPIDisabledError(SponteAPIConfigurationError):
    pass


class SponteAPIRateLimitError(SponteAPIError):
    pass


class SponteAPITimeoutError(SponteAPIError):
    pass


@dataclass(frozen=True)
class SponteSOAPResponse:
    operation: str
    xml_text: str
    from_cache: bool = False
    stale_cache: bool = False
    duration_seconds: float = 0
    record_count: int = 0
    return_code: str = ''


@dataclass(frozen=True)
class StudentSnapshot:
    external_id: str = ''
    enrollment_number: str = ''
    name: str = ''
    birth_date: str = ''
    phone: str = ''
    email: str = ''
    status: str = ''
    current_class: str = ''
    responsible_financial_id: str = ''
    responsible_pedagogical_id: str = ''
    discarded_sensitive_fields: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ResponsibleSnapshot:
    external_id: str = ''
    name: str = ''
    phone: str = ''
    email: str = ''
    discarded_sensitive_fields: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CourseSnapshot:
    external_id: str = ''
    name: str = ''
    abbreviation: str = ''
    status: str = ''
    modules: str = ''
    discarded_sensitive_fields: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RoomSnapshot:
    external_id: str = ''
    name: str = ''
    capacity: str = ''
    active: str = ''
    discarded_sensitive_fields: tuple[str, ...] = field(default_factory=tuple)


def _normalize(value):
    value = unicodedata.normalize('NFKD', str(value or ''))
    value = ''.join(char for char in value if not unicodedata.combining(char))
    return value.casefold()


def _setting(name, default=''):
    return getattr(settings, name, os.environ.get(name, default))


def _as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on', 'sim'}


def _as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def is_sponte_api_enabled():
    return _as_bool(_setting('SPONTE_API_ENABLED', False), False)


def _local_name(tag):
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


def _children_text_map(element):
    fields = {}
    discarded = []
    for child in list(element):
        key = _local_name(child.tag)
        if _is_sensitive_field(key):
            discarded.append(key)
            continue
        fields[key] = (child.text or '').strip()
    return fields, tuple(sorted(discarded))


def _is_sensitive_field(field_name):
    normalized = _normalize(field_name)
    return any(marker in normalized for marker in SENSITIVE_FIELD_MARKERS)


def _first(fields, *names):
    for name in names:
        value = fields.get(name, '').strip()
        if value:
            return value
    return ''


def _iter_xml_items(xml_text, tag_name):
    root = ET.fromstring(xml_text)
    for item in root.iter():
        if _local_name(item.tag) == tag_name:
            yield item


def _iter_xml_items_any(xml_text, tag_names):
    wanted = set(tag_names)
    root = ET.fromstring(xml_text)
    for item in root.iter():
        if _local_name(item.tag) in wanted:
            yield item


def _xml_metadata(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return 0, ''

    record_count = 0
    return_code = ''
    for item in root.iter():
        local_name = _local_name(item.tag)
        if local_name.startswith('ws') and item is not root:
            record_count += 1
        if local_name == 'RetornoOperacao' and item.text and not return_code:
            return_code = item.text.strip().split('-', 1)[0].strip()
    return record_count, return_code


def normalize_students(xml_text):
    snapshots = []
    for item in _iter_xml_items(xml_text, 'wsAluno'):
        fields, discarded = _children_text_map(item)
        snapshots.append(StudentSnapshot(
            external_id=_first(fields, 'AlunoID', 'IDAluno', 'CodigoAluno'),
            enrollment_number=_first(fields, 'NumeroMatricula', 'RA', 'Matricula'),
            name=_first(fields, 'Nome', 'NomeAluno'),
            birth_date=_first(fields, 'DataNascimento', 'Nascimento'),
            phone=_first(fields, 'Celular', 'Telefone'),
            email=_first(fields, 'Email', 'E-mail'),
            status=_first(fields, 'Situacao', 'Status'),
            current_class=_first(fields, 'TurmaAtual', 'NomeTurma', 'Turma'),
            responsible_financial_id=_first(fields, 'ResponsavelFinanceiroID'),
            responsible_pedagogical_id=_first(fields, 'ResponsavelDidaticoID', 'ResponsavelPedagogicoID'),
            discarded_sensitive_fields=discarded,
        ))
    return snapshots


def normalize_responsibles(xml_text):
    snapshots = []
    for item in _iter_xml_items(xml_text, 'wsResponsaveis'):
        fields, discarded = _children_text_map(item)
        snapshots.append(ResponsibleSnapshot(
            external_id=_first(fields, 'ResponsavelID', 'IDResponsavel', 'CodigoResponsavel'),
            name=_first(fields, 'Nome', 'NomeResponsavel'),
            phone=_first(fields, 'Celular', 'Telefone'),
            email=_first(fields, 'Email', 'E-mail'),
            discarded_sensitive_fields=discarded,
        ))
    return snapshots


def normalize_courses(xml_text):
    snapshots = []
    for item in _iter_xml_items(xml_text, 'wsCurso'):
        fields, discarded = _children_text_map(item)
        snapshots.append(CourseSnapshot(
            external_id=_first(fields, 'CursoID', 'IDCurso', 'CodigoCurso', 'Codigo'),
            name=_first(fields, 'NomeCurso', 'Curso', 'Nome', 'DescricaoCurso', 'Descricao'),
            abbreviation=_first(fields, 'Sigla', 'Abreviacao'),
            status=_first(fields, 'Situacao', 'Status', 'StatusCurso'),
            modules=_first(fields, 'NumeroModulos', 'Modulos', 'QtdModulos'),
            discarded_sensitive_fields=discarded,
        ))
    return snapshots


def normalize_rooms(xml_text):
    snapshots = []
    for item in _iter_xml_items_any(xml_text, ('wsSala', 'wsSalas')):
        fields, discarded = _children_text_map(item)
        snapshots.append(RoomSnapshot(
            external_id=_first(fields, 'SalaID', 'IDSala', 'CodigoSala', 'Codigo'),
            name=_first(fields, 'Descricao', 'Sigla', 'Nome', 'Sala'),
            capacity=_first(fields, 'Vagas', 'Capacidade'),
            active=_first(fields, 'Situacao', 'Status', 'Ativo'),
            discarded_sensitive_fields=discarded,
        ))
    return snapshots


class SponteSOAPClient:
    """Safe read-only SOAP client with local cache and defensive rate limit."""

    def __init__(self, *, cache_backend=None, fetcher=None, clock=None):
        self.cache = cache_backend or default_cache
        self.fetcher = fetcher
        self.clock = clock or time.time

    @property
    def base_url(self):
        return str(_setting('SPONTE_API_BASE_URL', '') or _setting('SPONTE_API_URL', DEFAULT_SPONTE_API_BASE_URL) or DEFAULT_SPONTE_API_BASE_URL).rstrip('/')

    @property
    def client_code(self):
        return str(_setting('SPONTE_API_CLIENT_CODE', '') or _setting('SPONTE_CODIGO_CLIENTE', '') or '').strip()

    @property
    def token(self):
        return str(_setting('SPONTE_API_TOKEN', '') or _setting('SPONTE_TOKEN', '') or '').strip()

    @property
    def timeout_seconds(self):
        return _as_int(_setting('SPONTE_API_TIMEOUT_SECONDS', '') or _setting('SPONTE_TIMEOUT_SECONDS', 30), 30)

    @property
    def cache_ttl_seconds(self):
        return max(_as_int(_setting('SPONTE_API_CACHE_TTL_MINUTES', 60), 60), 0) * 60

    @property
    def max_requests_per_minute(self):
        return max(_as_int(_setting('SPONTE_API_MAX_REQUESTS_PER_MINUTE', 30), 30), 0)

    @property
    def wait_on_rate_limit(self):
        return _as_bool(_setting('SPONTE_API_WAIT_ON_RATE_LIMIT', True), True)

    @property
    def rate_limit_wait_padding_seconds(self):
        return max(_as_int(_setting('SPONTE_API_RATE_LIMIT_WAIT_PADDING_SECONDS', 2), 2), 0)

    def call(self, operation, data=None, *, use_cache=True):
        data = data or {}
        if not is_sponte_api_enabled():
            raise SponteAPIDisabledError('Integração Sponte desabilitada por SPONTE_API_ENABLED.')
        if not self.client_code or not self.token:
            raise SponteAPIConfigurationError('Configure SPONTE_API_CLIENT_CODE e SPONTE_API_TOKEN no .env.')

        cache_key = self._cache_key(operation, data)
        stale_cache_key = f'{cache_key}:last_valid'
        started_at = self.clock()

        if use_cache:
            cached_xml = self.cache.get(cache_key)
            if cached_xml is not None:
                response = self._response(operation, cached_xml, True, False, started_at)
                self._safe_log(operation, 'cache_hit', response)
                return response

        try:
            self._check_rate_limit(operation, data)
        except SponteAPIRateLimitError:
            stale_xml = self.cache.get(stale_cache_key)
            if stale_xml is not None:
                response = self._response(operation, stale_xml, True, True, started_at)
                self._safe_log(operation, 'rate_limit_cache_hit', response)
                return response
            self._safe_log(operation, 'rate_limit', self._response(operation, '', False, False, started_at))
            raise

        try:
            xml_text = self._post(operation, data)
        except TimeoutError as exc:
            return self._handle_failure(operation, stale_cache_key, started_at, 'timeout', SponteAPITimeoutError('Tempo esgotado ao conectar ao Sponte.'), exc)
        except HTTPError as exc:
            return self._handle_failure(operation, stale_cache_key, started_at, 'http_error', SponteAPIError(f'Sponte retornou HTTP {exc.code}.'), exc)
        except URLError as exc:
            return self._handle_failure(operation, stale_cache_key, started_at, 'network_error', SponteAPIError(f'Não foi possível conectar ao Sponte: {exc.reason}'), exc)

        if self.cache_ttl_seconds > 0:
            self.cache.set(cache_key, xml_text, self.cache_ttl_seconds)
        self.cache.set(stale_cache_key, xml_text, None)
        response = self._response(operation, xml_text, False, False, started_at)
        self._safe_log(operation, 'success', response)
        return response

    def get_students(self, search_params='Nome=%'):
        return self.call('GetAlunos', {'sParametrosBusca': search_params})

    def get_responsibles(self, search_params='Nome=%'):
        return self.call('GetResponsaveis', {'sParametrosBusca': search_params})

    def get_courses(self, search_params='Situacao=1'):
        return self.call('GetCursos', {'sParametrosBusca': search_params})

    def get_rooms(self, search_params='', *, room_id='', abbreviation='', description='', active=''):
        return self.call('GetSalas', {
            'nSalaID': room_id,
            'sSigla': abbreviation,
            'sDescricao': description,
            'nAtivo': active,
            'sParametrosBusca': search_params,
        })

    def get_class_schedules(self, student_id, start_date, end_date, class_id='', course_id=''):
        return self.call('GetAgendaAluno', {
            'nAlunoID': student_id,
            'sTurmaID': class_id,
            'sCursoID': course_id,
            'dDataInicio': start_date.strftime('%d/%m/%Y'),
            'dDataTermino': end_date.strftime('%d/%m/%Y'),
        })

    def get_enrollments(self, search_params=''):
        return self.call('GetMatriculas', {'sParametrosBusca': search_params})

    def get_financial(self, search_params=''):
        return self.call('GetContasReceber', {'sParametrosBusca': search_params})

    def _cache_key(self, operation, data):
        raw = json.dumps({'operation': operation, 'data': data}, sort_keys=True, default=str)
        digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        return f'sponte:soap:{digest}'

    def _check_rate_limit(self, operation, data):
        limit = self.max_requests_per_minute
        if limit <= 0:
            return
        while True:
            now = self.clock()
            bucket = int(now // 60)
            cache_key = f'sponte:rate:{bucket}'
            self.cache.add(cache_key, 0, timeout=65)
            try:
                current = self.cache.incr(cache_key)
            except ValueError:
                self.cache.set(cache_key, 1, timeout=65)
                current = 1
            if current <= limit:
                return
            if not self.wait_on_rate_limit:
                raise SponteAPIRateLimitError(
                    f'Limite local de {limit} chamada(s) por minuto para a API Sponte atingido.'
                )

            wait_seconds = max(((bucket + 1) * 60) - now, 1) + self.rate_limit_wait_padding_seconds
            LOGGER.info(
                'sponte_api method=%s status=rate_limit_wait wait_seconds=%d limit=%d',
                operation,
                int(wait_seconds),
                limit,
            )
            time.sleep(wait_seconds)

    def _post(self, operation, data):
        payload = urlencode({
            'nCodigoCliente': self.client_code,
            'sToken': self.token,
            **data,
        }).encode('utf-8')
        request = Request(
            f'{self.base_url}/{operation}',
            data=payload,
            headers={'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8'},
            method='POST',
        )
        if self.fetcher:
            raw = self.fetcher(request, self.timeout_seconds)
        else:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        if isinstance(raw, bytes):
            return raw.decode('utf-8')
        return str(raw)

    def _handle_failure(self, operation, stale_cache_key, started_at, status, public_error, original_exc):
        stale_xml = self.cache.get(stale_cache_key)
        if stale_xml is not None:
            response = self._response(operation, stale_xml, True, True, started_at)
            self._safe_log(operation, f'{status}_cache_hit', response)
            return response
        response = self._response(operation, '', False, False, started_at)
        self._safe_log(operation, status, response)
        raise public_error from original_exc

    def _response(self, operation, xml_text, from_cache, stale_cache, started_at):
        record_count, return_code = _xml_metadata(xml_text) if xml_text else (0, '')
        return SponteSOAPResponse(
            operation=operation,
            xml_text=xml_text,
            from_cache=from_cache,
            stale_cache=stale_cache,
            duration_seconds=max(self.clock() - started_at, 0),
            record_count=record_count,
            return_code=return_code,
        )

    def _safe_log(self, operation, status, response):
        LOGGER.info(
            'sponte_api method=%s status=%s duration_ms=%d records=%d return_code=%s from_cache=%s stale_cache=%s',
            operation,
            status,
            int((response.duration_seconds or 0) * 1000),
            response.record_count,
            response.return_code or '-',
            response.from_cache,
            response.stale_cache,
        )
