"""
价格定时更新：一个一直运行的小程序，每天到点执行 update_prices。

docker-compose.yml 里的 prices 服务跑的就是它。到点后另起一个进程去抓取，
抓取进程卡住或出错都不会影响下一次。
"""

import datetime as dt
import os
import subprocess
import sys
import time

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

# 北京时间。期货下午 3 点收盘，结算价稍后公布；多跑几次是为了补上晚到的数据
DEFAULT_TIMES = "11:35,15:35,16:35,18:05,20:35"
RUN_TIMEOUT = 600  # 一次抓取最多给 10 分钟


def parse_times(text):
    times = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        hour, minute = part.split(":")
        times.append(dt.time(int(hour), int(minute)))
    if not times:
        raise ValueError("没有可用的时间")
    return sorted(times)


def next_run(now, times):
    """now 之后最近的一个运行时刻（now 是带时区的本地时间）。"""
    for day_offset in (0, 1):
        day = now.date() + dt.timedelta(days=day_offset)
        for t in times:
            candidate = now.replace(year=day.year, month=day.month, day=day.day,
                                    hour=t.hour, minute=t.minute, second=0, microsecond=0)
            if candidate > now:
                return candidate
    raise RuntimeError("算不出下一次运行时间")


class Command(BaseCommand):
    help = "一直运行，每天定时抓取价格（给 Docker 的 prices 服务用）。"

    def log(self, text):
        stamp = timezone.localtime().strftime("%m-%d %H:%M:%S")
        self.stdout.write(f"[{stamp}] {text}")
        self.stdout.flush()

    def wait_for_database(self):
        """等网站容器把数据库升级完再开始，避免两边同时动表结构。"""
        while True:
            try:
                executor = MigrationExecutor(connection)
                if not executor.migration_plan(executor.loader.graph.leaf_nodes()):
                    return
                self.log("数据库还在升级，10 秒后再看……")
            except Exception as exc:
                self.log(f"数据库还没准备好（{exc}），10 秒后再看……")
            connection.close()
            time.sleep(10)

    def run_once(self):
        self.log("开始抓取价格")
        try:
            result = subprocess.run([sys.executable, "manage.py", "update_prices"],
                                    capture_output=True, text=True, timeout=RUN_TIMEOUT)
            for line in (result.stdout + result.stderr).strip().splitlines()[-40:]:
                self.log(line)
            if result.returncode != 0:
                self.log(f"抓取程序异常退出（代码 {result.returncode}）")
        except subprocess.TimeoutExpired:
            self.log(f"抓取超过 {RUN_TIMEOUT} 秒还没结束，已中止，等下一次")

    def handle(self, *args, **opts):
        try:
            times = parse_times(os.environ.get("PRICE_UPDATE_TIMES", DEFAULT_TIMES))
        except ValueError as exc:
            self.log(f"PRICE_UPDATE_TIMES 写法不对（{exc}），改用默认时间 {DEFAULT_TIMES}")
            times = parse_times(DEFAULT_TIMES)
        self.wait_for_database()
        connection.close()
        self.log("价格定时更新已启动，每天运行时间（北京时间）：" + "、".join(t.strftime("%H:%M") for t in times))
        self.run_once()  # 启动时先抓一次
        while True:
            target = next_run(timezone.localtime(), times)
            self.log(f"下一次：{target.strftime('%m-%d %H:%M')}")
            while timezone.localtime() < target:
                time.sleep(min(60, max(1, (target - timezone.localtime()).total_seconds())))
            self.run_once()
