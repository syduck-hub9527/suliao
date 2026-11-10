"""
价格自动更新：把 price_catalog 里的品种同步进数据库，然后抓取、入库。

几条规矩：
1. 价格点的日期用数据源给的日期，不用“抓取的那天”。所以页面上不会把旧价格当成今天的。
2. 当天的期货日线要等收盘、结算价出来后才入库（见 price_fetch.accept_bar）。
3. 每条序列各自记录“上次尝试 / 上次成功 / 失败原因”，某个来源挂了不影响别的，行情页会如实显示。
4. 每次都会重写最近几天的数据，数据源事后更正的数字能跟上。
"""

import datetime as dt
import time
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from . import models as m
from . import price_catalog, price_fetch
from .price_fetch import FetchError

HISTORY_DAYS = 20       # 往回取多少天（只为了算“比上一天涨跌多少”，不需要更多）
REFRESH_BARS = 5        # 之后每次重写最近几根日线


@dataclass
class UpdateReport:
    ok: list = field(default_factory=list)        # (序列名, 最新日期, 最新价格, 新增点数)
    failed: list = field(default_factory=list)    # (序列名, 原因)

    def lines(self):
        out = []
        for name, day, price, added in self.ok:
            out.append(f"  ✓ {name}：最新 {day} {price:g}" + (f"（新增 {added} 天）" if added else ""))
        for name, reason in self.failed:
            out.append(f"  ✗ {name}：{reason}")
        out.append(f"成功 {len(self.ok)} 条，失败 {len(self.failed)} 条")
        return out


def _find_entry(key):
    if not key:
        return None
    qs = m.Entry.objects.filter(kind=m.EntryKind.MATERIAL)
    return qs.filter(abbr__iexact=key).first() or qs.filter(name_zh=key).first()


def sync_catalog():
    """按 price_catalog 建立或更新自动序列。清单里删掉的品种不会删数据，只是标成“不再跟踪”。"""
    sources = {}
    for key, spec in price_catalog.SOURCES.items():
        source, _ = m.Source.objects.update_or_create(
            title=spec["title"], kind=spec["kind"],
            defaults={"publisher": spec["publisher"], "url": spec["url"], "note": spec["note"]},
        )
        sources[key] = source

    codes = []
    for spec in price_catalog.series_specs():
        codes.append(spec["code"])
        m.PriceSeries.objects.update_or_create(
            code=spec["code"],
            defaults={
                "name": spec["name"], "entry": _find_entry(spec["entry"]), "price_type": spec["price_type"],
                "market": spec["market"], "currency": m.PriceSeries.Currency.CNY, "unit": spec["unit"],
                "tax": spec["tax"], "source": sources[spec["auto_source"]], "auto_source": spec["auto_source"],
                "symbol": spec["symbol"], "group": spec["group"], "group_title": spec["group_title"],
                "order": spec["order"], "explain": spec["explain"], "is_active": True,
            },
        )
    m.PriceSeries.objects.exclude(auto_source="").exclude(code__in=codes).update(is_active=False)
    return codes


def _mark(series, now, error=""):
    series.last_checked_at = now
    series.last_error = error[:300]
    if not error:
        series.last_ok_at = now
    series.save(update_fields=["last_checked_at", "last_error", "last_ok_at", "updated_at"])


def _latest(series):
    return series.points.order_by("-date").first()


def update_futures(now, report, fetch=price_fetch.fetch_futures_bars, pause=0.0):
    local_now = timezone.localtime(now).replace(tzinfo=None)
    start = local_now.date() - dt.timedelta(days=HISTORY_DAYS)
    qs = m.PriceSeries.objects.filter(is_active=True, auto_source=m.PriceSeries.AutoSource.SINA_FUTURES)
    for number, series in enumerate(qs):
        if pause and number:
            time.sleep(pause)   # 一个接一个慢慢取，别给数据源添麻烦
        try:
            bars = [b for b in fetch(series.symbol, start) if price_fetch.accept_bar(b, local_now)]
            if not bars:
                raise FetchError("数据源没有返回可用的日线")
            have = set(series.points.values_list("date", flat=True))
            todo = [b for b in bars if b.date not in have] + bars[-REFRESH_BARS:]
            added = 0
            with transaction.atomic():
                for bar in {b.date: b for b in todo}.values():
                    _, created = m.PricePoint.objects.update_or_create(
                        series=series, date=bar.date,
                        defaults={
                            "price": bar.settle or bar.close, "close_price": bar.close,
                            "price_low": bar.low if bar.low and bar.high and bar.low <= bar.high else None,
                            "price_high": bar.high if bar.low and bar.high and bar.low <= bar.high else None,
                            "note": "" if bar.settle else "数据源没给结算价，这里记的是收盘价",
                        },
                    )
                    added += created
            _mark(series, now)
            last = _latest(series)
            report.ok.append((series.name, last.date, float(last.price), added))
        except FetchError as exc:
            _mark(series, now, str(exc))
            report.failed.append((series.name, str(exc)))
        except Exception as exc:  # 意料之外的错误也要记下来，不能让一个品种拖垮全部
            _mark(series, now, f"程序出错：{type(exc).__name__} {exc}")
            report.failed.append((series.name, f"程序出错：{type(exc).__name__} {exc}"))


def update_spot(now, report, fetch=price_fetch.fetch_ppi_spot):
    qs = list(m.PriceSeries.objects.filter(is_active=True, auto_source=m.PriceSeries.AutoSource.PPI_SPOT))
    if not qs:
        return
    try:
        page_date, rows = fetch()
        if page_date > timezone.localtime(now).date():
            raise FetchError(f"生意社表格日期 {page_date} 在今天之后，数据有问题，没有入库")
    except Exception as exc:
        reason = str(exc) if isinstance(exc, FetchError) else f"程序出错：{type(exc).__name__} {exc}"
        for series in qs:
            _mark(series, now, reason)
            report.failed.append((series.name, reason))
        return

    for series in qs:
        row = rows.get(series.symbol)
        if row is None:
            reason = f"生意社 {page_date} 的表里没有这个品种"
            _mark(series, now, reason)
            report.failed.append((series.name, reason))
            continue
        _, created = m.PricePoint.objects.update_or_create(
            series=series, date=page_date, defaults={"price": row.spot, "contract": ""},
        )
        _mark(series, now)
        report.ok.append((series.name, page_date, float(row.spot), int(created)))
        # 顺手把主力合约代码补到同一天的期货价格点上（新浪的主力连续不告诉我们是哪个合约）
        if row.contract:
            m.PricePoint.objects.filter(series__code=f"fut:{series.group}", date=page_date,
                                        contract="").update(contract=row.contract)


def run_update(now=None, futures=True, spot=True) -> UpdateReport:
    now = now or timezone.now()
    sync_catalog()
    report = UpdateReport()
    if futures:
        update_futures(now, report, pause=0.8)
    if spot:
        update_spot(now, report)
    return report
