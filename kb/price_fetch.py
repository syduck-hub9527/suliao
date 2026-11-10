"""
从外部网站取价格数据（只负责“取”和“解析”，不碰数据库）。

- 期货：新浪财经的主力连续日线，通过 AKShare 的 futures_main_sina 取。
- 现货参考价：生意社“现期表”（https://www.100ppi.com/sf/），一次请求拿到当天所有品种。

AKShare 比较大（带 pandas），只在真正抓取时才导入，网站本身不加载它。
"""

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class FetchError(Exception):
    """取数失败。信息是给人看的，会原样显示在行情页上。"""


@dataclass
class Bar:
    """期货一天的行情。"""
    date: dt.date
    settle: Decimal | None
    close: Decimal | None
    low: Decimal | None
    high: Decimal | None


@dataclass
class SpotRow:
    """生意社现期表里的一行。"""
    spot: Decimal
    contract: str = ""            # 主力合约代码，例：PP2701
    futures_price: Decimal | None = None


def explain_error(exc: Exception) -> str:
    """把网络异常翻译成一句人话，后面带一小段原始信息方便排查。"""
    name = type(exc).__name__
    if "Timeout" in name:
        head = "连接超时"
    elif "Proxy" in name:
        head = "代理连不上"
    elif "SSL" in name:
        head = "安全连接失败"
    elif "Connection" in name:
        head = "连不上网站"
    elif "JSON" in name or name in ("ValueError", "KeyError", "IndexError"):
        head = "返回的内容不是预期的格式（网站可能改版或拒绝了访问）"
    else:
        head = "出错了"
    detail = " ".join(str(exc).split())
    return f"{head}（{name}：{detail[:90]}）"


def _dec(value) -> Decimal | None:
    """转成数字；空值、NaN、0 和负数都当作“没有”。"""
    try:
        d = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not d.is_finite() or d <= 0:
        return None
    return d


# ---------------- 期货（新浪） ----------------

def parse_sina_frame(df) -> list[Bar]:
    """把 futures_main_sina 返回的表转成 Bar 列表（按日期从早到晚）。"""
    bars = []
    for row in df.to_dict("records"):
        day = row.get("日期")
        if isinstance(day, dt.datetime):
            day = day.date()
        if not isinstance(day, dt.date):
            continue
        bars.append(Bar(date=day, settle=_dec(row.get("动态结算价")), close=_dec(row.get("收盘价")),
                        low=_dec(row.get("最低价")), high=_dec(row.get("最高价"))))
    bars.sort(key=lambda b: b.date)
    return bars


def fetch_futures_bars(symbol: str, start: dt.date) -> list[Bar]:
    """取某个期货品种主力连续合约从 start 起的日线。"""
    try:
        import akshare as ak
        df = ak.futures_main_sina(symbol=symbol, start_date=start.strftime("%Y%m%d"))
    except Exception as exc:  # 网络、网站改版、被限流……统一成一句人话
        raise FetchError(f"新浪期货 {symbol} 没取到：{explain_error(exc)}") from exc
    bars = parse_sina_frame(df)
    if not bars:
        raise FetchError(f"新浪期货 {symbol} 返回了空数据")
    return bars


def accept_bar(bar: Bar, now: dt.datetime) -> bool:
    """这根日线能不能入库。

    当天的日线要等下午收盘、结算价出来以后才算数（15:20 以后）：盘中抓到的是变动中的数字。
    晚上夜盘开始后，数据源可能会出现“下一个交易日”的日线，日期在今天之后，一律不收。
    """
    today = now.date()
    if bar.date > today:
        return False
    if bar.date == today and now.time() < dt.time(15, 20):
        return False
    return (bar.settle or bar.close) is not None


# ---------------- 现货参考价（生意社） ----------------

PPI_URL = "https://www.100ppi.com/sf/"

# 生意社表格里的商品名称 → 我们用的代码（只列用得到的；写法参考 AKShare 的对照表）
PPI_NAMES = {
    "聚乙烯": "L", "LLDPE": "L",
    "聚丙烯": "PP", "PP": "PP",
    "聚氯乙烯": "V", "PVC": "V",
    "瓶片": "PR", "瓶片期货": "PR",
    "苯乙烯": "EB",
    "PTA": "TA",
    "乙二醇": "EG",
}

_DATE_RE = re.compile(r"(20\d{2})\s*[-年/.]\s*(\d{1,2})\s*[-月/.]\s*(\d{1,2})")
_CJK_RE = re.compile(r"[一-龥]+")


def _cell(value) -> str:
    text = "" if value is None else str(value)
    return "" if text.lower() == "nan" else text.strip()


def parse_ppi_tables(tables) -> tuple[dt.date, dict[str, SpotRow]]:
    """从生意社现期表页面的表格里解析出：这张表是哪一天的、各品种的现货价。

    表格的日期以页面上写的为准，不用抓取当天的日期——这样周末、节假日抓到的旧表不会被当成今天的。
    """
    if not tables:
        raise FetchError("生意社页面里没有找到价格表（可能触发了网站的安全检查）")

    page_date = None
    for table in tables:
        for row in table.values.tolist()[:6]:
            for cell in row:
                found = _DATE_RE.search(str(cell))
                if found:
                    try:
                        page_date = dt.date(*map(int, found.groups()))
                    except ValueError:
                        continue
                    break
            if page_date:
                break
        if page_date:
            break
    if page_date is None:
        raise FetchError("生意社页面上没找到表格日期，页面格式可能变了")

    data = max((t for t in tables if t.shape[1] >= 7), key=lambda t: t.shape[0], default=None)
    if data is None:
        raise FetchError("生意社页面里没有找到现期对照表，页面格式可能变了")

    rows: dict[str, SpotRow] = {}
    for raw in data.values.tolist():
        name_cell = _cell(raw[0])
        name = "".join(_CJK_RE.findall(name_cell)) or name_cell
        symbol = PPI_NAMES.get(name) or PPI_NAMES.get(name_cell)
        spot = _dec(raw[1])
        if not symbol or spot is None or symbol in rows:
            continue
        digits = re.search(r"(\d{3,4})\s*$", _cell(raw[5]))
        rows[symbol] = SpotRow(spot=spot, contract=f"{symbol}{digits.group(1)}" if digits else "",
                               futures_price=_dec(raw[6]))
    if not rows:
        raise FetchError("生意社表格里没有找到要跟踪的品种，页面格式可能变了")
    return page_date, rows


def fetch_ppi_spot() -> tuple[dt.date, dict[str, SpotRow]]:
    """取生意社最新一张现期表。只发一次请求，失败就报错，不反复重试（避免被网站封）。"""
    try:
        from akshare.futures.requests_fun import pandas_read_html_link
        tables = pandas_read_html_link(PPI_URL, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
    except ValueError as exc:  # pandas 在页面里找不到表格
        raise FetchError("生意社返回的页面里没有价格表（可能触发了网站的安全检查，或网站暂时打不开）") from exc
    except Exception as exc:
        raise FetchError(f"生意社现期表没取到：{explain_error(exc)}") from exc
    return parse_ppi_tables(tables)
