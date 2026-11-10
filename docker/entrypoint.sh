#!/bin/sh
# 网站容器启动时依次执行：升级数据库结构 → 导入知识内容 → 启动网站
set -e

mkdir -p "${DJANGO_DATA_DIR:-/data}/media"

python manage.py migrate --noinput
python manage.py load_content

exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-2}" \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
