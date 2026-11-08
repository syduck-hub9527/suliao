"""
启动时自动创建管理员账号（只在账号还不存在时创建，不会改已有账号的密码）。

账号和密码来自 .env 里的 DJANGO_SUPERUSER_USERNAME / DJANGO_SUPERUSER_PASSWORD。
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "按 .env 里的设置创建管理员账号（已存在则跳过）"

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
        if not username or not password:
            self.stdout.write("未设置管理员账号或密码，跳过。")
            return

        User = get_user_model()
        if User.objects.filter(username=username).exists():
            self.stdout.write(f"管理员 {username} 已存在，跳过。")
            return

        User.objects.create_superuser(username=username, email="", password=password)
        self.stdout.write(self.style.SUCCESS(f"已创建管理员 {username}。"))
