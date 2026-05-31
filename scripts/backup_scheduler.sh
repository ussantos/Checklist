#!/usr/bin/env bash
set -euo pipefail

INTERVAL="${BACKUP_SCHEDULER_INTERVAL_SECONDS:-60}"
mkdir -p /app/logs

echo "[$(date)] Agendador de backup iniciado. Intervalo: ${INTERVAL}s"

until python manage.py migrate --check >/dev/null 2>&1; do
  echo "[$(date)] Aguardando migrations da aplicacao..."
  sleep 5
done

while true; do
  python manage.py run_due_backup || true
  sleep "$INTERVAL"
done
