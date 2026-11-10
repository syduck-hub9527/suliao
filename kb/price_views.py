"""行情页面：把价格序列整理成页面要用的样子。

最要紧的一条：每个价格都带着它自己的日期。只有价格日期等于今天，才显示“今天”；
否则明确写出是哪天的价格，以及今天为什么没有（休市 / 还没到更新时间 / 没取到）。
"""

import datetime as dt
import math
from collections import OrderedDict
from decimal import Decimal

from django.db.models import Q
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone

from . import models as m
from . import price_catalog
from .render import md_to_html

WEEKDAYS = "一二三四五六日"
FUTURES_READY = dt.time(15, 35)   # 当天结算价大约这个时间之后能抓到
SERIES_COLORS = {"futures": "#2a78d6", "spot": "#eb6834"}   # 走势图里两条线的颜色（已做色盲区分度检查）
GLOSSARY = ["期货与现货", "结算价与收盘价", "主力合约", "基差", "含税价与不含税价", "出厂价、市场价与送到价"]
SERIES_SHORT = {"futures": "期货结算价", "spot": "生意社现货"}


def fmt_price(value) -> str:
    if value is None:
        return "—"
    value = Decimal(value)
    if value == value.to_integral_value():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def day_label(day: dt.date, today: dt.date) -> str:
    text = f"{day.month}月{day.day}日 周{WEEKDAYS[day.weekday()]}"
    if day == today:
        return "今天 · " + text
    if day == today - dt.timedelta(days=1):
        return "昨天 · " + text
    return text


def _why_not_today(series, now) -> str:
    """最新价格不是今天的时候，给一句解释。"""
    today = now.date()
    futures = series.price_type == m.PriceSeries.PriceType.FUTURES
    if today.weekday() >= 5:
        return "周末休市，没有新价格"
    if futures and now.time() < FUTURES_READY:
        return "今天的结算价要等下午收盘后（约 15:35）更新"
    checked_today = series.last_checked_at and timezone.localtime(series.last_checked_at).date() == today
    if series.last_error and checked_today:
        return "今天没取到：" + series.last_error
    if not checked_today:
        return "今天还没有运行过自动更新"
    if futures:
        return "今天没有新数据（可能是节假日休市，或数据源还没更新）"
    return "生意社今天的价格还没发布（也可能是节假日）"


def _sparkline(points, width=160, height=36) -> str:
    """最近一段时间的小走势线（SVG 折线的坐标串）。points 按日期从早到晚。"""
    values = [float(p.price) for p in points]
    if len(values) < 2:
        return ""
    low, high = min(values), max(values)
    span = (high - low) or 1
    step = (width - 4) / (len(values) - 1)
    return " ".join(f"{2 + i * step:.1f},{2 + (height - 4) * (1 - (v - low) / span):.1f}"
                    for i, v in enumerate(values))


def snapshot(series, now):
    """一条价格序列的“现在怎么样”。"""
    today = now.date()
    recent = list(series.points.order_by("-date")[:30])
    snap = {
        "series": series, "kind": series.price_type, "short": SERIES_SHORT.get(series.price_type, ""),
        "color": SERIES_COLORS.get(series.price_type, "#2a78d6"), "has_data": bool(recent),
        "unit": f"元/{series.unit}", "error": series.last_error,
    }
    if not recent:
        snap["why"] = ("还没取到过数据：" + series.last_error) if series.last_error else "还没有数据，等第一次自动更新"
        return snap
    latest = recent[0]
    snap.update({
        "point": latest, "price": fmt_price(latest.price), "date": latest.date,
        "is_today": latest.date == today, "date_label": day_label(latest.date, today),
        "why": "" if latest.date == today else _why_not_today(series, now),
        "spark": _sparkline(list(reversed(recent))),
    })
    if len(recent) > 1:
        prev = recent[1]
        diff = latest.price - prev.price
        snap.update({
            "diff": diff, "diff_text": ("+" if diff > 0 else "") + fmt_price(diff),
            "pct_text": f"{diff / prev.price * 100:+.2f}%" if prev.price else "",
            "direction": "up" if diff > 0 else "down" if diff < 0 else "flat",
            "prev_label": f"比上一个交易日（{prev.date.month}月{prev.date.day}日）",
        })
    return snap


