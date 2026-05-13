import os
from pathlib import Path

from corsheaders.defaults import default_headers

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("SKYLITE_DJANGO_SECRET_KEY", "django-insecure-weather-api")
DEBUG = os.getenv("SKYLITE_DJANGO_DEBUG", "false") == "true"
ALLOWED_HOSTS = os.getenv(
    "SKYLITE_DJANGO_ALLOWED_HOSTS",
    "weather.api.skylitefly.com,localhost,127.0.0.1",
).split(",")

INSTALLED_APPS = [
    "corsheaders",
    "rest_framework",
    "django_crontab",
    "weather.apps.WeatherConfig",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "weather_service.urls"
WSGI_APPLICATION = "weather_service.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "en-us"
STATIC_URL = "static/"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

redis_location = os.getenv("SKYLITE_REDIS_WEATHER_LOCATION")
if redis_location:
    CACHES = {
        "weather": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": redis_location,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "PASSWORD": os.getenv("SKYLITE_REDIS_WEATHER_PASSWORD", None) or None,
                "SOCKET_CONNECT_TIMEOUT": 5,
                "SOCKET_TIMEOUT": 5,
            },
            "KEY_PREFIX": os.getenv("SKYLITE_REDIS_WEATHER_KEY_PREFIX", "weather"),
            "TIMEOUT": 4500,
        }
    }
else:
    CACHES = {"weather": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CACHES["default"] = CACHES["weather"]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "UNAUTHENTICATED_USER": None,
}

CORS_ORIGIN_ALLOW_ALL = True
CORS_ALLOW_HEADERS = list(default_headers)

AVWX_API_TOKEN = os.getenv("SKYLITE_AVWX_TOKEN", "")
AVWX_API_BASE_URL = os.getenv("SKYLITE_AVWX_BASE_URL", "https://avwx.rest/api")

CRONJOBS = [
    ("*/5 * * * *", "weather.cron.fetch_and_cache_all_metar_taf"),
]
