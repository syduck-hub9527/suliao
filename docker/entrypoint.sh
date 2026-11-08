#!/bin/sh
# 容器启动时依次执行：升级数据库结构 → 确保有管理员账号 → 启动网站
set -e

mkdir -p "${DJANGO_DATA_DIR:-/data}/media"

python manage.py migrate --noinput
python manage.py ensure_admin

exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-2}" \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
