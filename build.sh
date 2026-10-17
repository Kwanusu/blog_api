#!/usr/bin/env bash
# Render build script for blog_api.
# Render runs this on every deploy (see buildCommand in render.yaml). It installs dependencies,
# gathers static files for WhiteNoise, and applies database migrations.
set -o errexit   # stop on the first failing command
set -o nounset
set -o pipefail

echo "==> Installing Python dependencies"
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Collecting static files"
python manage.py collectstatic --no-input

echo "==> Applying database migrations"
python manage.py migrate --no-input

# Optional: create a superuser on the first deploy without shell access.
# Set DJANGO_SUPERUSER_EMAIL and DJANGO_SUPERUSER_PASSWORD in the Render dashboard, deploy once,
# then delete both variables. If the user already exists, the command fails and we just skip it.
if [[ -n "${DJANGO_SUPERUSER_EMAIL:-}" && -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]]; then
  echo "==> Creating superuser ${DJANGO_SUPERUSER_EMAIL}"
  python manage.py createsuperuser --no-input || echo "    superuser already exists, skipping"
fi

echo "==> Build finished"