def price_groups(now, series_qs=None):
    """按商品分组：每组里有期货和（或）现货两张“快照”，外加基差。"""
    qs = series_qs if series_qs is not None else m.PriceSeries.objects.all()
    qs = qs.filter(is_active=True).exclude(auto_source="").select_related("entry", "source").order_by("order", "pk")
    about = {item["group"]: item["about"] for item in price_catalog.CATALOG}
    groups = OrderedDict()
    for series in qs:
        g = groups.setdefault(series.group, {
            "code": series.group, "title": series.group_title or series.name, "about": about.get(series.group, ""),
            "entry": series.entry, "snaps": [], "futures": None, "spot": None,
        })
        snap = snapshot(series, now)
        g["snaps"].append(snap)
        if snap["kind"] in ("futures", "spot"):
            g[snap["kind"]] = snap
    for g in groups.values():
        fut, spot = g["futures"], g["spot"]
        g["has_data"] = any(s["has_data"] for s in g["snaps"])
        # 基差只在两个价格是同一天时才算，不拿不同日子的价格相减
        if fut and spot and fut["has_data"] and spot["has_data"] and fut["date"] == spot["date"]:
            basis = spot["point"].price - fut["point"].price
            g["basis"] = {
                "text": fmt_price(abs(basis)),
                "sentence": ("现货比期货高" if basis > 0 else "现货比期货低" if basis < 0 else "现货和期货持平"),
                "zero": basis == 0,
            }
    return list(groups.values())


def related_price_groups(entry, now):
    """和某个材料词条有关的价格（它自己的、它上级的、它下级的）。"""
    cond = Q(entry=entry) | Q(entry__parent=entry)
    if entry.parent_id:
        cond |= Q(entry_id=entry.parent_id)
    return [g for g in price_groups(now, m.PriceSeries.objects.filter(cond)) if g["has_data"]]


def _status(groups, now):
    snaps = [s for g in groups for s in g["snaps"]]
    checked = [s["series"].last_checked_at for s in snaps if s["series"].last_checked_at]
    return {
        "total": len(snaps),
        "today": sum(1 for s in snaps if s.get("is_today")),
        "with_data": sum(1 for s in snaps if s["has_data"]),
        "failed": [s for s in snaps if s["error"]],
        "last_checked": timezone.localtime(max(checked)) if checked else None,
    }


def prices(request):
    now = timezone.localtime()
    groups = price_groups(now)
    return render(request, "kb/prices.html", {
        "groups": groups, "status": _status(groups, now), "now": now,
        "today_label": f"{now.year}年{now.month}月{now.day}日 周{WEEKDAYS[now.weekday()]}",
        "manual_series": m.PriceSeries.objects.filter(auto_source="", is_active=True).select_related("entry", "grade"),
        "glossary": m.Entry.objects.filter(name_zh__in=GLOSSARY).order_by("path_items__order"),
    })


# ---------------- 走势图 ----------------

def _nice_ticks(low: float, high: float, count=4):
    """给纵轴挑几个整齐的刻度（步长是 1、2、2.5、5 乘以 10 的若干次方）。"""
    if high <= low:
        high = low + 1
    raw = (high - low) / count
    mag = 10 ** math.floor(math.log10(raw))
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw * 0.999)
    start = math.floor(low / step) * step
    ticks = [round(start + i * step, 6) for i in range(int(round((high - start) / step)) + 2)]
    while len(ticks) > 2 and ticks[-2] >= high:
        ticks.pop()
    return ticks


