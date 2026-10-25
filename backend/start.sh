#!/usr/bin/env bash
# Render start script for the web service.
# Workers tuned for Render Starter (0.5 CPU / 512 MB); raise on larger plans.
# --timeout 180: emailing statements to a whole property renders a PDF and
# sends an email per tenant inside one request; at 60s the worker could be
# killed mid-batch, leaving half the tenants sent and the office retrying.
set -o errexit

exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers ${WEB_CONCURRENCY:-3} \
    --threads ${WEB_THREADS:-2} \
    --timeout 180 \
    --access-logfile - \
    --error-logfile -
