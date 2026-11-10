"""今日价格页面：每个品种只给一个价格。

规矩只有两条：
1. 每个品种挑一个价格显示：期货和现货里日期最新的那个；同一天的话用现货（报价是现货生意）。
2. 价格带着它自己的日期。只有日期等于今天才标“今天”，否则写明是哪天的。
"""

import datetime as dt
from collections import OrderedDict
from decimal import Decimal

from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from . import models as m

WEEKDAYS = "一二三四五六日"
KIND_LABEL = {"spot": "现货", "futures": "期货"}


def fmt_price(value) -> str:
    if value is None:
        return "—"
    value = Decimal(value)
    if value == value.to_integral_value():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def day_label(day: dt.date, today: dt.date) -> str:
    if day == today:
        return "今天"
    text = f"{day.month}月{day.day}日 周{WEEKDAYS[day.weekday()]}"
    if day == today - dt.timedelta(days=1):
        return "昨天 " + text
    return text


def _candidate(series, today):
    """一条序列的最新价格和涨跌；没有数据返回 None。"""
    recent = list(series.points.order_by("-date")[:2])
    if not recent:
        return None
    latest = recent[0]
    row = {
        "kind": series.price_type, "kind_label": KIND_LABEL.get(series.price_type, ""),
        "price": fmt_price(latest.price), "unit": f"元/{series.unit}", "date": latest.date,
        "is_today": latest.date == today, "date_label": day_label(latest.date, today),
    }
    if len(recent) > 1 and recent[1].price:
        diff = latest.price - recent[1].price
        row["direction"] = "up" if diff > 0 else "down" if diff < 0 else "flat"
        row["diff_text"] = fmt_price(abs(diff))
    return row


def price_rows(now, series_qs=None):
    """每个品种一行、一个价格。"""
    today = now.date()
    qs = series_qs if series_qs is not None else m.PriceSeries.objects.all()
    qs = qs.filter(is_active=True).exclude(auto_source="").select_related("entry").order_by("order", "pk")
    groups = OrderedDict()
    for series in qs:
        g = groups.setdefault(series.group, {"code": series.group, "title": series.group_title or series.name,
                                             "entry": series.entry, "candidates": [], "errors": []})
        cand = _candidate(series, today)
        if cand:
            g["candidates"].append(cand)
        if series.last_error:
            g["errors"].append(series.last_error)
    rows = []
    for g in groups.values():
        # 日期最新的优先；同一天现货优先
        best = max(g["candidates"], key=lambda c: (c["date"], c["kind"] == "spot"), default=None)
        row = {"code": g["code"], "title": g["title"], "entry": g["entry"], "has_price": best is not None}
        if best:
            row.update(best)
        else:
            row["error"] = g["errors"][0] if g["errors"] else "还没有数据，等第一次自动更新"
        rows.append(row)
    return rows


def related_price_rows(entry, now):
    """和某个材料词条有关的价格（它自己的、它上级的、它下级的）。"""
    cond = Q(entry=entry) | Q(entry__parent=entry)
    if entry.parent_id:
        cond |= Q(entry_id=entry.parent_id)
    return [r for r in price_rows(now, m.PriceSeries.objects.filter(cond)) if r["has_price"]]


def prices(request):
    now = timezone.localtime()
    return render(request, "kb/prices.html", {
        "rows": price_rows(now),
        "today_label": f"{now.month}月{now.day}日 周{WEEKDAYS[now.weekday()]}",
    })
