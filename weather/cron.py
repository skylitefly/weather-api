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


def _backfill_missing_tafs(weather_cache, missing: set[str], tried_hour: int, now: datetime, emit=None) -> dict:
    summary = {"tried_hours": [], "found": 0, "remaining": len(missing), "errors": []}
    remaining = set(missing)
    for hour in _previous_taf_cycles(tried_hour):
        if not remaining:
            break
        summary["tried_hours"].append(hour)
        if emit:
            emit(f"Backfilling missing TAFs from NOAA {hour:02d}Z cycle: remaining={len(remaining)}")
        try:
            response = requests.get(NOAA_TAF_BASE.format(hour=hour), timeout=30)
            if emit:
                emit(f"NOAA TAF backfill {hour:02d}Z HTTP status={response.status_code}")
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
                summary["found"] += len(found)
                summary["remaining"] = len(remaining)
                logger.info("NOAA TAF backfill %02dZ: found %d, still missing %d", hour, len(found), len(remaining))
                if emit:
                    emit(f"NOAA TAF backfill {hour:02d}Z cached={len(found)} remaining={len(remaining)}")
        except Exception:
            logger.exception("NOAA TAF backfill failed hour=%02dZ", hour)
            summary["errors"].append(hour)
            if emit:
                emit(f"NOAA TAF backfill {hour:02d}Z failed; see exception log")
    return summary


def fetch_and_cache_all_metar_taf(emit=None):
    weather_cache = caches["weather"]
    utc_hour = datetime.now(timezone.utc).hour
    now = datetime.now(timezone.utc)
    summary = {
        "utc_hour": utc_hour,
        "metar": {"status": None, "parsed": 0, "fresh": 0, "cached": 0, "error": False},
        "taf": {"cycle": None, "status": None, "parsed": 0, "fresh": 0, "cached": 0, "error": False},
        "backfill": None,
    }

    metar_icaos: set[str] = set()
    try:
        if emit:
            emit(f"Fetching NOAA METAR cycle {utc_hour:02d}Z")
        response = requests.get(NOAA_METAR_BASE.format(hour=utc_hour), timeout=30)
        summary["metar"]["status"] = response.status_code
        if emit:
            emit(f"NOAA METAR cycle {utc_hour:02d}Z HTTP status={response.status_code} bytes={len(response.content)}")
        if response.status_code == 200:
            metars = _parse_metars(response.text)
            summary["metar"]["parsed"] = len(metars)
            fresh_metars = {
                icao: raw
                for icao, raw in metars.items()
                if (obs := parse_obs_datetime(raw)) is None or now - obs <= METAR_MAX_AGE
            }
            summary["metar"]["fresh"] = len(fresh_metars)
            if fresh_metars:
                weather_cache.set_many({f"noaa:metar:{icao}": raw for icao, raw in fresh_metars.items()}, timeout=METAR_TTL)
                metar_icaos = set(fresh_metars.keys())
                summary["metar"]["cached"] = len(fresh_metars)
            logger.info("NOAA METAR cached: %d airports (%02dZ)", len(fresh_metars), utc_hour)
            if emit:
                emit(f"NOAA METAR parsed={len(metars)} fresh={len(fresh_metars)} cached={summary['metar']['cached']}")
    except Exception:
        logger.exception("NOAA METAR fetch failed hour=%02dZ", utc_hour)
        summary["metar"]["error"] = True
        if emit:
            emit(f"NOAA METAR cycle {utc_hour:02d}Z failed; see exception log")

    taf_hour = _latest_taf_cycle()
    summary["taf"]["cycle"] = taf_hour
    covered_tafs: set[str] = set()
    try:
        if emit:
            emit(f"Fetching NOAA TAF cycle {taf_hour:02d}Z")
        response = requests.get(NOAA_TAF_BASE.format(hour=taf_hour), timeout=30)
        summary["taf"]["status"] = response.status_code
        if emit:
            emit(f"NOAA TAF cycle {taf_hour:02d}Z HTTP status={response.status_code} bytes={len(response.content)}")
        if response.status_code == 200:
            tafs = _parse_tafs(response.text)
            summary["taf"]["parsed"] = len(tafs)
            fresh_tafs = {
                icao: raw
                for icao, raw in tafs.items()
                if (obs := parse_obs_datetime(raw)) is None or now - obs <= TAF_MAX_AGE
            }
            summary["taf"]["fresh"] = len(fresh_tafs)
            if fresh_tafs:
                weather_cache.set_many({f"noaa:taf:{icao}": raw for icao, raw in fresh_tafs.items()}, timeout=TAF_TTL)
                covered_tafs = set(fresh_tafs.keys())
                summary["taf"]["cached"] = len(fresh_tafs)
            logger.info("NOAA TAF cached: %d airports (%02dZ)", len(fresh_tafs), taf_hour)
            if emit:
                emit(f"NOAA TAF parsed={len(tafs)} fresh={len(fresh_tafs)} cached={summary['taf']['cached']}")
    except Exception:
        logger.exception("NOAA TAF fetch failed hour=%02dZ", taf_hour)
        summary["taf"]["error"] = True
        if emit:
            emit(f"NOAA TAF cycle {taf_hour:02d}Z failed; see exception log")

    missing = metar_icaos - covered_tafs
    if emit:
        emit(f"TAF coverage check: metar_airports={len(metar_icaos)} covered_tafs={len(covered_tafs)} missing={len(missing)}")
    if missing:
        summary["backfill"] = _backfill_missing_tafs(weather_cache, missing, taf_hour, now, emit=emit)
    return summary
