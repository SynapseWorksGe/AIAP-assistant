# AIAP Zoom Assistant

Сервис для автоматической записи Zoom-звонков и отправки на расшифровку через [AIAP Meeting Protocol](https://github.com/SynapseWorksGe/AIAP-protocol).

## Как работает

1. Вы отправляете ссылку на Zoom-встречу через API
2. Бот подключается к встрече через веб-клиент Zoom (headless Chromium + Playwright)
3. Аудио записывается через PulseAudio virtual sink + FFmpeg
4. После окончания встречи (или ручной остановки) запись отправляется в AIAP Protocol для расшифровки
5. Результат — транскрипция, саммари, PDF-протокол

## API

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| `POST` | `/api/v1/zoom/join` | Подключиться к Zoom-встрече и начать запись |
| `POST` | `/api/v1/zoom/stop/{session_id}` | Остановить запись |
| `GET` | `/api/v1/zoom/status/{session_id}` | Статус сессии записи |
| `GET` | `/api/v1/zoom/sessions` | Список всех сессий |
| `POST` | `/api/v1/zoom/transcribe/{session_id}` | Вручную отправить запись на расшифровку |
| `GET` | `/health` | Health check |
| `GET` | `/health/details` | Детальная проверка (включая связь с AIAP) |

### Примеры использования

**Начать запись:**
```bash
curl -X POST http://167.86.122.142/zoom/api/v1/zoom/join \
  -H "Content-Type: application/json" \
  -d '{
    "zoom_url": "https://zoom.us/j/12345678?pwd=xxx",
    "bot_name": "Записываем встречу",
    "language": "ru-RU",
    "auto_transcribe": true
  }'
```

**Остановить запись:**
```bash
curl -X POST http://167.86.122.142/zoom/api/v1/zoom/stop/{session_id}
```

**Проверить статус:**
```bash
curl http://167.86.122.142/zoom/api/v1/zoom/status/{session_id}
```

---

## Развёртывание на сервере 167.86.122.142

### Предварительные требования

- Сервер с Docker и Docker Compose (уже настроен для AIAP Protocol)
- AIAP Protocol развёрнут в `/opt/AIAP-protocol/deploy/`

---

### Вариант A: Автоматический (скрипт)

```bash
# 1. Клонировать репозиторий
cd /opt
git clone https://github.com/SynapseWorksGe/AIAP-assistant.git

# 2. Запустить скрипт развёртывания
bash /opt/AIAP-assistant/scripts/deploy.sh
```

Скрипт автоматически:
- Проверит, что AIAP Protocol установлен
- Создаст env-файл из шаблона
- Добавит `zoom-assistant` сервис в `docker-compose.yml`
- Добавит `location /zoom/` в Nginx
- Соберёт Docker-образ
- Запустит сервис
- Проверит health check

---

### Вариант B: Ручной (пошагово)

#### Шаг 1. Клонировать репозиторий

```bash
cd /opt
git clone https://github.com/SynapseWorksGe/AIAP-assistant.git
```

#### Шаг 2. Скопировать env-файл

```bash
cp /opt/AIAP-assistant/deploy/envs/zoom-assistant.env \
   /opt/AIAP-protocol/deploy/envs/zoom-assistant.env
```

При необходимости отредактировать:
```bash
nano /opt/AIAP-protocol/deploy/envs/zoom-assistant.env
```

Ключевые переменные:
| Переменная | Значение | Описание |
|-----------|----------|----------|
| `BOT_NAME` | `AIAP Recorder` | Имя бота в Zoom |
| `AIAP_BASE_URL` | `http://aiap-protocol:8000` | URL AIAP (внутри Docker-сети) |
| `MAX_RECORDING_DURATION_SEC` | `14400` | Макс. длительность записи (4ч) |

#### Шаг 3. Добавить сервис в docker-compose.yml

Открыть `/opt/AIAP-protocol/deploy/docker-compose.yml` и добавить в секцию `services:`:

```yaml
  # ── Zoom Assistant ───────────────────────────────────────────────────
  zoom-assistant:
    build:
      context: /opt/AIAP-assistant
      dockerfile: Dockerfile
    container_name: zoom-assistant
    env_file:
      - ./envs/zoom-assistant.env
    volumes:
      - zoom-recordings:/tmp/zoom-recordings
    restart: unless-stopped
    networks:
      - services
```

Добавить в `depends_on` у nginx:
```yaml
    depends_on:
      - aiap-protocol
      - zoom-assistant   # ← добавить
```

Добавить в секцию `volumes:`:
```yaml
volumes:
  aiap-uploads:
  zoom-recordings:    # ← добавить
```

#### Шаг 4. Добавить location в Nginx

Открыть `/opt/AIAP-protocol/deploy/nginx/default.conf` и добавить внутри `server { }`:

```nginx
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
    }
```

#### Шаг 5. Собрать и запустить

```bash
cd /opt/AIAP-protocol/deploy

# Собрать образ (3-5 минут — устанавливается Chromium)
docker compose build zoom-assistant

# Запустить все сервисы
docker compose up -d
```

#### Шаг 6. Проверить

```bash
# Статус контейнера
docker ps | grep zoom-assistant

# Логи
docker logs -f zoom-assistant

# Health check
curl http://167.86.122.142/zoom/health

# Детальная проверка (включая связь с AIAP)
curl http://167.86.122.142/zoom/health/details

# Swagger UI
# Открыть в браузере: http://167.86.122.142/zoom/docs
```

---

### Итоговая архитектура на сервере

```
Nginx (порт 80)
  ├── /aiap/  →  aiap-protocol:8000   (расшифровка)
  └── /zoom/  →  zoom-assistant:8001   (запись Zoom)
                       │
                       └── POST /aiap/api/v1/meetings/transcribe
                           (отправляет аудио внутри Docker-сети)
```

---

## Обновление

```bash
cd /opt/AIAP-assistant
git pull

cd /opt/AIAP-protocol/deploy
docker compose build zoom-assistant
docker compose up -d zoom-assistant
```

## Устранение неполадок

**Контейнер не стартует:**
```bash
docker logs zoom-assistant
```

**Нет звука в записи:**
```bash
# Проверить PulseAudio внутри контейнера
docker exec zoom-assistant pactl list sinks short
```

**Не отправляется на расшифровку:**
```bash
# Проверить связь с AIAP
docker exec zoom-assistant curl -s http://aiap-protocol:8000/health
```

## Технологии

- **FastAPI** + Uvicorn — API-сервер
- **Playwright** (Chromium) — headless браузер для подключения к Zoom
- **PulseAudio** — захват аудио из браузера
- **FFmpeg** — кодирование аудио (OGG/Opus, 16kHz mono)
- **gosu** — безопасный drop привилегий в контейнере
- **AIAP Protocol** — расшифровка через Yandex STT + Claude AI
