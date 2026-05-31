#!/usr/bin/env bash
set -euo pipefail

# Backup diário do sistema My Robot Checklist.
# Executa o backup configurado na tela administrativa do Django.
# Recomendado no cron: 0 20 * * * cd /opt/checklist && /bin/bash scripts/backup.sh >> logs/backup.log 2>&1

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

mkdir -p "$APP_DIR/logs"

echo "[$(date)] Iniciando backup configurado"
docker compose exec -T web python manage.py run_configured_backup
echo "[$(date)] Backup finalizado"

