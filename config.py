# config.py — загрузка и хранение конфигурации Diar Car Buy AI v5.0.

import logging
import yaml

CONFIG_PATH = "config.yaml"

# Изменяемый в runtime словарь — заполняется при старте из config.yaml.
# Доступен из любого модуля без перезапуска.
RUNTIME_CONFIG = {}


def load_config() -> dict:
    """Прочитать config.yaml и заполнить RUNTIME_CONFIG. При повторном вызове возвращает текущее runtime-состояние."""
    global RUNTIME_CONFIG
    if RUNTIME_CONFIG:
        return RUNTIME_CONFIG
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        RUNTIME_CONFIG.update(data)
    except Exception as e:
        logging.error(f"Ошибка загрузки config.yaml: {e}")

    # Значения из .env перекрывают config.yaml (секреты не хранятся в репо)
    try:
        from dotenv import load_dotenv
        import os
        load_dotenv()
        for key in ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GEMINI_API_KEY", "GROQ_API_KEY", "DEEPSEEK_API_KEY"]:
            env_val = os.getenv(key)
            if env_val:
                RUNTIME_CONFIG[key] = env_val
    except ImportError:
        pass  # python-dotenv не установлен — работаем только с config.yaml

    return RUNTIME_CONFIG


def set_value(key: str, value) -> dict:
    """Изменить значение ключа в runtime без записи на диск."""
    cfg = load_config()
    cfg[key] = value
    return cfg
