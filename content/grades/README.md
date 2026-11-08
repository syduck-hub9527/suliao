# 牌号数据文件说明

这个目录里的 `.yaml` 文件是网站“牌号库”的数据。容器每次启动时和知识内容一起自动导入（`python manage.py load_content`），重复导入是安全的。

- `companies.yaml`：公司（厂家）。
- 其他文件按材料分：`聚乙烯.yaml`、`聚丙烯.yaml`……每个文件里写若干牌号。
- 在网站后台改过的牌号（包括它的性能数据），不会被这里的文件再次覆盖。

## 三条铁规矩

1. **每个数字都要有出处。** 性能数据的 `source` 必须指向本牌号 `sources` 里的一个 `id`，没有出处的数字导入时会被丢掉。
2. **照抄原文。** 数值、单位、测试条件、标准按资料原样写，不自己换算、不补全。资料没写测试条件，就写“资料未注明”。
3. **查不到就空着。** 宁可少一行，也不要凭印象填。

## 核验状态怎么标

| 写法 | 网站上显示 | 什么时候用 |
|---|---|---|
| `verified` | 资料有官方出处 | 数字来自厂家自己的网站或厂家域名下的 TDS 文件 |
| `partial` | 转载的厂家资料 | 厂家 TDS 被数据库（UL Prospector、Material Data Center/CAMPUS）或经销商网站转载 |
| `unverified` | 资料待核实 | 贸易商网站、B2B 平台、来源不明的资料 |

牌号整体的 `verify` 写这个牌号大部分数据的情况；某一行和整体不同，就在那一行单独写 `verify`。

## 牌号字段

```yaml
grades:
  - code: 2805                 # 必填，照厂家写法
    full_name: Makrolon 2805   # 完整叫法（品牌 + 牌号）
    manufacturer: 科思创        # 只有一家厂家时写，要和 companies.yaml 里的 name 一致
    producers: 中国石化九江、镇海等多家   # 没有单一厂家的通用牌号（T30S、SG-5）写这个，不写 manufacturer
    brand: Makrolon
    material: PC               # 必填，对应知识词条的中文名或缩写，例：PC、PP-H、ABS
    product_type: resin        # resin 树脂 / compound 改性料 / masterbatch 母粒 / additive 助剂 / filler 填料 / recycled 再生料 / other
    grade_class: 注塑级          # 级别/用途
    lifecycle: active          # active 在产 / discontinued 停产 / unknown 未知
    verify: verified
    aliases: [PC 2805]         # 其他叫法，搜索时能搜到
    summary: 一句话介绍
    description: |             # 特点与用途，尽量照厂家原话的意思写；可以用 Markdown
      ……
    sources:
      - {id: c1, title: 资料标题, url: https://…, publisher: 谁发布的, kind: maker_web, accessed: 2026-11-08}
    properties:
      - {prop: MVR, value: "9", unit: cm³/10min, conditions: "300°C/1.2kg", standard: ISO 1133, source: c1}
```

### 来源 `kind`

`maker_doc` 厂家技术文件、`maker_web` 厂家官网、`standard` 标准原文、`cert` 认证机构、`exchange` 交易所/官方统计、`trader` 供应商/贸易商、`media` 行业媒体、`book` 书籍、`other` 其他（数据库等）。

### 性能数据字段

| 字段 | 说明 |
|---|---|
| prop | 性能指标，写中文名或缩写：MFR、MVR、HDT、密度、拉伸模量、等规指数、黏数、K 值…… |
| value | 原文写法，**一律加引号**。支持 `62`、`60～65`、`3.0±0.5`、`≥30`、`≤0.03`、`>1,000`，也可以是 `HB`、`R-110` 这类文字 |
| unit | 原文单位 |
| conditions | 测试条件，例：`230°C/2.16kg`、`23°C，缺口`、`1.8 MPa，未退火` |
| standard | 测试标准，例：`ISO 1133`、`ASTM D638`、`GB/T 3682` |
| type | `typical` 典型值（默认）/ `guaranteed` 保证值、规格值 / `range` 范围 / `measured` 实测值 |
| state | 尼龙等吸水材料必填：`dry` 干态 / `conditioned` 调湿后 |
| direction | 收缩率等区分方向时写：`flow` 平行于流动方向 / `cross` 垂直 |
| thickness_mm | 试样厚度（阻燃等级必须写） |
| source | 对应 `sources` 里的 id |
| verify | 这一行和牌号整体核验状态不同时写 |
| note | 备注，例：“原文同时写 475 kg/cm²” |
