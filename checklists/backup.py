import os
import shutil
import subprocess
import tarfile
from dataclasses import dataclass, field
from datetime import datetime
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


@dataclass
class BackupRunResult:
    local_path: Path
    cloud_status: str = 'disabled'
    cloud_message: str = ''
    warnings: list[str] = field(default_factory=list)


@dataclass
class BackupRestoreResult:
    backup_name: str
    restored_path: Path
    safety_backup_path: Path | None = None
    restored_media: bool = False


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
        })
    return sorted(rows, key=lambda row: row['created_at'], reverse=True)[:limit]


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


def _cleanup_old_backups(backups_dir, keep_path, retention_days):
    now = timezone.now().timestamp()
    max_age_seconds = int(retention_days) * 24 * 60 * 60
    for path in backups_dir.iterdir():
        if not path.is_dir() or path == keep_path:
            continue
        age = now - path.stat().st_mtime
        if age > max_age_seconds:
            shutil.rmtree(path)


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

    result = BackupRunResult(local_path=backup_root)
    manifest_lines = [
        'Backup My Robot Checklist',
        f'Data: {timezone.localtime().isoformat()}',
        f'Banco: {db.get("NAME", "")}',
        'Arquivos: db.dump, media.tar.gz, app_config.tar.gz',
        f'Destino em nuvem: {config.get_cloud_provider_display()}',
    ]

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
                result.cloud_status = 'uploaded'
                result.cloud_message = remote_target
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
    (backup_root / 'manifest.txt').write_text('\n'.join(manifest_lines) + '\n', encoding='utf-8')

    _cleanup_old_backups(backups_dir, backup_root, config.retention_days)
    return result


def _safe_extract_tar(tar, destination):
    destination = destination.resolve()
    for member in tar.getmembers():
        member_path = (destination / member.name).resolve()
        if destination != member_path and destination not in member_path.parents:
            raise RuntimeError('Arquivo de backup contem caminho inseguro.')
    tar.extractall(destination)


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
