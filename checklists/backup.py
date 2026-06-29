import os
import shutil
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.utils import timezone
from psycopg import connect, sql

from .models import BackupConfiguration


CONFIG_PATHS = [
    '.env',
    'docker-compose.yml',
    'Dockerfile',
    'requirements.txt',
    'seed',
    'scripts',
    'myrobot_checklist',
    'checklists',
    'templates',
    'static',
    'grafana',
]

ENV_BACKUP_KEYS = [
    'DJANGO_SECRET_KEY',
    'DJANGO_DEBUG',
    'DJANGO_ALLOWED_HOSTS',
    'CSRF_TRUSTED_ORIGINS',
    'APP_BIND',
    'POSTGRES_DB',
    'POSTGRES_USER',
    'POSTGRES_PASSWORD',
    'POSTGRES_HOST',
    'POSTGRES_PORT',
    'GRAFANA_BIND',
    'GRAFANA_ADMIN_USER',
    'GRAFANA_ADMIN_PASSWORD',
    'INITIAL_CHECKLISTADMIN_PASSWORD',
    'FORCE_PASSWORD_CHANGE_ON_FIRST_LOGIN',
    'AUTO_SEED_OPERATIONAL_DATA',
    'MAX_EVIDENCE_FILE_SIZE_MB',
    'SPONTE_API_ENABLED',
    'SPONTE_API_BASE_URL',
    'SPONTE_API_CLIENT_CODE',
    'SPONTE_API_TOKEN',
    'SPONTE_API_TIMEOUT_SECONDS',
    'SPONTE_API_CACHE_TTL_MINUTES',
    'SPONTE_API_MAX_REQUESTS_PER_MINUTE',
    'SPONTE_STUDENT_SEARCH_PARAMS',
    'SPONTE_COURSE_SEARCH_PARAMS',
    'SPONTE_SCHEDULE_SYNC_DAYS_BACK',
    'SPONTE_SCHEDULE_SYNC_DAYS_AHEAD',
    'RCLONE_REMOTE',
    'BACKUP_RETENTION_DAYS',
    'BACKUP_SCHEDULER_INTERVAL_SECONDS',
]


@dataclass
class BackupRunResult:
    local_path: Path
    package_path: Path | None = None
    cloud_status: str = 'disabled'
    cloud_message: str = ''
    warnings: list[str] = field(default_factory=list)


@dataclass
class BackupRestoreResult:
    backup_name: str
    restored_path: Path
    safety_backup_path: Path | None = None
    restored_media: bool = False


@dataclass
class BackupImportResult:
    backup_name: str
    local_path: Path
    has_media: bool = False


def infer_provider(remote_path):
    remote = (remote_path or '').strip().lower()
    if remote.startswith('onedrive:'):
        return BackupConfiguration.PROVIDER_ONEDRIVE
    if remote.startswith(('gdrive:', 'google:', 'drive:')):
        return BackupConfiguration.PROVIDER_GOOGLE_DRIVE
    return BackupConfiguration.PROVIDER_NONE


def split_remote_path(remote_path):
    remote_path = (remote_path or '').strip()
    if ':' not in remote_path:
        return remote_path.rstrip(':'), ''
    remote_name, folder = remote_path.split(':', 1)
    return remote_name.strip().rstrip(':'), folder.strip().strip('/')


def build_remote_path(remote_name, remote_folder):
    remote_name = (remote_name or '').strip().rstrip(':')
    remote_folder = (remote_folder or '').strip().strip('/')
    if not remote_name:
        return ''
    if not remote_folder:
        return f'{remote_name}:'
    return f'{remote_name}:{remote_folder}'


def get_backup_configuration():
    config, created = BackupConfiguration.objects.get_or_create(pk=1)
    if created:
        env_remote = os.environ.get('RCLONE_REMOTE', '').strip()
        if env_remote:
            config.remote_path = env_remote
            config.cloud_provider = infer_provider(env_remote)
        retention = os.environ.get('BACKUP_RETENTION_DAYS', '').strip()
        if retention.isdigit():
            config.retention_days = int(retention)
        config.save()
    return config


def list_rclone_remotes():
    if shutil.which('rclone') is None:
        return []
    try:
        completed = _run_command(['rclone', 'listremotes'], timeout=30)
    except RuntimeError:
        return []
    remotes = []
    for line in completed.stdout.splitlines():
        remote = line.strip().rstrip(':')
        if remote:
            remotes.append(remote)
    return sorted(set(remotes))


