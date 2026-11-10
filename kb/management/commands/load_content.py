"""
把 content/ 目录里的知识文件导入数据库。容器每次启动时自动执行；重复执行是安全的。
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from kb.content import ContentError, Importer, read_content_dir
from kb.grades_import import GradeImporter, read_grades_dir
from kb.phase2_import import Phase2Importer


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
            grades_dir = content_dir / "grades"
            companies, grades = read_grades_dir(grades_dir) if grades_dir.exists() else ([], [])
        except ContentError as exc:
            raise CommandError(f"知识文件格式错误：{exc}") from exc

        report = Importer(items).run()
        self.stdout.write(self.style.SUCCESS(f"知识导入完成：{report.summary()}"))
        if report.skipped_edited:
            self.stdout.write("以下词条在后台改过，保留你的修改、没有覆盖：" + "、".join(report.skipped_edited))
        for warning in report.warnings:
            self.stdout.write(self.style.WARNING("提醒：" + warning))

        if companies or grades:
            greport = GradeImporter(companies, grades).run()
            self.stdout.write(self.style.SUCCESS(f"牌号导入完成：{greport.summary()}"))
            if greport.skipped_edited:
                self.stdout.write("以下牌号在后台改过，保留你的修改、没有覆盖：" + "、".join(greport.skipped_edited))
            for warning in greport.warnings:
                self.stdout.write(self.style.WARNING("提醒：" + warning))

            preport = Phase2Importer(companies, grades).run()
            self.stdout.write(self.style.SUCCESS(f"第二阶段资料补充完成：{preport.summary()}"))
            for warning in preport.warnings:
                self.stdout.write(self.style.WARNING("提醒：" + warning))
