#!/usr/bin/env bash
#
# deploy.sh — установка / обновление Diar Car Buy AI v5.0 на VPS (Ubuntu).
#
# Скрипт запускается НА СЕРВЕРЕ под root:
#   bash deploy.sh
#
# Идемпотентен: при первом запуске ставит систему, клонирует репозиторий,
# создаёт venv, ставит Playwright-браузеры и systemd-сервис; при повторных —
# подтягивает изменения, обновляет зависимости и перезапускает сервис.
#
# Приватный репозиторий: для первого клонирования задайте токен через
# переменную окружения GITHUB_TOKEN, например:
#   GITHUB_TOKEN=ghp_xxx bash deploy.sh
#
set -euo pipefail

# ─────────────── Настройки ───────────────
APP_DIR="${APP_DIR:-/root/diar_car_buy}"
BRANCH="${BRANCH:-claude/stoic-bardeen-C3rZP}"
REPO_SLUG="kirillfomenkov92-crypto/diar_car_buy"
SERVICE_NAME="diarcarbuy"
PYTHON="python3"

log() { echo -e "\n\033[1;32m[deploy]\033[0m $*"; }

# ─────────────── 1. Системные пакеты ───────────────
log "Обновление системы и установка зависимостей"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y "$PYTHON" python3-pip python3-venv git curl wget

# ─────────────── 2. Получение кода ───────────────
if [ -d "$APP_DIR/.git" ]; then
    log "Репозиторий уже есть — обновляю ($BRANCH)"
    cd "$APP_DIR"
    git fetch origin "$BRANCH"
    git checkout "$BRANCH"
    git reset --hard "origin/$BRANCH"
else
    log "Клонирую репозиторий в $APP_DIR"
    if [ -n "${GITHUB_TOKEN:-}" ]; then
        CLONE_URL="https://${GITHUB_TOKEN}@github.com/${REPO_SLUG}.git"
    else
        CLONE_URL="https://github.com/${REPO_SLUG}.git"
    fi
    git clone -b "$BRANCH" "$CLONE_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# ─────────────── 3. Виртуальное окружение ───────────────
log "Настройка virtualenv и установка Python-зависимостей"
if [ ! -d "$APP_DIR/.venv" ]; then
    "$PYTHON" -m venv "$APP_DIR/.venv"
fi
# shellcheck disable=SC1091
source "$APP_DIR/.venv/bin/activate"
pip install --upgrade pip
pip install -r "$APP_DIR/requirements.txt"

# ─────────────── 4. Playwright (если есть в зависимостях) ───────────────
if grep -qi '^playwright' "$APP_DIR/requirements.txt"; then
    log "Установка браузеров Playwright (chromium) и системных зависимостей"
    python -m playwright install-deps || log "playwright install-deps завершился с предупреждениями"
    python -m playwright install chromium
fi

# ─────────────── 5. Конфигурация ───────────────
if [ ! -f "$APP_DIR/config.yaml" ]; then
    if [ -f "$APP_DIR/config.yaml.example" ]; then
        cp "$APP_DIR/config.yaml.example" "$APP_DIR/config.yaml"
        log "Создан config.yaml из шаблона."
    fi
    log "ВНИМАНИЕ: заполните $APP_DIR/config.yaml (токены, Chat ID, GEMINI_API_KEY)"
    log "Секреты можно положить в $APP_DIR/.env — они перекроют config.yaml."
elif grep -qE 'TELEGRAM_BOT_TOKEN:\s*""' "$APP_DIR/config.yaml"; then
    log "ВНИМАНИЕ: config.yaml есть, но токены пустые — заполните перед стартом."
fi

# ─────────────── 6. Инициализация БД ───────────────
log "Инициализация базы данных"
"$APP_DIR/.venv/bin/python" -c "from database import init_db; init_db(); print('DB OK')"

# ─────────────── 7. systemd-сервис ───────────────
log "Установка systemd-сервиса $SERVICE_NAME"
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Diar Car Buy AI
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

log "Готово. Статус сервиса:"
systemctl --no-pager status "$SERVICE_NAME" || true

cat <<NOTE

────────────────────────────────────────────────────────
ДАЛЬШЕ:
 1. Заполните ${APP_DIR}/config.yaml (или .env) секретами.
 2. Telegram-каналы (Telethon) при первом запуске требуют
    интерактивной авторизации по номеру телефона. Если включён
    источник 'telegram', выполните один раз вручную:
        cd ${APP_DIR} && .venv/bin/python main.py
    введите телефон/код, дождитесь создания diar_session.session,
    затем перезапустите сервис: systemctl restart ${SERVICE_NAME}
 3. Логи: journalctl -u ${SERVICE_NAME} -f
────────────────────────────────────────────────────────
NOTE
