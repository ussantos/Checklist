#!/usr/bin/env bash
set -euo pipefail

# Restauração do sistema My Robot Checklist.
# Uso: ./scripts/restore.sh /caminho/do/backup/YYYYMMDD_HHMMSS

if [[ $# -ne 1 ]]; then
  echo "Uso: $0 /caminho/do/backup" >&2
  exit 1
fi

BACKUP_DIR="$1"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

if [[ ! -f "$BACKUP_DIR/db.dump" ]]; then
  echo "db.dump não encontrado em $BACKUP_DIR" >&2
  exit 1
fi

set -a
source .env
set +a

echo "ATENÇÃO: esta operação substituirá o banco atual. Pressione ENTER para continuar ou Ctrl+C para cancelar."
read -r _

docker compose up -d db
sleep 5

docker compose cp "$BACKUP_DIR/db.dump" db:/tmp/db.dump
# Recria o banco para garantir restauração limpa.
docker compose exec -T db psql -U "$POSTGRES_USER" -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${POSTGRES_DB}';" || true
docker compose exec -T db psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS ${POSTGRES_DB};"
docker compose exec -T db psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE ${POSTGRES_DB};"
docker compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists /tmp/db.dump

if [[ -f "$BACKUP_DIR/media.tar.gz" ]]; then
  rm -rf media
  tar -xzf "$BACKUP_DIR/media.tar.gz" -C "$APP_DIR"
fi

docker compose up -d --build

echo "Restauração concluída. Acesse o sistema e valide dashboard, usuários e anexos."
