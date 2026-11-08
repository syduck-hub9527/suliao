"""
项目设置。

所有“因服务器而异”或“需要保密”的值都从环境变量读取（部署时写在 .env 文件里，不进 GitHub）。
数据库文件和上传的文件都放在 DJANGO_DATA_DIR 目录（Docker 里是 /data 数据卷），和代码分开。
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# ---------- 基本开关 ----------

DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key"
    else:
        raise ImproperlyConfigured("缺少 DJANGO_SECRET_KEY：请在 .env 文件里设置。")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

# 免登录模式：只有你一个人用，打开就直接进入，没有登录页。
# 安全前提：网站只能从服务器本机访问（你通过 SSH 隧道进来，SSH 登录就是那道“门”）。
# 所以开启时只允许本机地址，防止以后不小心开放到公网。
SINGLE_USER_MODE = env_bool("SINGLE_USER_MODE", True)
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
if SINGLE_USER_MODE and not set(ALLOWED_HOSTS) <= _LOCAL_HOSTS:
    raise ImproperlyConfigured(
        "免登录模式只允许本机访问：DJANGO_ALLOWED_HOSTS 只能是 localhost,127.0.0.1。"
        "如果要对外开放网站，请先把 SINGLE_USER_MODE 改成 false 并设置登录。"
    )
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")

DATA_DIR = Path(os.environ.get("DJANGO_DATA_DIR", BASE_DIR / "data"))
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass


# ---------- 应用 ----------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "kb",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "kb.middleware.SingleUserMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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


# ---------- 数据库：SQLite ----------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
        "OPTIONS": {
            # WAL 模式：读写互不阻塞；IMMEDIATE：避免偶发的“database is locked”
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA foreign_keys=ON;",
            "transaction_mode": "IMMEDIATE",
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------- 登录 ----------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "admin:login"

# 知识内容文件所在目录（部署时自动导入）
CONTENT_DIR = BASE_DIR / "content"


# ---------- 语言和时区 ----------

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True


# ---------- 静态文件（后台的样式等）和上传文件 ----------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MEDIA_URL = "media/"
MEDIA_ROOT = DATA_DIR / "media"

# 单个上传文件上限 50 MB（TDS/SDS 一般几百 KB 到几 MB）
DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024


# ---------- 日志：输出到控制台，用 docker compose logs 查看 ----------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
