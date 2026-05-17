#!/usr/bin/env bash
# Render start script for the web service.
# Workers tuned for Render Starter (0.5 CPU / 512 MB); raise on larger plans.
set -o errexit

exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers ${WEB_CONCURRENCY:-3} \
    --threads ${WEB_THREADS:-2} \
    --timeout 60 \
    --access-logfile - \
    --error-logfile -
