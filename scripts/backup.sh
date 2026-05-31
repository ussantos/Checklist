#!/usr/bin/env bash
set -euo pipefail

# Backup diário do sistema My Robot Checklist.
# Faz dump do PostgreSQL + arquivos de evidência + configurações essenciais.
# Recomendado no cron: 0 20 * * * cd /opt/checkups && /bin/bash scripts/backup.sh >> logs/backup.log 2>&1

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

set -a
source .env
set +a

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_ROOT="$APP_DIR/backups/$STAMP"
mkdir -p "$BACKUP_ROOT"
mkdir -p "$APP_DIR/logs"

echo "[$(date)] Iniciando backup $STAMP"

# Banco de dados. Usa o container para evitar depender do psql no host.
docker compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --file=/tmp/db.dump
docker compose cp db:/tmp/db.dump "$BACKUP_ROOT/db.dump"
docker compose exec -T db rm -f /tmp/db.dump

# Arquivos de evidência e configurações necessárias.
tar -czf "$BACKUP_ROOT/media.tar.gz" media 2>/dev/null || true
tar -czf "$BACKUP_ROOT/app_config.tar.gz" .env docker-compose.yml seed scripts requirements.txt Dockerfile myrobot_checklist checklists templates static 2>/dev/null

# Manifesto simples para conferência.
cat > "$BACKUP_ROOT/manifest.txt" <<EOF
Backup My Robot Checklist
Data: $(date --iso-8601=seconds)
Banco: $POSTGRES_DB
Arquivos: db.dump, media.tar.gz, app_config.tar.gz
EOF

# Sincronização opcional para Google Drive/OneDrive via rclone.
if command -v rclone >/dev/null 2>&1 && [[ -n "${RCLONE_REMOTE:-}" ]]; then
  echo "[$(date)] Enviando para rclone: $RCLONE_REMOTE/$STAMP"
  rclone copy "$BACKUP_ROOT" "$RCLONE_REMOTE/$STAMP"
else
  echo "[$(date)] rclone não configurado ou não instalado. Backup ficou local em $BACKUP_ROOT"
fi

# Retenção local.
find "$APP_DIR/backups" -mindepth 1 -maxdepth 1 -type d -mtime +"${BACKUP_RETENTION_DAYS:-30}" -exec rm -rf {} \;

echo "[$(date)] Backup concluído: $BACKUP_ROOT"
