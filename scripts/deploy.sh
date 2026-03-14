#!/bin/bash
###############################################################################
# deploy.sh — Развёртывание AIAP Zoom Assistant на VPS
#
# Предполагается, что AIAP-protocol уже работает на этом сервере
# в /opt/AIAP-protocol/deploy/ через Docker Compose.
#
# Запуск: bash /opt/AIAP-assistant/scripts/deploy.sh
###############################################################################

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

ASSISTANT_DIR="/opt/AIAP-assistant"
PROTOCOL_DIR="/opt/AIAP-protocol"
PROTOCOL_DEPLOY="${PROTOCOL_DIR}/deploy"
COMPOSE_FILE="${PROTOCOL_DEPLOY}/docker-compose.yml"
NGINX_CONF="${PROTOCOL_DEPLOY}/nginx/default.conf"

###############################################################################
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  AIAP Zoom Assistant — Deployment Script"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ── Step 1: Проверки ────────────────────────────────────────────────────────
echo "── Шаг 1: Проверка окружения ──"

if [ ! -d "$PROTOCOL_DEPLOY" ]; then
    err "AIAP-protocol не найден в ${PROTOCOL_DIR}. Убедитесь, что он развёрнут."
fi

if [ ! -f "$COMPOSE_FILE" ]; then
    err "docker-compose.yml не найден: ${COMPOSE_FILE}"
fi

if ! command -v docker &> /dev/null; then
    err "Docker не установлен. Запустите bootstrap-vps.sh из AIAP-protocol."
fi

if ! docker compose version &> /dev/null; then
    err "Docker Compose (v2) не найден."
fi

log "Все зависимости на месте"

# ── Step 2: Env-файл ───────────────────────────────────────────────────────
echo ""
echo "── Шаг 2: Настройка переменных окружения ──"

ENV_FILE="${PROTOCOL_DEPLOY}/envs/zoom-assistant.env"
ENV_EXAMPLE="${ASSISTANT_DIR}/deploy/envs/zoom-assistant.env.example"

if [ ! -f "$ENV_FILE" ]; then
    if [ -f "$ENV_EXAMPLE" ]; then
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        log "Создан ${ENV_FILE} из шаблона"
    else
        err "Шаблон env-файла не найден: ${ENV_EXAMPLE}"
    fi
else
    log "Env-файл уже существует: ${ENV_FILE}"
fi

# ── Step 3: Добавить сервис в docker-compose.yml ───────────────────────────
echo ""
echo "── Шаг 3: Добавление сервиса в docker-compose.yml ──"

if grep -q "zoom-assistant" "$COMPOSE_FILE"; then
    log "Сервис zoom-assistant уже есть в ${COMPOSE_FILE}"
else
    warn "Добавляю zoom-assistant в ${COMPOSE_FILE}..."

    # Add service before the volumes section
    # We use a Python snippet for reliable YAML editing
    python3 - "$COMPOSE_FILE" "$ASSISTANT_DIR" <<'PYEOF'
import sys

compose_file = sys.argv[1]
assistant_dir = sys.argv[2]

with open(compose_file, 'r') as f:
    content = f.read()

service_block = f"""
  # ── Zoom Assistant ───────────────────────────────────────────────────
  zoom-assistant:
    build:
      context: {assistant_dir}
      dockerfile: Dockerfile
    container_name: zoom-assistant
    env_file:
      - ./envs/zoom-assistant.env
    volumes:
      - zoom-recordings:/tmp/zoom-recordings
    restart: unless-stopped
    networks:
      - services
"""

# Insert before "volumes:" section
if "volumes:" in content:
    content = content.replace("volumes:", service_block + "\nvolumes:", 1)

# Add zoom-recordings volume
if "zoom-recordings:" not in content:
    content = content.rstrip() + "\n  zoom-recordings:\n"

with open(compose_file, 'w') as f:
    f.write(content)

print("OK")
PYEOF

    log "Сервис zoom-assistant добавлен"
fi

# ── Step 4: Добавить nginx location ────────────────────────────────────────
echo ""
echo "── Шаг 4: Настройка Nginx ──"

if grep -q "zoom-assistant" "$NGINX_CONF"; then
    log "Location /zoom/ уже настроен в Nginx"
else
    warn "Добавляю location /zoom/ в ${NGINX_CONF}..."

    ZOOM_LOCATION='
    # ── Zoom Assistant ──────────────────────────────────────────────────
    location /zoom/ {
        proxy_pass         http://zoom-assistant:8001/;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        proxy_read_timeout    600;
        proxy_connect_timeout 60;
        proxy_send_timeout    600;
        client_max_body_size  500M;
    }'

    # Insert before the last closing brace
    python3 - "$NGINX_CONF" "$ZOOM_LOCATION" <<'PYEOF'
import sys

conf_file = sys.argv[1]
location_block = sys.argv[2]

with open(conf_file, 'r') as f:
    content = f.read()

# Find the last '}' and insert before it
last_brace = content.rfind('}')
if last_brace != -1:
    content = content[:last_brace] + location_block + "\n" + content[last_brace:]

with open(conf_file, 'w') as f:
    f.write(content)

print("OK")
PYEOF

    log "Location /zoom/ добавлен"
fi

# ── Step 5: Обновить nginx depends_on ──────────────────────────────────────
echo ""
echo "── Шаг 5: Обновление depends_on для Nginx ──"

if grep -A5 "depends_on" "$COMPOSE_FILE" | grep -q "zoom-assistant"; then
    log "depends_on уже содержит zoom-assistant"
else
    # Add zoom-assistant to nginx depends_on
    sed -i '/depends_on:/,/restart:/{
        /- aiap-protocol/a\      - zoom-assistant
    }' "$COMPOSE_FILE" 2>/dev/null || true
    log "Добавлен zoom-assistant в nginx depends_on"
fi

# ── Step 6: Build and start ────────────────────────────────────────────────
echo ""
echo "── Шаг 6: Сборка и запуск ──"

cd "$PROTOCOL_DEPLOY"

log "Собираю образ zoom-assistant (это может занять 3-5 минут)..."
docker compose build zoom-assistant

log "Запускаю все сервисы..."
docker compose up -d

echo ""
echo "── Шаг 7: Проверка ──"
sleep 3

if docker ps --format '{{.Names}}' | grep -q "zoom-assistant"; then
    log "Контейнер zoom-assistant запущен"
else
    err "Контейнер zoom-assistant не запустился. Проверьте: docker logs zoom-assistant"
fi

# Health check
echo ""
HEALTH=$(curl -s http://localhost:8001/health 2>/dev/null || curl -s http://127.0.0.1/zoom/health 2>/dev/null || echo "unavailable")
if echo "$HEALTH" | grep -q '"ok"'; then
    log "Health check пройден: ${HEALTH}"
else
    warn "Health check не прошёл (сервис может ещё стартовать): ${HEALTH}"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Развёртывание завершено!"
echo ""
echo "  API доступен по адресу:"
echo "    http://167.86.122.142/zoom/api/v1/zoom/join"
echo ""
echo "  Swagger UI:"
echo "    http://167.86.122.142/zoom/docs"
echo ""
echo "  Логи:"
echo "    docker logs -f zoom-assistant"
echo "═══════════════════════════════════════════════════════════"
