"""杂项工具函数。"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytz

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / ".github" / "cache"
SOURCE_CONFIG_PATH = CACHE_DIR / "source_config.json"
PROCESSED_URLS_PATH = CACHE_DIR / "processed_urls.json"

CST = pytz.timezone("Asia/Shanghai")


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_source_config() -> dict:
    return load_json(SOURCE_CONFIG_PATH)


def load_processed_urls() -> set:
    data = load_json(PROCESSED_URLS_PATH)
    if isinstance(data, dict):
        return set(data.get("urls", []))
    return set(data if isinstance(data, list) else [])


def save_processed_urls(urls: set) -> None:
    payload = {
        "updated": datetime.now(CST).isoformat(),
        "count": len(urls),
        "urls": sorted(urls),
    }
    save_json(PROCESSED_URLS_PATH, payload)


def week_boundaries(days_back: int = 7) -> tuple[datetime, datetime]:
    """Return (week_ago, now) in CST, both timezone-aware."""
    now = datetime.now(CST)
    ago = now - timedelta(days=days_back)
    return ago, now


def parse_feed_date(entry) -> Optional[datetime]:
    """Robustly extract a datetime from a feedparser entry, returning UTC-aware datetime or None."""
    for attr in ("published_parsed", "updated_parsed"):
        tp = getattr(entry, attr, None)
        if tp is not None:
            from time import mktime

            return datetime.fromtimestamp(mktime(tp), tz=timezone.utc)
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                from dateutil.parser import parse as dt_parse

                return dt_parse(raw).astimezone(timezone.utc)
            except Exception:
                pass
    return None


def clean_html(raw: str) -> str:
    """Strip HTML tags, collapse whitespace."""
    clean = re.sub(r"<[^>]+>", " ", raw)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def sanitize_filename(name: str) -> str:
    return re.sub(r"[^\w\-_.]", "_", name)


def env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key, str(default)).lower()
    return val in ("1", "true", "yes", "on")
