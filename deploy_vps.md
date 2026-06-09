# Deploy Diar Car Buy AI v5.0 на VPS (Ubuntu 22.04)

> ⚠️ **ПРОЧТИ СНАЧАЛА — блокер переноса.**
> Парсеры Auto.ru / Drom / Avito берут куки антибота из **локального профиля
> браузера** (`browser_cookie3` читает Firefox/Chrome на этой машине). На голом
> VPS профиля браузера нет → куки пустые → Auto.ru/Avito отдадут 403/капчу.
> Перед боевым запуском на VPS нужно решить вопрос кук (см. раздел 7).

---

## 1. Система и зависимости

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip git
# Зависимости браузеров Playwright
sudo apt install -y libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
  libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
  libxfixes3 libxrandr2 libgbm1 libasound2
```

## 2. Клонирование и виртуальное окружение

```bash
cd /opt
sudo git clone https://github.com/kirillfomenkov92-crypto/diar_car_buy.git
sudo chown -R $USER:$USER diar_car_buy
cd diar_car_buy
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
# ВАЖНО: эти зависимости отсутствуют в requirements.txt — поставь вручную
pip install google-genai browser_cookie3 playwright-stealth
```

## 3. Браузеры Playwright

```bash
playwright install firefox chromium
playwright install-deps        # доустановит системные библиотеки
```

## 4. Конфигурация (секреты НЕ в git)

`config.yaml` в репозиторий не входит (и не должен). Создай его на VPS:

```bash
cp config.yaml.bak config.yaml   # если есть шаблон, иначе создай с нуля
nano config.yaml
```

Заполни как минимум:
- `TELEGRAM_BOT_TOKEN` — **выпусти НОВЫЙ токен** (старый скомпрометирован, см. отчёт)
- `TELEGRAM_CHAT_ID`, `ALLOWED_USER_IDS`
- `GROQ_API_KEY`, `GEMINI_API_KEY`
- `PROXY_*` (резидентный прокси для Avito)
- куки `AUTORU_COOKIES` / `DROM_COOKIES` / `AVITO_COOKIES`

Альтернатива для секретов — `.env` (перекрывает config.yaml):
```
TELEGRAM_BOT_TOKEN=...
GROQ_API_KEY=...
GEMINI_API_KEY=...
```

## 5. Проверка перед запуском

```bash
source .venv/bin/activate
python -c "from config import load_config; print('cfg keys:', len(load_config()))"
python -c "from database import init_db; init_db()"
python -c "from parsers.autoru import parse; print('autoru:', len(parse()))"
```
Если autoru/avito = 0 и в логах 403/капча — проблема кук/прокси (раздел 7).

## 6. systemd-юнит (автозапуск + рестарт)

`/etc/systemd/system/diar-car-buy.service`:

```ini
[Unit]
Description=Diar Car Buy AI v5.0
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=diar
WorkingDirectory=/opt/diar_car_buy
ExecStart=/opt/diar_car_buy/.venv/bin/python /opt/diar_car_buy/main.py
Restart=on-failure
RestartSec=15
# единственный экземпляр гарантируется и портом-замком 47921 в коде
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
sudo useradd -r -s /usr/sbin/nologin diar 2>/dev/null || true
sudo chown -R diar:diar /opt/diar_car_buy
sudo systemctl daemon-reload
sudo systemctl enable --now diar-car-buy
```

## 7. Проблема кук на VPS (обязательно решить)

`browser_cookie3` на VPS вернёт пусто. Варианты:

1. **Экспорт кук с десктопа** (быстро): на рабочей машине выгрузить куки
   auto.ru/drom.ru/avito.ru и положить значения в `config.yaml`
   (`AUTORU_COOKIES`, `DROM_COOKIES`, `AVITO_COOKIES`). Минус — куки протухают
   за дни, бот уже шлёт уведомление об устаревании (`_notify_stale_cookies`).
2. **Резидентный прокси для всех источников** (надёжнее): сейчас прокси
   подключён только к Avito Playwright. Для VPS стоит пустить через прокси и
   Auto.ru (curl_cffi `proxies=`) и Drom.
3. Поставить на VPS реальный Firefox-профиль и периодически прогревать его
   (сложно, хрупко) — не рекомендуется.

## 8. Мониторинг

```bash
sudo systemctl status diar-car-buy
journalctl -u diar-car-buy -f            # живой лог
tail -f /opt/diar_car_buy/agent.log      # файловый лог (ротация 5MB x3)
```

Встроенный watchdog шлёт тревогу в Telegram, если циклов не было 15+ минут.

## 9. Чек-лист после деплоя

- [ ] Новый Telegram-токен выпущен, старый отозван
- [ ] `config.yaml` создан, в git НЕ попал (`git status` чистый)
- [ ] 3 доп. зависимости поставлены (google-genai, browser_cookie3, playwright-stealth)
- [ ] `playwright install firefox chromium` выполнен
- [ ] Тестовый парс autoru/avito вернул > 0 (куки/прокси работают)
- [ ] systemd-юнит запущен, `Restart=on-failure` проверен (kill + автоподъём)
- [ ] Пришло тестовое уведомление обоим получателям
