"""
Fetches this week's economic calendar from ForexFactory's public JSON feed.
Blocks signals if a high-impact USD/XAU event is within NEWS_PAUSE_MINUTES.
"""
import requests
from datetime import datetime, timezone, timedelta
import config

_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_cache: list = []
_cache_fetched: datetime | None = None
_CACHE_TTL_HOURS = 3


def _fetch_calendar() -> list:
    global _cache, _cache_fetched
    now = datetime.now(timezone.utc)
    if _cache_fetched and (now - _cache_fetched).total_seconds() < _CACHE_TTL_HOURS * 3600:
        return _cache
    try:
        resp = requests.get(_CALENDAR_URL, timeout=10)
        resp.raise_for_status()
        _cache = resp.json()
        _cache_fetched = now
        return _cache
    except Exception as e:
        print(f"[News] Calendar fetch failed: {e}")
        return _cache  # return stale cache rather than crash


def is_news_window() -> tuple[bool, str]:
    """
    Returns (True, event_title) if we're inside a news pause window.
    Returns (False, '') otherwise.
    """
    events = _fetch_calendar()
    now    = datetime.now(timezone.utc)
    pause  = timedelta(minutes=config.NEWS_PAUSE_MINUTES)

    for ev in events:
        if ev.get("impact", "").lower() != "high":
            continue
        currency = ev.get("country", "").upper()
        if currency not in config.NEWS_CURRENCIES:
            continue
        try:
            ev_time = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
        except Exception:
            continue
        if abs(now - ev_time) <= pause:
            title = ev.get("title", "High-impact event")
            return True, f"{currency}: {title} @ {ev_time.strftime('%H:%M UTC')}"

    return False, ""
