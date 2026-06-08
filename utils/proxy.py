# utils/proxy.py — резидентный прокси (pool.proxy.market) для всех парсеров.
# Настройки в config.yaml: PROXY_ENABLED / PROXY_HOST / PROXY_PORT /
# PROXY_PORT_MAX / PROXY_LOGIN / PROXY_PASSWORD. Порт выбирается случайно из
# диапазона PROXY_PORT..PROXY_PORT_MAX — это ротирует IP пула на каждый запуск.
#
# ВАЖНО: логин/пароль в логи НЕ попадают (логируем только host:port).

import logging
import random

from config import RUNTIME_CONFIG


def _proxy_parts():
    """(host, port, login, password) или None, если прокси выключен/не настроен."""
    if not RUNTIME_CONFIG.get("PROXY_ENABLED"):
        return None
    host = RUNTIME_CONFIG.get("PROXY_HOST")
    login = RUNTIME_CONFIG.get("PROXY_LOGIN")
    password = RUNTIME_CONFIG.get("PROXY_PASSWORD")
    if not (host and login and password):
        logging.warning("Proxy: PROXY_ENABLED, но настройки неполные — работаем без прокси")
        return None
    port_min = int(RUNTIME_CONFIG.get("PROXY_PORT", 10000))
    port_max = int(RUNTIME_CONFIG.get("PROXY_PORT_MAX", port_min))
    port = random.randint(port_min, port_max) if port_max > port_min else port_min
    return host, port, login, password


def playwright_proxy():
    """Конфиг прокси для Playwright (.launch(proxy=...)) или None."""
    parts = _proxy_parts()
    if not parts:
        return None
    host, port, login, password = parts
    logging.info(f"Proxy (Playwright): {host}:{port}")
    return {"server": f"http://{host}:{port}", "username": login, "password": password}


def curl_proxies():
    """Конфиг прокси для curl_cffi / requests (proxies=...) или None.

    Формат {'http': url, 'https': url}, креды зашиты в URL — не логируется.
    """
    parts = _proxy_parts()
    if not parts:
        return None
    host, port, login, password = parts
    logging.info(f"Proxy (curl): {host}:{port}")
    url = f"http://{login}:{password}@{host}:{port}"
    return {"http": url, "https": url}
