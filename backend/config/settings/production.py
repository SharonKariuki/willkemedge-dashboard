"""Production settings — DEBUG off, strict security, Postgres required."""
import dj_database_url
from decouple import Csv, config

from .base import *  # noqa: F401,F403

DEBUG = False

SECRET_KEY = config("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", cast=Csv())

DATABASE_URL = config("DATABASE_URL", default="")
if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(DATABASE_URL, conn_max_age=600, ssl_require=True)
    }
else:
    raise RuntimeError(
        "DATABASE_URL environment variable is required in production. "
        "Get it from your Render PostgreSQL dashboard → External Database URL."
    )

CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", default="", cast=Csv())

# Security headers
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Static files served by WhiteNoise on Render
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")  # noqa: F405

# Disable throttling in test if needed
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = (  # noqa: F405
    "rest_framework.throttling.AnonRateThrottle",
    "rest_framework.throttling.UserRateThrottle",
)

# Email — SMTP (Gmail by default, configured via env vars in base.py)
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

# Run Celery tasks synchronously in production until Render Redis + a Celery
# worker are provisioned. Receipts/notifications fire inside the web request,
# adding ~1–2 seconds per payment-creation call but guaranteeing delivery.
# Switch to False once REDIS_URL points to a real broker and a worker process
# is running.
CELERY_TASK_ALWAYS_EAGER = config("CELERY_TASK_ALWAYS_EAGER", default=True, cast=bool)
CELERY_TASK_EAGER_PROPAGATES = False
