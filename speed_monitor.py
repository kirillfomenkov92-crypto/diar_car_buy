# speed_monitor.py — мониторинг скорости появления объявлений.
# Ключевое конкурентное преимущество: видеть объявление раньше рынка.

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging


def calculate_listing_age_minutes(published_at: str) -> int:
    """Вычислить сколько минут назад появилось объявление."""
    try:
        if not published_at or published_at == "999":
            return 999
        pub_str = str(published_at).strip()
        pub_time = None

        # Русский относительный формат: "2 часа назад", "30 минут назад"
        ru_match = re.search(r"(\d+)\s*(минут|минуты|минуту|час|часа|часов|день|дня|дней)", pub_str)
        if ru_match:
            n, unit = int(ru_match.group(1)), ru_match.group(2)
            if "мин" in unit:
                return n
            elif "час" in unit:
                return n * 60
            elif "ден" in unit or "дн" in unit or "дня" in unit or "день" in unit:
                return n * 1440
        if any(w in pub_str.lower() for w in ("только что", "сейчас", "недавно")):
            return 1
        if "вчера" in pub_str.lower():
            return 1440

        # RFC 2822 / RSS формат: "Mon, 01 Jun 2026 14:32:00 +0300"
        try:
            pub_time = parsedate_to_datetime(pub_str)
        except Exception:
            pass

        if pub_time is None and pub_str.isdigit():
            # Unix timestamp (VK API)
            pub_time = datetime.fromtimestamp(int(pub_str), tz=timezone.utc)

        if pub_time is None:
            # ISO формат: "2024-01-15T23:30:00" или с Z
            pub_time = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            if pub_time.tzinfo is None:
                pub_time = pub_time.replace(tzinfo=timezone.utc)

        now = datetime.now(tz=timezone.utc)
        delta = now - pub_time
        return max(0, int(delta.total_seconds() / 60))
    except Exception as e:
        logging.debug(f"speed_monitor: не удалось разобрать дату '{published_at}': {e}")
        return 999


def get_urgency_label(age_minutes: int) -> str:
    """Вернуть метку срочности по возрасту объявления в минутах."""
    if age_minutes <= 15:
        return "🔴 ТОЛЬКО ЧТО — ты первый!"
    elif age_minutes <= 60:
        return f"🟡 {age_minutes} минут назад — торопись"
    elif age_minutes <= 360:
        return f"🟢 {age_minutes // 60}ч назад — ещё актуально"
    else:
        hours = age_minutes // 60
        return f"⚪ {hours}ч назад"
