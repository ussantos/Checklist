#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${CHECKLIST_INSTALL_DIR:-/opt/checklist}"
APP_BIND="${CHECKLIST_APP_BIND:-0.0.0.0:8000}"
GRAFANA_BIND="${CHECKLIST_GRAFANA_BIND:-0.0.0.0:3000}"
RUN_OPERATIONAL_SEED="${CHECKLIST_RUN_OPERATIONAL_SEED:-False}"
FORCE_PASSWORD_CHANGE="${CHECKLIST_FORCE_PASSWORD_CHANGE_ON_FIRST_LOGIN:-False}"
CREDENTIALS_FILE="${CHECKLIST_CREDENTIALS_FILE:-/root/checklist-credentials.txt}"
SOURCE_DIR="${CHECKLIST_SOURCE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

log() {
  printf '\n[Checklist] %s\n' "$*"
}

fail() {
  printf '\n[Checklist] ERRO: %s\n' "$*" >&2
  exit 1
}

is_true() {
  case "${1:-}" in
    [Tt][Rr][Uu][Ee]|1|[Yy][Ee][Ss]|[Ss][Ii][Mm]) return 0 ;;
    *) return 1 ;;
  esac
}

random_secret() {
  local length="${1:-32}"
  openssl rand -base64 64 | tr -d '\n' | tr '/+' '_-' | cut -c1-"${length}"
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    fail "Execute com sudo: sudo ./install_ubuntu26.sh"
  fi
}

check_ubuntu() {
  if [[ ! -r /etc/os-release ]]; then
    fail "Nao foi possivel identificar o sistema operacional."
  fi
  # shellcheck disable=SC1091
  . /etc/os-release
  if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "26.04" ]]; then
    if ! is_true "${CHECKLIST_ALLOW_UNSUPPORTED:-False}"; then
      fail "Este instalador foi feito para Ubuntu Server 26.04 LTS. Defina CHECKLIST_ALLOW_UNSUPPORTED=True para continuar mesmo assim."
    fi
  fi
}

install_base_packages() {
  log "Instalando pacotes base do Ubuntu"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl gnupg lsb-release openssl rsync tar gzip ufw
}

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    log "Docker e Docker Compose ja estao instalados"
    systemctl enable --now docker
    return
  fi

  log "Instalando Docker Engine e Docker Compose Plugin"
  install -m 0755 -d /etc/apt/keyrings
  if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
  fi

  # shellcheck disable=SC1091
  . /etc/os-release
  local codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-resolute}}"
  local arch
  arch="$(dpkg --print-architecture)"
  cat >/etc/apt/sources.list.d/docker.list <<EOF
deb [arch=${arch} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${codename} stable
EOF

  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
}

copy_application() {
  [[ -f "${SOURCE_DIR}/docker-compose.yml" ]] || fail "docker-compose.yml nao encontrado em ${SOURCE_DIR}."

  log "Copiando aplicacao para ${APP_DIR}"
  mkdir -p "${APP_DIR}"

  local source_real target_real
  source_real="$(realpath "${SOURCE_DIR}")"
  target_real="$(realpath "${APP_DIR}")"

  if [[ "${source_real}" != "${target_real}" ]]; then
    rsync -a --delete \
      --exclude '.git/' \
      --exclude '.env' \
      --exclude '*.env' \
      --exclude 'media/' \
      --exclude 'logs/' \
      --exclude 'backups/' \
      --exclude 'rclone/' \
      --exclude 'staticfiles/' \
      --exclude 'dist/' \
      --exclude '__pycache__/' \
      --exclude '*.pyc' \
      "${SOURCE_DIR}/" "${APP_DIR}/"
  fi

  mkdir -p "${APP_DIR}/media" "${APP_DIR}/staticfiles" "${APP_DIR}/logs" "${APP_DIR}/backups" "${APP_DIR}/rclone"
  chmod 700 "${APP_DIR}/backups" "${APP_DIR}/rclone"
}

detect_first_ip() {
  hostname -I 2>/dev/null | awk '{print $1}'
}

