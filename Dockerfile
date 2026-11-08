# 基础镜像可以在 .env 里用 PYTHON_IMAGE 换成镜像站地址（官方地址下载不了时用）
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_DATA_DIR=/data

# 国内服务器默认用阿里云的 Python 软件源，下载快；需要时可在 .env 里改 PIP_INDEX_URL
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

WORKDIR /app

COPY requirements.txt .
RUN pip install --index-url "${PIP_INDEX_URL}" -r requirements.txt

COPY . .

# 打包后台用的样式文件；网站用普通用户（非 root）身份运行，更安全
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput \
 && useradd --uid 10001 --create-home app \
 && mkdir -p /data/media \
 && chown -R app:app /data \
 && chmod +x docker/entrypoint.sh

USER app

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
