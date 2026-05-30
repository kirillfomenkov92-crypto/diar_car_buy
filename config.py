"""
config.py — загрузка и хранение конфигурации Diar Car Buy AI.

Конфигурация читается из config.yaml, но значения PAUSED, MAX_PRICE и
MIN_DCB_SCORE могут изменяться в runtime через команды бота. Текущее
состояние хранится в словаре RUNTIME_CONFIG и доступно всем модулям.
"""

import logging
import yaml

CONFIG_PATH = "config.yaml"

# Изменяемая в runtime конфигурация. Заполняется при первом load_config().
RUNTIME_CONFIG = {}


def load_config():
    """
    Загрузить конфигурацию из config.yaml в RUNTIME_CONFIG.

    Загрузка выполняется один раз: при повторных вызовах возвращается уже
    изменённое в runtime состояние (чтобы не затирать /pause, /budget и т.п.).
    Возвращает словарь RUNTIME_CONFIG.
    """
    global RUNTIME_CONFIG
    if RUNTIME_CONFIG:
        return RUNTIME_CONFIG
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        RUNTIME_CONFIG.update(data)
    except Exception as e:
        logging.error(f"Ошибка загрузки config.yaml: {e}")
    return RUNTIME_CONFIG


def reload_config():
    """Принудительно перечитать config.yaml с диска, затерев runtime-значения."""
    global RUNTIME_CONFIG
    RUNTIME_CONFIG.clear()
    return load_config()


def set_value(key, value):
    """Изменить значение конфигурации в runtime (без записи на диск)."""
    cfg = load_config()
    cfg[key] = value
    return cfg
