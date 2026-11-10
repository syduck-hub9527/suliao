from django.core.management.base import BaseCommand

from kb.price_update import run_update


class Command(BaseCommand):
    help = "抓取最新的期货结算价和生意社现货参考价，写进数据库。可以随时手动执行，重复执行是安全的。"

    def add_arguments(self, parser):
        parser.add_argument("--no-futures", action="store_true", help="这次不抓期货")
        parser.add_argument("--no-spot", action="store_true", help="这次不抓生意社现货")

    def handle(self, *args, **opts):
        report = run_update(futures=not opts["no_futures"], spot=not opts["no_spot"])
        self.stdout.write("价格更新结果：")
        for line in report.lines():
            self.stdout.write(line)
