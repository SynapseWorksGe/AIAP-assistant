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
| POST | `/api/v1/zoom/join` | Подключиться к Zoom-встрече и начать запись |
| POST | `/api/v1/zoom/stop/{session_id}` | Остановить запись |
| GET | `/api/v1/zoom/status/{session_id}` | Статус сессии записи |
| GET | `/api/v1/zoom/sessions` | Список всех сессий |
| POST | `/api/v1/zoom/transcribe/{session_id}` | Вручную отправить запись на расшифровку |
| GET | `/health` | Health check |
| GET | `/health/details` | Детальная проверка (включая AIAP) |

### Пример: начать запись

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

### Пример: остановить запись

```bash
curl -X POST http://167.86.122.142/zoom/api/v1/zoom/stop/{session_id}
```

### Пример: проверить статус

```bash
curl http://167.86.122.142/zoom/api/v1/zoom/status/{session_id}
```

## Развёртывание

### На сервере 167.86.122.142 (рядом с AIAP Protocol)

1. Склонировать репозиторий:
```bash
cd /opt
git clone https://github.com/SynapseWorksGe/AIAP-assistant.git
```

2. Добавить сервис в основной `docker-compose.yml` AIAP Protocol (`/opt/AIAP-protocol/deploy/docker-compose.yml`):

```yaml
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

Добавить volume:
```yaml
volumes:
  aiap-uploads:
  zoom-recordings:   # ← добавить
```

3. Скопировать env-файл:
```bash
cp /opt/AIAP-assistant/deploy/envs/zoom-assistant.env /opt/AIAP-protocol/deploy/envs/
```

4. Добавить location в nginx конфиг (`/opt/AIAP-protocol/deploy/nginx/default.conf`):
```nginx
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

5. Пересобрать и запустить:
```bash
cd /opt/AIAP-protocol/deploy
docker compose up -d --build
```

### Автономный запуск (без AIAP compose)

```bash
cd deploy
docker compose up -d --build
```

## Технологии

- **FastAPI** + Uvicorn — API-сервер
- **Playwright** (Chromium) — headless браузер для подключения к Zoom
- **PulseAudio** — захват аудио из браузера
- **FFmpeg** — кодирование аудио (OGG/Opus)
- **AIAP Protocol** — расшифровка через Yandex STT + Claude AI

## Конфигурация

См. [.env.example](.env.example) для всех доступных переменных.
