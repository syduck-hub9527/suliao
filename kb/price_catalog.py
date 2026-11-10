"""
自动更新的价格品种清单。

每个“分组”是一种商品，最多两条价格序列：
- futures：期货主力连续合约的每日结算价（来源：新浪财经期货行情）；
- spot：生意社“现期表”里的现货参考价（来源：生意社 100ppi.com）。

要增减品种，改这个文件，然后重新部署；update_prices 命令会自动把清单同步进数据库。
"""

FUTURES_NOTE = "期货交易所主力合约当天的结算价，每个交易日下午收盘后才有。"
SPOT_NOTE = "生意社每天发布的现货参考价。"

SOURCES = {
    "sina_futures": {
        "kind": "market",
        "title": "新浪财经 · 期货行情（主力连续日线）",
        "publisher": "新浪财经",
        "url": "https://vip.stock.finance.sina.com.cn/quotes_service/view/qihuohangqing.html",
        "note": "自动抓取。主力连续合约的每日开盘、最高、最低、收盘和结算价。",
    },
    "100ppi": {
        "kind": "market",
        "title": "生意社 · 现期表（现货与期货价格对照）",
        "publisher": "生意社（100ppi.com）",
        "url": "https://www.100ppi.com/sf/",
        "note": "自动抓取。生意社每个交易日发布的现货参考价。",
    },
}

# 只跟踪客户常问价的几种通用塑料。entry：对应知识词条的缩写；unit：计价单位
CATALOG = [
    {"group": "L", "title": "聚乙烯 PE（LLDPE）", "entry": "LLDPE", "unit": "吨", "order": 10,
     "futures": {"symbol": "L0", "market": "大连商品交易所"}, "spot": {"symbol": "L"}},
    {"group": "PP", "title": "聚丙烯 PP", "entry": "PP", "unit": "吨", "order": 20,
     "futures": {"symbol": "PP0", "market": "大连商品交易所"}, "spot": {"symbol": "PP"}},
    {"group": "V", "title": "聚氯乙烯 PVC", "entry": "PVC", "unit": "吨", "order": 30,
     "futures": {"symbol": "V0", "market": "大连商品交易所"}, "spot": {"symbol": "V"}},
    {"group": "PR", "title": "PET 瓶片", "entry": "PET", "unit": "吨", "order": 40,
     "futures": {"symbol": "PR0", "market": "郑州商品交易所"}, "spot": {"symbol": "PR"}},
]


def series_specs():
    """把清单展开成一条条价格序列的定义。"""
    specs = []
    for item in CATALOG:
        common = {"group": item["group"], "group_title": item["title"], "entry": item["entry"],
                  "unit": item["unit"]}
        if item.get("futures"):
            specs.append({
                **common, "code": f"fut:{item['group']}", "auto_source": "sina_futures",
                "symbol": item["futures"]["symbol"], "market": item["futures"]["market"],
                "name": f"{item['title']} · 期货主力结算价", "price_type": "futures", "tax": "included",
                "order": item["order"], "explain": FUTURES_NOTE,
            })
        if item.get("spot"):
            specs.append({
                **common, "code": f"spot:{item['group']}", "auto_source": "100ppi",
                "symbol": item["spot"]["symbol"], "market": "生意社基准价",
                "name": f"{item['title']} · 现货参考价（生意社）", "price_type": "spot", "tax": "unknown",
                "order": item["order"] + 1, "explain": SPOT_NOTE,
            })
    return specs
