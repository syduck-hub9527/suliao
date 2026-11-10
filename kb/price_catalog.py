"""
自动更新的价格品种清单。

每个“分组”是一种商品，最多两条价格序列：
- futures：期货主力连续合约的每日结算价（来源：新浪财经期货行情）；
- spot：生意社“现期表”里的现货参考价（来源：生意社 100ppi.com）。

要增减品种，改这个文件，然后重新部署；update_prices 命令会自动把清单同步进数据库。
"""

FUTURES_NOTE = (
    "这是期货交易所里“主力合约”当天的**结算价**（全天成交价按成交量加权平均），含税，"
    "每个交易日下午收盘后才有。它反映的是市场对未来几个月价格的看法，"
    "**不是**你今天去买货的价格，但现货报价通常跟着它涨跌，所以业内每天都看。\n\n"
    "走势图用的是“主力连续”：把各个时期的主力合约接成一条线。主力合约每隔几个月换一次（换月），"
    "换的那几天图上可能出现一个跳空，那不是真的涨跌了那么多。"
)
SPOT_NOTE = (
    "这是生意社每天发布的**现货参考价**，是生意社按自己选定的规格和地区采集的基准价，"
    "用来看现货市场的大致水平和涨跌方向。具体到某个牌号、某个地区、某个供应商，实际成交价会有出入。"
)

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

# entry：对应知识词条的缩写或中文名（没有就不挂词条）；unit：计价单位
CATALOG = [
    {
        "group": "L", "title": "聚乙烯（LLDPE）", "entry": "LLDPE", "unit": "吨", "order": 10,
        "about": "大连商品交易所的线型低密度聚乙烯期货，代码 L，行业里常直接叫“塑料”期货。看聚乙烯行情，一般先看它。",
        "futures": {"symbol": "L0", "market": "大连商品交易所"},
        "spot": {"symbol": "L"},
    },
    {
        "group": "PP", "title": "聚丙烯（PP）", "entry": "PP", "unit": "吨", "order": 20,
        "about": "大连商品交易所的聚丙烯期货，代码 PP。PP 拉丝料等通用料的现货报价基本跟着它走。",
        "futures": {"symbol": "PP0", "market": "大连商品交易所"},
        "spot": {"symbol": "PP"},
    },
    {
        "group": "V", "title": "聚氯乙烯（PVC）", "entry": "PVC", "unit": "吨", "order": 30,
        "about": "大连商品交易所的聚氯乙烯期货，代码 V。交割标准品是 SG5 型 PVC，所以它基本就是 SG-5 的价格风向标。",
        "futures": {"symbol": "V0", "market": "大连商品交易所"},
        "spot": {"symbol": "V"},
    },
    {
        "group": "PR", "title": "瓶片（瓶级 PET）", "entry": "PET", "unit": "吨", "order": 40,
        "about": "郑州商品交易所的瓶片期货，代码 PR。瓶片就是做饮料瓶用的瓶级 PET 切片。",
        "futures": {"symbol": "PR0", "market": "郑州商品交易所"},
        "spot": {"symbol": "PR"},
    },
    {
        "group": "EB", "title": "苯乙烯（PS、ABS 的原料）", "entry": "PS", "unit": "吨", "order": 50,
        "about": "大连商品交易所的苯乙烯期货，代码 EB。苯乙烯是生产 PS、ABS 的主要原料，它涨跌会带动 PS、ABS 的成本。",
        "futures": {"symbol": "EB0", "market": "大连商品交易所"},
        "spot": {"symbol": "EB"},
    },
    {
        "group": "TA", "title": "PTA（PET 的原料）", "entry": "PET", "unit": "吨", "order": 60,
        "about": "郑州商品交易所的 PTA（精对苯二甲酸）期货，代码 TA。PTA 和乙二醇反应生成 PET，是聚酯产业链的核心原料。",
        "futures": {"symbol": "TA0", "market": "郑州商品交易所"},
        "spot": {"symbol": "TA"},
    },
    {
        "group": "EG", "title": "乙二醇（PET 的原料）", "entry": "PET", "unit": "吨", "order": 70,
        "about": "大连商品交易所的乙二醇期货，代码 EG。乙二醇是 PET 的另一种主要原料。",
        "futures": {"symbol": "EG0", "market": "大连商品交易所"},
        "spot": {"symbol": "EG"},
    },
    {
        "group": "SC", "title": "原油", "entry": None, "unit": "桶", "order": 90,
        "about": "上海国际能源交易中心的原油期货，代码 SC，单位是元/桶。大多数塑料的源头是石油，"
                 "原油大涨大跌，一般会沿着产业链传到塑料价格上。",
        "futures": {"symbol": "SC0", "market": "上海国际能源交易中心"},
        "spot": None,
    },
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
