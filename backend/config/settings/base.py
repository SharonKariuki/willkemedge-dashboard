"""
Base Django settings for willkemedge-dashboard.
Shared across all environments. Environment-specific overrides live in
development.py and production.py.
"""
from datetime import timedelta
from pathlib import Path

from decouple import Csv, config

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = config(
    "DJANGO_SECRET_KEY",
    default="insecure-dev-key-change-me-at-least-32-bytes-long-aaaaaaaa",
)
DEBUG = config("DJANGO_DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_celery_beat",
]

LOCAL_APPS = [
    "apps.accounts",
    "apps.buildings",
    "apps.tenants",
    "apps.payments",
    "apps.dashboard",
    "apps.expenses",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.accounts.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Database (overridden per environment)
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# DRF + JWT
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "20/minute",
        "user": "120/minute",
        "coop_ipn": "120/minute",
    },
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
    ),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# ---------------------------------------------------------------------------
# I18n / TZ
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static / Media
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# CORS (overridden per environment)
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS: list[str] = []
CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = config("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = config("REDIS_URL", default="redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Africa/Nairobi"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# ---------------------------------------------------------------------------
# Payment reference parsing
# ---------------------------------------------------------------------------
# Paybill account-number prefix: tenants pay "<prefix>#<house number>"
# (e.g. "90290#A12"). The IPN narration parser strips this prefix to recover the
# bare house number, which must equal a Unit.label. Override via env if it changes.
MPESA_ACCOUNT_PREFIX = config("MPESA_ACCOUNT_PREFIX", default="90290")

# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
AT_API_KEY = config("AT_API_KEY", default="")
AT_USERNAME = config("AT_USERNAME", default="sandbox")
AT_SENDER_ID = config("AT_SENDER_ID", default="")

# Email — SMTP (Gmail by default; swap host/port for any other SMTP provider)
EMAIL_BACKEND = config(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = config("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="Wilkem Ventures <wilkem.ventures@gmail.com>")

FRONTEND_URL = config("FRONTEND_URL", default="http://localhost:5173")

# ---------------------------------------------------------------------------
# Content-Security-Policy
# ---------------------------------------------------------------------------
# Extra origins (beyond 'self') allowed for connect-src (XHR/fetch/WebSocket).
# In dev we include the local API; in production set CSP_CONNECT_SRC to the
# real API origin(s) — do NOT leave localhost in here.
CSP_CONNECT_SRC = config(
    "CSP_CONNECT_SRC",
    default="" if not DEBUG else "http://localhost:8000",
    cast=Csv(),
)

# ---------------------------------------------------------------------------
# Bank webhook
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Co-operative Bank IPN (Instant Payment Notification)
# ---------------------------------------------------------------------------
# Bearer token Co-op presents on each IPN POST (Authorization: Bearer <token>).
# Generate a strong random value and share it with the bank; keep it secret.
COOP_IPN_TOKEN = config("COOP_IPN_TOKEN", default="")
# The institution account (behind Paybill 400222) credits are expected on.
# Credits to any other AcctNo are ignored, not booked as rent.
COOP_ACCOUNT_NUMBER = config("COOP_ACCOUNT_NUMBER", default="")
# Optional defence-in-depth: comma-separated source IPs Co-op posts from.
# Empty = allow all (until Co-op shares their range).
COOP_IPN_ALLOWED_IPS = config("COOP_IPN_ALLOWED_IPS", default="", cast=Csv())
# Dev-only escape hatch: skip bearer auth when DEBUG and this is explicitly set.
ALLOW_INSECURE_COOP_IPN = config("ALLOW_INSECURE_COOP_IPN", default=False, cast=bool)
# Admin alerted (SMS + email) when an IPN credit can't be auto-matched/errors.
ADMIN_ALERT_PHONE = config("ADMIN_ALERT_PHONE", default="")
ADMIN_ALERT_EMAIL = config("ADMIN_ALERT_EMAIL", default="")
# Authorising director (Dr. Osoro) — alerted to authorize bank reversals.
# Falls back to ADMIN_ALERT_* if unset.
DIRECTOR_ALERT_PHONE = config("DIRECTOR_ALERT_PHONE", default="")
DIRECTOR_ALERT_EMAIL = config("DIRECTOR_ALERT_EMAIL", default="")
