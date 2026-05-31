#!/usr/bin/env bash
set -euo pipefail

python manage.py migrate --noinput
python manage.py collectstatic --noinput

case "${AUTO_SEED_OPERATIONAL_DATA:-False}" in
  [Tt][Rr][Uu][Ee]|1|[Yy][Ee][Ss])
    python manage.py seed_operational_data
    ;;
  *)
    echo "AUTO_SEED_OPERATIONAL_DATA is not enabled; skipping seed_operational_data."
    ;;
esac

exec "$@"
