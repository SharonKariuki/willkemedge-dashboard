"""Development settings — DEBUG on, permissive CORS, local DB."""
from decouple import config

from .base import *  # noqa: F401,F403

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

# Use Postgres if DATABASE_URL is set, otherwise fall back to SQLite for quick start.
DATABASE_URL = config("DATABASE_URL", default="")
if DATABASE_URL:
    import dj_database_url  # type: ignore

    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=600)}

CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# Email to console in dev
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Disable throttling in dev/test so tests don't get rate-limited
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []  # noqa: F405