def build_chart(snaps, days=120, width=760, height=300):
    """把一组序列画到同一张图上（同一个单位、同一根纵轴）。返回模板和悬停脚本要用的坐标。"""
    pad_l, pad_r, pad_t, pad_b = 56, 96, 14, 28
    per_series = []
    for snap in snaps:
        pts = list(reversed(snap["series"].points.order_by("-date")[:days]))
        if pts:
            per_series.append((snap, pts))
    if not per_series:
        return None
    dates = sorted({p.date for _, pts in per_series for p in pts})[-days:]
    if len(dates) < 2:
        return None
    index = {d: i for i, d in enumerate(dates)}
    values = [float(p.price) for _, pts in per_series for p in pts if p.date in index]
    ticks = _nice_ticks(min(values), max(values))
    y_low, y_high = ticks[0], ticks[-1]
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b

    def x(i):
        return pad_l + plot_w * i / (len(dates) - 1)

    def y(v):
        return pad_t + plot_h * (1 - (v - y_low) / (y_high - y_low))

    lines, hover = [], [{"date": f"{d.month}月{d.day}日", "x": round(x(i), 1), "v": {}} for i, d in enumerate(dates)]
    for snap, pts in per_series:
        coords = [(x(index[p.date]), y(float(p.price)), p) for p in pts if p.date in index]
        for cx, _, p in coords:
            hover[index[p.date]]["v"][snap["kind"]] = fmt_price(p.price)
        last_x, last_y, last_p = coords[-1]
        lines.append({
            "kind": snap["kind"], "name": snap["short"], "color": snap["color"],
            "path": " ".join(f"{cx:.1f},{cy:.1f}" for cx, cy, _ in coords) if len(coords) > 1 else "",
            "dots": [{"x": round(cx, 1), "y": round(cy, 1)} for cx, cy, _ in coords] if len(coords) < 8 else [],
            "end": {"x": round(last_x, 1), "y": round(last_y, 1), "label": fmt_price(last_p.price)},
            "ys": {index[p.date]: round(cy, 1) for _, cy, p in coords},
        })
    # 两条线的末端标签靠太近时错开，避免叠在一起
    ends = sorted(lines, key=lambda line: line["end"]["y"])
    for upper, lower in zip(ends, ends[1:]):
        if lower["end"]["y"] - upper["end"]["y"] < 28:
            mid = (lower["end"]["y"] + upper["end"]["y"]) / 2
            upper["end"]["label_y"], lower["end"]["label_y"] = mid - 14, mid + 14
    for line in lines:
        line["end"].setdefault("label_y", line["end"]["y"])
        line["end"]["label_y"] = round(min(max(line["end"]["label_y"], pad_t + 4), height - pad_b - 14), 1)
        line["end"]["label_x"] = round(line["end"]["x"] + 10, 1)
        line["end"]["name_y"] = round(line["end"]["label_y"] + 14, 1)

    x_marks = sorted({0, (len(dates) - 1) // 2, len(dates) - 1})
    return {
        "width": width, "height": height, "lines": lines,
        "ticks": [{"y": round(y(t), 1), "label": fmt_price(Decimal(str(t)))} for t in ticks],
        "x_labels": [{"x": round(x(i), 1), "label": f"{dates[i].month}月{dates[i].day}日",
                      "anchor": "start" if i == 0 else "end" if i == len(dates) - 1 else "middle"} for i in x_marks],
        "plot": {"left": pad_l, "right": width - pad_r, "top": pad_t, "bottom": height - pad_b,
                 "tick_x": pad_l - 8, "date_y": height - 8},
        "hover": hover, "hover_lines": [{"kind": ln["kind"], "name": ln["name"], "color": ln["color"],
                                         "ys": ln["ys"]} for ln in lines],
        "first": dates[0], "last": dates[-1], "count": len(dates),
    }


def price_detail(request, group):
    now = timezone.localtime()
    groups = price_groups(now, m.PriceSeries.objects.filter(group=group))
    if not groups:
        raise Http404("没有这个价格品种")
    g = groups[0]

    # 明细表：把期货和现货按日期并排
    rows = OrderedDict()
    for snap in g["snaps"]:
        for p in snap["series"].points.order_by("-date")[:60]:
            rows.setdefault(p.date, {"date": p.date})[snap["kind"]] = p
    table = []
    for day in sorted(rows, reverse=True)[:60]:
        row = rows[day]
        fut, spot = row.get("futures"), row.get("spot")
        table.append({
            "date": day, "weekday": WEEKDAYS[day.weekday()], "is_today": day == now.date(),
            "futures": fmt_price(fut.price) if fut else "", "close": fmt_price(fut.close_price) if fut and fut.close_price else "",
            "range": f"{fmt_price(fut.price_low)}～{fmt_price(fut.price_high)}" if fut and fut.price_low and fut.price_high else "",
            "contract": fut.contract if fut else "", "note": fut.note if fut else "",
            "spot": fmt_price(spot.price) if spot else "",
            "basis": (("+" if spot.price > fut.price else "") + fmt_price(spot.price - fut.price)) if fut and spot else "",
        })
    for snap in g["snaps"]:
        snap["explain_html"] = md_to_html(snap["series"].explain) if snap["series"].explain else ""
    return render(request, "kb/price_detail.html", {
        "g": g, "chart": build_chart(g["snaps"]), "table": table, "now": now,
        "has_spot": bool(g["spot"]), "has_futures": bool(g["futures"]),
        "glossary": m.Entry.objects.filter(name_zh__in=GLOSSARY).order_by("path_items__order"),
    })
