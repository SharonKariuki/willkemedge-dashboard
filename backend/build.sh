#!/usr/bin/env bash
# Render build script — runs on every deploy.
# Installs dependencies, collects static files, and applies migrations.
set -o errexit

pip install --upgrade pip
pip install -r requirements/prod.txt

python manage.py collectstatic --noinput
python manage.py migrate --noinput
