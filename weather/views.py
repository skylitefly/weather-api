from calendar import monthrange
from datetime import datetime, timedelta
import re

import requests
from django.conf import settings
from django.core.cache import caches
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

OBS_TS_RE = re.compile(r"\b(\d{2})(\d{2})(\d{2})Z\b")


def _normalize_icao(icao: str) -> str:
    return (icao or "").strip().upper()


def _parse_obs_dt(raw: str) -> datetime | None:
    match = OBS_TS_RE.search(raw)
    if not match:
        return None

    day, hour, minute = int(match.group(1)), int(match.group(2)), int(match.group(3))
    now = timezone.now()
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


def _is_metar_fresh(raw: str, max_age_min: int = 90) -> bool:
    obs = _parse_obs_dt(raw)
    return True if obs is None else timezone.now() - obs <= timedelta(minutes=max_age_min)


def _is_taf_fresh(raw: str, max_age_hours: int = 8) -> bool:
    obs = _parse_obs_dt(raw)
    return True if obs is None else timezone.now() - obs <= timedelta(hours=max_age_hours)


def _calculate_metar_taf_ttl() -> int:
    now = datetime.now()
    minutes_to_next = 30 - now.minute if now.minute < 30 else 60 - now.minute
    seconds_to_next = minutes_to_next * 60 - now.second
    return min(15 * 60, seconds_to_next)


def _fetch_avwx_raw(kind: str, icao: str) -> str | None:
    token = settings.AVWX_API_TOKEN
    if not token:
        return None

    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{settings.AVWX_API_BASE_URL}/{kind}/{icao}", headers=headers, timeout=10)
    response.raise_for_status()
    return response.json().get("raw")


def fetch_metar_taf(icao: str) -> dict:
    icao = _normalize_icao(icao)
    if len(icao) != 4 or not icao.isalnum():
        return {"success": False, "error": "Invalid ICAO code"}

    weather_cache = caches["weather"]
    metar = weather_cache.get(f"noaa:metar:{icao}")
    taf = weather_cache.get(f"noaa:taf:{icao}")

    if metar is not None and not _is_metar_fresh(metar):
        metar = None
    if taf is not None and not _is_taf_fresh(taf):
        taf = None

    if metar is not None and taf is not None:
        return {"success": True, "data": {"airport": icao, "metar": metar, "taf": taf}}

    try:
        ttl = _calculate_metar_taf_ttl()
        if metar is None:
            raw = _fetch_avwx_raw("metar", icao)
            if raw:
                metar = raw
                weather_cache.set(f"noaa:metar:{icao}", metar, timeout=ttl)

        if taf is None:
            raw = _fetch_avwx_raw("taf", icao)
            if raw:
                taf = raw
                weather_cache.set(f"noaa:taf:{icao}", taf, timeout=ttl)
    except Exception as exc:
        if metar is None and taf is None:
            return {"success": False, "error": str(exc)}

    return {
        "success": True,
        "data": {
            "airport": icao,
            "metar": metar or "暂无数据",
            "taf": taf or "暂无数据",
        },
    }


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "ok"})


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def get_weather_by_icao(request, airport_icao):
    result = fetch_metar_taf(airport_icao)
    response_status = status.HTTP_200_OK if result.get("success") else status.HTTP_400_BAD_REQUEST
    return Response(result, status=response_status)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def get_metar_by_icao(request, airport_icao):
    result = fetch_metar_taf(airport_icao)
    if not result.get("success"):
        return Response(result, status=status.HTTP_400_BAD_REQUEST)
    return Response({"success": True, "data": {"airport": result["data"]["airport"], "metar": result["data"]["metar"]}})


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def get_taf_by_icao(request, airport_icao):
    result = fetch_metar_taf(airport_icao)
    if not result.get("success"):
        return Response(result, status=status.HTTP_400_BAD_REQUEST)
    return Response({"success": True, "data": {"airport": result["data"]["airport"], "taf": result["data"]["taf"]}})
