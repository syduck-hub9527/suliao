"""
把 content/ 目录里的知识文件导入数据库。容器每次启动时自动执行；重复执行是安全的。
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from kb.content import ContentError, Importer, read_content_dir


class Command(BaseCommand):
    help = "导入 content/ 目录下的知识内容"

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=None, help="知识文件目录（默认 settings.CONTENT_DIR）")

    def handle(self, *args, **options):
        content_dir = Path(options["dir"] or settings.CONTENT_DIR)
        if not content_dir.exists():
            self.stdout.write(f"没有找到知识目录 {content_dir}，跳过导入。")
            return
        try:
            items = read_content_dir(content_dir)
        except ContentError as exc:
            raise CommandError(f"知识文件格式错误：{exc}") from exc

        report = Importer(items).run()
        self.stdout.write(self.style.SUCCESS(f"知识导入完成：{report.summary()}"))
        if report.skipped_edited:
            self.stdout.write("以下词条在后台改过，保留你的修改、没有覆盖：" + "、".join(report.skipped_edited))
        for warning in report.warnings:
            self.stdout.write(self.style.WARNING("提醒：" + warning))
