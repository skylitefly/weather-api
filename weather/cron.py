import logging
import re
from calendar import monthrange
from datetime import datetime, timedelta, timezone

import requests
from django.core.cache import caches

logger = logging.getLogger(__name__)

METAR_TTL = 45 * 60
TAF_TTL = 7 * 3600
METAR_MAX_AGE = timedelta(minutes=90)
TAF_MAX_AGE = timedelta(hours=8)

OBS_TS_RE = re.compile(r"\b(\d{2})(\d{2})(\d{2})Z\b")
TAF_CYCLES = [0, 6, 12, 18]
NOAA_METAR_BASE = "https://tgftp.nws.noaa.gov/data/observations/metar/cycles/{hour:02d}Z.TXT"
NOAA_TAF_BASE = "https://tgftp.nws.noaa.gov/data/forecasts/taf/cycles/{hour:02d}Z.TXT"
TAF_MODIFIERS = frozenset({"TAF", "AMD", "COR", "RTD"})


def _latest_taf_cycle() -> int:
    utc_hour = datetime.now(timezone.utc).hour
    for hour in reversed(TAF_CYCLES):
        if utc_hour >= hour:
            return hour
    return 18


def _parse_metars(text: str) -> dict[str, str]:
    result = {}
    for block in text.split("\n\n"):
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        metar_line = lines[1].strip()
        parts = metar_line.split()
        if parts and len(parts[0]) == 4:
            result[parts[0].upper()] = metar_line
    return result


def _parse_tafs(text: str) -> dict[str, str]:
    result = {}
    for block in text.split("\n\n"):
        lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
        if len(lines) < 2:
            continue

        taf_lines = lines[1:]
        icao = None
        for line in taf_lines:
            for word in line.split():
                if word.upper() in TAF_MODIFIERS:
                    continue
                if len(word) == 4 and word.isalpha():
                    icao = word.upper()
                break
            if icao:
                break

        if icao is not None:
            result[icao] = "\n".join(taf_lines)
    return result


def parse_obs_datetime(raw: str) -> datetime | None:
    match = OBS_TS_RE.search(raw)
    if not match:
        return None

    day, hour, minute = int(match.group(1)), int(match.group(2)), int(match.group(3))
    now = datetime.now(timezone.utc)
    try:
        obs = now.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError:
        return None

    if obs > now + timedelta(hours=1):
        previous_month = now.month - 1 if now.month > 1 else 12
        previous_year = now.year if now.month > 1 else now.year - 1
        if day > monthrange(previous_year, previous_month)[1]:
            return None
        try:
            obs = obs.replace(year=previous_year, month=previous_month)
        except ValueError:
            return None
    return obs


def is_metar_fresh(raw: str, max_age: timedelta = METAR_MAX_AGE) -> bool:
    obs = parse_obs_datetime(raw)
    return True if obs is None else datetime.now(timezone.utc) - obs <= max_age


def is_taf_fresh(raw: str, max_age: timedelta = TAF_MAX_AGE) -> bool:
    obs = parse_obs_datetime(raw)
    return True if obs is None else datetime.now(timezone.utc) - obs <= max_age


def _previous_taf_cycles(current_hour: int) -> list[int]:
    index = TAF_CYCLES.index(current_hour)
    return [TAF_CYCLES[(index - offset) % len(TAF_CYCLES)] for offset in range(1, len(TAF_CYCLES))]


def _backfill_missing_tafs(weather_cache, missing: set[str], tried_hour: int, now: datetime) -> None:
    remaining = set(missing)
    for hour in _previous_taf_cycles(tried_hour):
        if not remaining:
            break
        try:
            response = requests.get(NOAA_TAF_BASE.format(hour=hour), timeout=30)
            if response.status_code != 200:
                continue
            tafs = _parse_tafs(response.text)
            found = {
                icao: raw
                for icao, raw in tafs.items()
                if icao in remaining and ((obs := parse_obs_datetime(raw)) is None or now - obs <= TAF_MAX_AGE)
            }
            if found:
                weather_cache.set_many({f"noaa:taf:{icao}": raw for icao, raw in found.items()}, timeout=TAF_TTL)
                remaining -= found.keys()
                logger.info("NOAA TAF backfill %02dZ: found %d, still missing %d", hour, len(found), len(remaining))
        except Exception:
            logger.exception("NOAA TAF backfill failed hour=%02dZ", hour)


def fetch_and_cache_all_metar_taf():
    weather_cache = caches["weather"]
    utc_hour = datetime.now(timezone.utc).hour
    now = datetime.now(timezone.utc)

    metar_icaos: set[str] = set()
    try:
        response = requests.get(NOAA_METAR_BASE.format(hour=utc_hour), timeout=30)
        if response.status_code == 200:
            metars = _parse_metars(response.text)
            fresh_metars = {
                icao: raw
                for icao, raw in metars.items()
                if (obs := parse_obs_datetime(raw)) is None or now - obs <= METAR_MAX_AGE
            }
            if fresh_metars:
                weather_cache.set_many({f"noaa:metar:{icao}": raw for icao, raw in fresh_metars.items()}, timeout=METAR_TTL)
                metar_icaos = set(fresh_metars.keys())
            logger.info("NOAA METAR cached: %d airports (%02dZ)", len(fresh_metars), utc_hour)
    except Exception:
        logger.exception("NOAA METAR fetch failed hour=%02dZ", utc_hour)

    taf_hour = _latest_taf_cycle()
    covered_tafs: set[str] = set()
    try:
        response = requests.get(NOAA_TAF_BASE.format(hour=taf_hour), timeout=30)
        if response.status_code == 200:
            tafs = _parse_tafs(response.text)
            fresh_tafs = {
                icao: raw
                for icao, raw in tafs.items()
                if (obs := parse_obs_datetime(raw)) is None or now - obs <= TAF_MAX_AGE
            }
            if fresh_tafs:
                weather_cache.set_many({f"noaa:taf:{icao}": raw for icao, raw in fresh_tafs.items()}, timeout=TAF_TTL)
                covered_tafs = set(fresh_tafs.keys())
            logger.info("NOAA TAF cached: %d airports (%02dZ)", len(fresh_tafs), taf_hour)
    except Exception:
        logger.exception("NOAA TAF fetch failed hour=%02dZ", taf_hour)

    missing = metar_icaos - covered_tafs
    if missing:
        _backfill_missing_tafs(weather_cache, missing, taf_hour, now)