def backup_runtime_status():
    return {
        'pg_dump_available': shutil.which('pg_dump') is not None,
        'rclone_available': shutil.which('rclone') is not None,
        'rclone_remotes': list_rclone_remotes(),
        'env_remote': os.environ.get('RCLONE_REMOTE', '').strip(),
        'env_retention_days': os.environ.get('BACKUP_RETENTION_DAYS', '').strip(),
        'base_dir': str(settings.BASE_DIR),
        'backups_dir': str(settings.BASE_DIR / 'backups'),
    }


def _run_command(args, *, env=None, timeout=600):
    completed = subprocess.run(
        args,
        cwd=settings.BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f'Comando falhou: {args[0]}'
        raise RuntimeError(message[:1000])
    return completed


def _add_to_tar(tar, source):
    source_path = settings.BASE_DIR / source
    if source_path.exists():
        tar.add(source_path, arcname=source)


def _add_text_to_tar(tar, arcname, content):
    encoded = content.encode('utf-8')
    info = tarfile.TarInfo(arcname)
    info.size = len(encoded)
    info.mtime = int(timezone.now().timestamp())
    tar.addfile(info, BytesIO(encoded))


def _env_file_value(value):
    value = str(value).replace('\r', '').replace('\n', '\\n')
    if value == '' or any(char.isspace() or char in {'"', "'", '#', '=', '$', '`', '\\'} for char in value):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return value


def _add_runtime_env_to_tar(tar):
    lines = [
        '# Gerado automaticamente pelo backup do Checklist.',
        '# Este arquivo pode conter segredos. Guarde o backup em local seguro.',
    ]
    for key in ENV_BACKUP_KEYS:
        if key in os.environ:
            lines.append(f'{key}={_env_file_value(os.environ.get(key, ""))}')
    _add_text_to_tar(tar, '.env.generated', '\n'.join(lines) + '\n')


def _add_rclone_config_to_tar(tar):
    config_file = os.environ.get('RCLONE_CONFIG', '').strip()
    if config_file:
        path = Path(config_file)
        if path.is_file():
            tar.add(path, arcname='rclone/rclone.conf')
            return

    config_dir = Path.home() / '.config' / 'rclone'
    if config_dir.exists():
        tar.add(config_dir, arcname='rclone')


def _folder_size(path):
    total = 0
    for item in path.rglob('*'):
        if item.is_file():
            total += item.stat().st_size
    return total


def _format_size(size):
    units = ['B', 'KB', 'MB', 'GB']
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f'{value:.1f} {unit}' if unit != 'B' else f'{int(value)} B'
        value /= 1024
    return f'{size} B'


def _safe_backup_name(name):
    name = (name or '').strip().strip('/').strip('\\')
    allowed = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-')
    if not name or any(char not in allowed for char in name):
        raise RuntimeError('Nome de backup inválido.')
    return name


def _parse_backup_stamp(name):
    try:
        return datetime.strptime(name, '%Y%m%d_%H%M%S')
    except ValueError:
        return None


def backup_path_for_name(name):
    backup_name = _safe_backup_name(name)
    backups_dir = (settings.BASE_DIR / 'backups').resolve()
    target = (backups_dir / backup_name).resolve()
    if backups_dir not in target.parents:
        raise RuntimeError('Caminho de backup inválido.')
    return target


def list_local_backups(limit=20):
    backups_dir = settings.BASE_DIR / 'backups'
    if not backups_dir.exists():
        return []
    rows = []
    for path in backups_dir.iterdir():
        if not path.is_dir():
            continue
        stat = path.stat()
        created_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone())
        size = _folder_size(path)
        rows.append({
            'name': path.name,
            'path': str(path),
            'created_at': created_at,
            'size': _format_size(size),
            'has_db': (path / 'db.dump').exists(),
            'has_media': (path / 'media.tar.gz').exists(),
            'has_config': (path / 'app_config.tar.gz').exists(),
            'has_manifest': (path / 'manifest.txt').exists(),
            'has_package': (path / 'backup_package.tar.gz').exists(),
        })
    return sorted(rows, key=lambda row: row['created_at'], reverse=True)[:limit]


def local_backup_package_path(backup_name):
    backup_path = backup_path_for_name(backup_name)
    package_path = backup_path / 'backup_package.tar.gz'
    if not package_path.exists():
        raise RuntimeError('backup_package.tar.gz nao encontrado neste backup.')
    return package_path