write_env_file() {
  if [[ -f "${APP_DIR}/.env" ]] && ! is_true "${CHECKLIST_REGENERATE_ENV:-False}"; then
    log "Arquivo .env existente preservado em ${APP_DIR}/.env"
    return
  fi

  log "Gerando .env com senhas fortes"
  local host_ip allowed_hosts csrf_origins
  host_ip="$(detect_first_ip || true)"
  allowed_hosts="${CHECKLIST_DJANGO_ALLOWED_HOSTS:-*}"
  csrf_origins="${CHECKLIST_CSRF_TRUSTED_ORIGINS:-http://localhost:8000,http://127.0.0.1:8000}"
  if [[ -n "${host_ip}" ]]; then
    if [[ "${allowed_hosts}" != "*" ]]; then
      allowed_hosts="${allowed_hosts},${host_ip}"
    fi
    csrf_origins="${csrf_origins},http://${host_ip}:8000"
  fi

  local django_secret postgres_password admin_password grafana_password
  django_secret="$(random_secret 64)"
  postgres_password="$(random_secret 32)"
  admin_password="$(random_secret 16)aA1!"
  grafana_password="$(random_secret 16)gG1!"

  cat >"${APP_DIR}/.env" <<EOF
# Gerado pelo instalador Checklist em $(date -Is)
DJANGO_SECRET_KEY=${django_secret}
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=${allowed_hosts}
CSRF_TRUSTED_ORIGINS=${csrf_origins}

APP_BIND=${APP_BIND}

POSTGRES_DB=myrobot_checklist
POSTGRES_USER=myrobot
POSTGRES_PASSWORD=${postgres_password}
POSTGRES_HOST=db
POSTGRES_PORT=5432

GRAFANA_BIND=${GRAFANA_BIND}
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=${grafana_password}

INITIAL_CHECKLISTADMIN_PASSWORD=${admin_password}
FORCE_PASSWORD_CHANGE_ON_FIRST_LOGIN=${FORCE_PASSWORD_CHANGE}
AUTO_SEED_OPERATIONAL_DATA=False

MAX_EVIDENCE_FILE_SIZE_MB=5

RCLONE_REMOTE=gdrive:MyRobotBackups/checklist
BACKUP_RETENTION_DAYS=30
BACKUP_SCHEDULER_INTERVAL_SECONDS=60
EOF
  chmod 600 "${APP_DIR}/.env"

  cat >"${CREDENTIALS_FILE}" <<EOF
Checklist instalado em: ${APP_DIR}
Data: $(date -Is)

Aplicacao:
  URL local: http://127.0.0.1:8000/
  URL rede: http://${host_ip:-IP_DO_SERVIDOR}:8000/
  Usuario inicial: checklistadmin
  Senha inicial: ${admin_password}

Grafana:
  URL local: http://127.0.0.1:3000/
  Usuario: admin
  Senha: ${grafana_password}

Banco PostgreSQL:
  Usuario: myrobot
  Senha: ${postgres_password}

Troque as senhas iniciais apos o primeiro acesso.
EOF
  chmod 600 "${CREDENTIALS_FILE}"
}

compose_up() {
  log "Subindo Docker Compose"
  cd "${APP_DIR}"
  docker compose up -d --build
}

wait_for_web() {
  log "Aguardando aplicacao Django ficar pronta"
  cd "${APP_DIR}"
  local tries=60
  until docker compose exec -T web python manage.py check >/dev/null 2>&1; do
    tries=$((tries - 1))
    if [[ "${tries}" -le 0 ]]; then
      docker compose logs --tail=120 web || true
      fail "A aplicacao nao ficou pronta no tempo esperado."
    fi
    sleep 5
  done
}

ensure_initial_admin() {
  log "Garantindo usuario administrador inicial checklistadmin"
  cd "${APP_DIR}"
  docker compose exec -T web python manage.py shell <<'PY'
import os
from django.contrib.auth import get_user_model
from checklists.models import UserProfile

password = os.environ.get('INITIAL_CHECKLISTADMIN_PASSWORD')
if not password:
    raise SystemExit('INITIAL_CHECKLISTADMIN_PASSWORD nao definido.')

User = get_user_model()
user, created = User.objects.get_or_create(
    username='checklistadmin',
    defaults={
        'first_name': 'Administrador Checklist',
        'is_staff': True,
        'is_superuser': True,
        'is_active': True,
    },
)
if created or not user.has_usable_password():
    user.set_password(password)
user.first_name = 'Administrador Checklist'
user.last_name = ''
user.is_staff = True
user.is_superuser = True
user.is_active = True
user.save()

profile, _ = UserProfile.objects.get_or_create(user=user)
profile.display_name = 'Administrador Checklist'
profile.system_role = UserProfile.ROLE_ADMIN
profile.position = None
profile.active = True
profile.must_change_password = False
profile.save()

print('Administrador checklistadmin pronto.')
PY
}

run_optional_seed() {
  if is_true "${RUN_OPERATIONAL_SEED}"; then
    log "Executando seed operacional solicitado"
    cd "${APP_DIR}"
    docker compose exec -T web python manage.py seed_operational_data
  else
    log "Seed operacional nao executado. Para importar depois: docker compose exec web python manage.py seed_operational_data"
  fi
}

final_checks() {
  log "Executando validacoes finais"
  cd "${APP_DIR}"
  docker compose exec -T web python manage.py makemigrations --check --dry-run
  docker compose ps
}

print_summary() {
  local host_ip
  host_ip="$(detect_first_ip || true)"
  log "Instalacao concluida"
  cat <<EOF

Diretorio: ${APP_DIR}
Credenciais geradas: ${CREDENTIALS_FILE}

Aplicacao:
  Bind configurado: ${APP_BIND}
  Acesso local: http://127.0.0.1:8000/
  Acesso rede: http://${host_ip:-IP_DO_SERVIDOR}:8000/

Grafana:
  Bind configurado: ${GRAFANA_BIND}
  Acesso local: http://127.0.0.1:3000/

Se precisar acessar o Grafana remotamente mantendo bind local, use tunel SSH, por exemplo:
  ssh -L 8000:127.0.0.1:8000 -L 3000:127.0.0.1:3000 usuario@${host_ip:-IP_DO_SERVIDOR}

Para configurar Google Drive ou OneDrive:
  cd ${APP_DIR}
  docker compose exec web rclone config

EOF
}

main() {
  require_root
  check_ubuntu
  install_base_packages
  install_docker
  copy_application
  write_env_file
  compose_up
  wait_for_web
  ensure_initial_admin
  run_optional_seed
  final_checks
  print_summary
}

main "$@"
