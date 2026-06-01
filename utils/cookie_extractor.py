"""utils/cookie_extractor.py — экспорт куки из Firefox/Chrome и обновление config.yaml."""

import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml

CONFIG_PATH = Path("config.yaml")

DOMAINS = {
    "avito":  ".avito.ru",
    "drom":   ".drom.ru",
    "autoru": ".auto.ru",
}


def _load_cookiejar(domain: str):
    """Пробует Firefox, затем Chrome; возвращает первый успешный CookieJar."""
    import browser_cookie3
    for browser_name, loader in [
        ("Firefox", browser_cookie3.firefox),
        ("Chrome",  browser_cookie3.chrome),
    ]:
        try:
            cj = loader(domain_name=domain)
            logging.info(f"Куки загружены из {browser_name} для {domain}")
            return cj
        except Exception as e:
            logging.debug(f"{browser_name} недоступен для {domain}: {e}")
    return None


def extract_cookies_for_domain(domain: str) -> dict:
    """Извлекает куки из Firefox или Chrome для указанного домена."""
    try:
        import browser_cookie3  # noqa: F401 — проверка наличия пакета
        cj = _load_cookiejar(domain)
        if cj is None:
            logging.error(f"Ни Firefox, ни Chrome не доступны для {domain}")
            return {}
        cookies = {}
        for cookie in cj:
            if domain.lstrip(".") in cookie.domain:
                cookies[cookie.name] = cookie.value
        logging.info(f"Извлечено {len(cookies)} куки для {domain}")
        return cookies
    except Exception as e:
        logging.error(f"Ошибка извлечения куки для {domain}: {e}")
        return {}


def extract_all() -> dict:
    """Извлекает куки для всех сайтов из Firefox или Chrome."""
    result = {}
    for name, domain in DOMAINS.items():
        cookies = extract_cookies_for_domain(domain)
        result[name] = cookies
        if cookies:
            print(f"  OK {name}: найдено {len(cookies)} куки")
        else:
            print(f"  WARN {name}: куки не найдены (возможно не авторизован)")
    return result


def update_config(all_cookies: dict) -> bool:
    """Обновляет AVITO_COOKIES, DROM_COOKIES, AUTORU_COOKIES в config.yaml."""
    if not CONFIG_PATH.exists():
        logging.error("config.yaml не найден")
        return False

    backup_path = CONFIG_PATH.with_suffix(".yaml.bak")
    backup_path.write_text(CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"  Резервная копия: {backup_path}")

    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    if all_cookies.get("avito"):
        avito = all_cookies["avito"]
        config["AVITO_COOKIES"] = {
            "user_id":             avito.get("user_id", ""),
            "u":                   avito.get("u", ""),
            "sess2":               avito.get("sess2", ""),
            "buyer_laas_location": avito.get("buyer_laas_location", ""),
            "abp":                 avito.get("abp", ""),
            "lox":                 avito.get("lox", ""),
        }

    if all_cookies.get("drom"):
        config["DROM_COOKIES"] = {k: v for k, v in all_cookies["drom"].items() if k}

    if all_cookies.get("autoru"):
        autoru = all_cookies["autoru"]
        config["AUTORU_COOKIES"] = {
            "autoru_sid": autoru.get("autoru_sid", ""),
            "suid":       autoru.get("suid", ""),
            "csrftoken":  autoru.get("csrf_token", autoru.get("csrftoken", "")),
            "yandexuid":  autoru.get("yandexuid", ""),
            "crookie":    autoru.get("crookie", ""),
            "cmtchd":     autoru.get("cmtchd", ""),
            "_yasc":      autoru.get("_yasc", ""),
        }

    config["COOKIES_UPDATED_AT"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

    print("  config.yaml обновлён")
    return True


def load_cookies_into_session(session, source: str):
    """Загружает куки из config.yaml в requests.Session.

    Args:
        session: requests.Session
        source: "avito", "drom" или "autoru"
    """
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        key_map = {
            "avito":  "AVITO_COOKIES",
            "drom":   "DROM_COOKIES",
            "autoru": "AUTORU_COOKIES",
        }
        cookies = config.get(key_map.get(source, ""), {})
        if not isinstance(cookies, dict) or not cookies:
            return session

        domain_map = {
            "avito":  ".avito.ru",
            "drom":   ".drom.ru",
            "autoru": ".auto.ru",
        }
        domain = domain_map.get(source, "")
        for name, value in cookies.items():
            if value:
                session.cookies.set(name, str(value), domain=domain)

        logging.info(f"[{source}] Загружено {len(cookies)} куки из config.yaml")
    except Exception as e:
        logging.warning(f"load_cookies_into_session({source}): {e}")

    return session


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("Diar Car Buy AI — экспорт куки из Firefox / Chrome")
    print("-" * 40)
    print("Убедись что браузер закрыт перед запуском!\n")

    print("Извлекаю куки...")
    all_cookies = extract_all()

    print("\nОбновляю config.yaml...")
    success = update_config(all_cookies)

    print("\n" + "-" * 40)
    if success:
        print("Готово! Куки обновлены в config.yaml")
        print("Парсеры теперь будут работать от твоего аккаунта")
        print("Повторяй раз в 2 недели когда куки протухнут")
    else:
        print("Не удалось обновить config.yaml")