def list_remote_backups(config=None, limit=30):
    config = config or get_backup_configuration()
    if not config.remote_path or shutil.which('rclone') is None:
        return []
    try:
        completed = _run_command(['rclone', 'lsf', '--dirs-only', config.remote_path], timeout=60)
    except RuntimeError:
        return []
    rows = []
    for line in completed.stdout.splitlines():
        try:
            backup_name = _safe_backup_name(line.strip().strip('/'))
        except RuntimeError:
            continue
        rows.append({'name': backup_name})
    return sorted(rows, key=lambda row: row['name'], reverse=True)[:limit]


def download_remote_backup(config, backup_name):
    if not config.remote_path:
        raise RuntimeError('Configure um remoto antes de baixar backup da nuvem.')
    if shutil.which('rclone') is None:
        raise RuntimeError('rclone nao encontrado no ambiente da aplicacao.')
    backup_name = _safe_backup_name(backup_name)
    local_path = backup_path_for_name(backup_name)
    if local_path.exists():
        raise RuntimeError('Este backup ja existe localmente.')
    local_path.mkdir(parents=True)
    remote_source = f'{config.remote_path.rstrip("/")}/{backup_name}'
    try:
        _run_command(['rclone', 'copy', remote_source, str(local_path)], timeout=1800)
    except Exception:
        shutil.rmtree(local_path, ignore_errors=True)
        raise
    return local_path


def _cleanup_remote_backups(config, keep_name, retention_days):
    if not config.remote_path or shutil.which('rclone') is None:
        return []
    removed = []
    now = timezone.localtime().replace(tzinfo=None)
    for row in list_remote_backups(config, limit=1000):
        name = row['name']
        if name == keep_name:
            continue
        stamp = _parse_backup_stamp(name)
        if not stamp:
            continue
        age_days = (now - stamp).days
        if age_days > int(retention_days):
            remote_target = f'{config.remote_path.rstrip("/")}/{name}'
            try:
                _run_command(['rclone', 'purge', remote_target], timeout=600)
                removed.append(name)
            except RuntimeError:
                continue
    return removed


def _cleanup_old_backups(backups_dir, keep_path, retention_days):
    now = timezone.now().timestamp()
    max_age_seconds = int(retention_days) * 24 * 60 * 60
    for path in backups_dir.iterdir():
        if not path.is_dir() or path == keep_path:
            continue
        age = now - path.stat().st_mtime
        if age > max_age_seconds:
            shutil.rmtree(path)


def _write_manifest(backup_root, lines):
    (backup_root / 'manifest.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def _create_backup_package(backup_root):
    package_path = backup_root / 'backup_package.tar.gz'
    package_items = ['db.dump', 'media.tar.gz', 'app_config.tar.gz', 'manifest.txt']
    with tarfile.open(package_path, 'w:gz') as tar:
        for item in package_items:
            item_path = backup_root / item
            if item_path.exists():
                tar.add(item_path, arcname=item)
    return package_path


def run_backup(config=None, *, force_local_only=False):
    config = config or get_backup_configuration()
    if shutil.which('pg_dump') is None:
        raise RuntimeError('pg_dump nao encontrado no ambiente da aplicacao.')

    stamp = timezone.localtime().strftime('%Y%m%d_%H%M%S')
    backups_dir = settings.BASE_DIR / 'backups'
    backup_root = backups_dir / stamp
    backup_root.mkdir(parents=True, exist_ok=False)

    db = settings.DATABASES['default']
    env = os.environ.copy()
    if db.get('PASSWORD'):
        env['PGPASSWORD'] = db['PASSWORD']

    db_dump = backup_root / 'db.dump'
    _run_command([
        'pg_dump',
        '-h', str(db.get('HOST') or 'localhost'),
        '-p', str(db.get('PORT') or '5432'),
        '-U', str(db.get('USER') or ''),
        '-d', str(db.get('NAME') or ''),
        '--format=custom',
        '--file', str(db_dump),
    ], env=env, timeout=900)

    media_path = settings.BASE_DIR / 'media'
    with tarfile.open(backup_root / 'media.tar.gz', 'w:gz') as tar:
        if media_path.exists():
            tar.add(media_path, arcname='media')

    with tarfile.open(backup_root / 'app_config.tar.gz', 'w:gz') as tar:
        for source in CONFIG_PATHS:
            _add_to_tar(tar, source)
        _add_runtime_env_to_tar(tar)
        _add_rclone_config_to_tar(tar)

    manifest_lines = [
        'Backup My Robot Checklist',
        f'Data: {timezone.localtime().isoformat()}',
        f'Banco: {db.get("NAME", "")}',
        'Arquivos: db.dump, media.tar.gz, app_config.tar.gz',
        'Arquivos locais: incluidos em media.tar.gz quando existirem',
        'Configuracoes: inclui .env quando existir, .env.generated, codigo, scripts, static, grafana e rclone quando existirem',
        'Pacote restauravel: backup_package.tar.gz',
        f'Destino em nuvem: {config.get_cloud_provider_display()}',
        f'Retencao local/nuvem: {config.retention_days} dia(s)',
    ]
    _write_manifest(backup_root, manifest_lines)
    package_path = _create_backup_package(backup_root)

    result = BackupRunResult(local_path=backup_root, package_path=package_path)

    if force_local_only:
        result.cloud_status = 'disabled'
        result.cloud_message = 'Envio para nuvem ignorado para backup de segurança local.'
    elif config.active and config.remote_path:
        if shutil.which('rclone') is None:
            result.cloud_status = 'skipped'
            result.cloud_message = 'rclone nao encontrado no ambiente da aplicacao.'
            result.warnings.append(result.cloud_message)
        else:
            remote_target = f'{config.remote_path.rstrip("/")}/{stamp}'
            try:
                _run_command(['rclone', 'copy', str(backup_root), remote_target], timeout=1800)
                removed_remote = _cleanup_remote_backups(config, stamp, config.retention_days)
                result.cloud_status = 'uploaded'
                result.cloud_message = remote_target
                if removed_remote:
                    result.warnings.append(f'Remotos antigos removidos: {", ".join(removed_remote)}')
            except RuntimeError as exc:
                result.cloud_status = 'failed'
                result.cloud_message = str(exc)
                result.warnings.append(result.cloud_message)
    else:
        result.cloud_status = 'disabled'
        result.cloud_message = 'Envio para nuvem desativado.'

    manifest_lines.extend([
        f'Status nuvem: {result.cloud_status}',
        f'Detalhe nuvem: {result.cloud_message}',
    ])
    _write_manifest(backup_root, manifest_lines)
    result.package_path = _create_backup_package(backup_root)

    _cleanup_old_backups(backups_dir, backup_root, config.retention_days)
    return result


def _safe_extract_tar(tar, destination):
    destination = destination.resolve()
    for member in tar.getmembers():
        member_path = (destination / member.name).resolve()
        if destination != member_path and destination not in member_path.parents:
            raise RuntimeError('Arquivo de backup contem caminho inseguro.')
    tar.extractall(destination)


def _safe_extract_zip(zip_file, destination):
    destination = destination.resolve()
    for member in zip_file.infolist():
        member_path = (destination / member.filename).resolve()
        if destination != member_path and destination not in member_path.parents:
            raise RuntimeError('Arquivo de backup contem caminho inseguro.')
    zip_file.extractall(destination)


def _copy_backup_files_from_source(source_dir, backup_root):
    db_files = list(source_dir.rglob('db.dump'))
    if not db_files:
        raise RuntimeError('db.dump nao encontrado no arquivo enviado.')
    source_root = db_files[0].parent
    expected_files = ['db.dump', 'media.tar.gz', 'app_config.tar.gz', 'manifest.txt', 'backup_package.tar.gz']
    for filename in expected_files:
        source_file = source_root / filename
        if source_file.exists() and source_file.resolve() != (backup_root / filename).resolve():
            shutil.copy2(source_file, backup_root / filename)
    if not (backup_root / 'manifest.txt').exists():
        _write_manifest(backup_root, [
            'Backup My Robot Checklist',
            f'Data de importacao: {timezone.localtime().isoformat()}',
            'Origem: upload manual na tela Backups',
        ])
    if not (backup_root / 'backup_package.tar.gz').exists():
        _create_backup_package(backup_root)


def import_uploaded_backup(uploaded_file):
    stem = Path(uploaded_file.name).name
    safe_stem = ''.join(char if char.isalnum() or char in {'-', '_'} else '_' for char in stem.split('.')[0])[:40] or 'backup'
    backup_name = f'upload_{timezone.localtime().strftime("%Y%m%d_%H%M%S")}_{safe_stem}'
    backup_root = backup_path_for_name(backup_name)
    backup_root.mkdir(parents=True, exist_ok=False)
    upload_path = backup_root / stem
    try:
        with upload_path.open('wb') as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        lower_name = stem.lower()
        if lower_name.endswith('.dump'):
            shutil.copy2(upload_path, backup_root / 'db.dump')
            _write_manifest(backup_root, [
                'Backup My Robot Checklist',
                f'Data de importacao: {timezone.localtime().isoformat()}',
                'Origem: upload manual de db.dump',
                'Arquivos locais: nao incluidos neste arquivo',
            ])
            _create_backup_package(backup_root)
        elif lower_name.endswith('.zip'):
            extracted_dir = backup_root / '_extract'
            extracted_dir.mkdir()
            with zipfile.ZipFile(upload_path) as archive:
                _safe_extract_zip(archive, extracted_dir)
            _copy_backup_files_from_source(extracted_dir, backup_root)
            shutil.rmtree(extracted_dir, ignore_errors=True)
        elif lower_name.endswith(('.tar', '.tar.gz', '.tgz')):
            extracted_dir = backup_root / '_extract'
            extracted_dir.mkdir()
            with tarfile.open(upload_path) as archive:
                _safe_extract_tar(archive, extracted_dir)
            _copy_backup_files_from_source(extracted_dir, backup_root)
            shutil.rmtree(extracted_dir, ignore_errors=True)
        else:
            raise RuntimeError('Formato de backup nao suportado.')

        upload_path.unlink(missing_ok=True)
        return BackupImportResult(
            backup_name=backup_name,
            local_path=backup_root,
            has_media=(backup_root / 'media.tar.gz').exists(),
        )
    except Exception:
        shutil.rmtree(backup_root, ignore_errors=True)
        raise


def _recreate_database(db):
    name = str(db.get('NAME') or '')
    if not name:
        raise RuntimeError('Nome do banco não configurado.')
    conn = connect(
        dbname='postgres',
        user=str(db.get('USER') or ''),
        password=str(db.get('PASSWORD') or ''),
        host=str(db.get('HOST') or 'localhost'),
        port=str(db.get('PORT') or '5432'),
        autocommit=True,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s', [name])
            cursor.execute(sql.SQL('DROP DATABASE IF EXISTS {}').format(sql.Identifier(name)))
            cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    finally:
        conn.close()


def restore_local_backup(backup_name, *, restore_media=True, create_safety_backup=True):
    backup_name = _safe_backup_name(backup_name)
    backup_path = backup_path_for_name(backup_name)
    db_dump = backup_path / 'db.dump'
    if not db_dump.exists():
        raise RuntimeError('db.dump nao encontrado neste backup.')
    if shutil.which('pg_restore') is None:
        raise RuntimeError('pg_restore nao encontrado no ambiente da aplicacao.')

    safety_backup = None
    if create_safety_backup:
        config = get_backup_configuration()
        safety_result = run_backup(config, force_local_only=True)
        safety_backup = safety_result.local_path

    db = settings.DATABASES['default']
    env = os.environ.copy()
    if db.get('PASSWORD'):
        env['PGPASSWORD'] = db['PASSWORD']

    connections.close_all()
    _recreate_database(db)
    _run_command([
        'pg_restore',
        '-h', str(db.get('HOST') or 'localhost'),
        '-p', str(db.get('PORT') or '5432'),
        '-U', str(db.get('USER') or ''),
        '-d', str(db.get('NAME') or ''),
        '--no-owner',
        '--no-acl',
        str(db_dump),
    ], env=env, timeout=1800)
    connections.close_all()
    call_command('migrate', interactive=False, verbosity=0)

    restored_media = False
    media_archive = backup_path / 'media.tar.gz'
    if restore_media and media_archive.exists():
        media_dir = (settings.BASE_DIR / 'media').resolve()
        expected_media_dir = (settings.BASE_DIR / 'media').resolve()
        if media_dir != expected_media_dir:
            raise RuntimeError('Diretorio de media invalido.')
        if media_dir.exists():
            shutil.rmtree(media_dir)
        with tarfile.open(media_archive, 'r:gz') as tar:
            _safe_extract_tar(tar, settings.BASE_DIR)
        restored_media = True

    return BackupRestoreResult(
        backup_name=backup_name,
        restored_path=backup_path,
        safety_backup_path=safety_backup,
        restored_media=restored_media,
    )


def scheduled_backup_is_due(config=None, now=None):
    config = config or get_backup_configuration()
    now = timezone.localtime(now or timezone.now())
    if now.time() < config.backup_time:
        return False
    if config.last_scheduled_run_at:
        last_run = timezone.localtime(config.last_scheduled_run_at)
        if last_run.date() == now.date():
            return False
    return True


def run_scheduled_backup_if_due():
    config = get_backup_configuration()
    if not scheduled_backup_is_due(config):
        return None
    result = run_backup(config)
    config.last_scheduled_run_at = timezone.now()
    config.save(update_fields=['last_scheduled_run_at', 'updated_at'])
    return result
