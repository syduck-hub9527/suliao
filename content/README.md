# 知识内容文件说明

这个目录里的 `.md` 文件就是网站上的知识内容。容器每次启动时会自动导入（`python manage.py load_content`），重复导入是安全的。

- 一个文件可以放多个词条；每个词条以 `---` 包起来的“头部”开始，后面是正文。
- 正文按 `## 小白解释`、`## 专业内容`、`## 常见误区` 分段；其他 `##` 标题会并入“专业内容”。
- **正文里不要单独一行写 `---`**，会被当成下一个词条的开头。
- 在网站后台改过的词条，不会被这里的文件再次覆盖。
- 所有内容由 AI 整理，网站上会标注“AI 整理 · 待核对”。

## 头部字段

| 字段 | 必填 | 说明 |
|---|---|---|
| kind | 是 | 词条种类：material 材料、additive 助剂/填料、process 加工工艺、property 性能指标、term 术语/概念、application 应用领域、regulation 法规/标准/认证、defect 成型缺陷 |
| name_zh | 是 | 中文名（同一种类里不能重复） |
| name_en | | 英文名 |
| abbr | | 最常用的缩写 |
| aliases | | 其他叫法。直接写文字默认是“行业俗称”；也可以写 `{text: 9003-07-0, kind: cas}`。kind 可选：abbr、name_zh、name_en、nickname、trade、former、typo、cas、other |
| category | | 分类路径，例如 `[通用塑料, 聚烯烃]` |
| parent | | 上级词条的名字或缩写 |
| difficulty | | 1 入门、2 基础、3 进阶、4 专业 |
| one_liner | | 一句话解释 |
| related | | 相关词条。直接写名字是“相关”；也可以写 `{to: PA66, kind: confusable}`。kind 可选：related、confusable 容易混淆、used_with 常搭配使用、used_in 用于、alternative 可能替代 |
| path | | 放进学习路线：`{stage: "第 1 阶段：认识塑料行业", order: 10, goal: 学完能……}` |

## 目录

| 目录 | 对应学习路线 |
|---|---|
| 01-入门概念 | 第 1 阶段：认识塑料行业 |
| 02-常见塑料 | 第 2 阶段：认识常见塑料 |
| 03-看懂牌号与物性表 | 第 3 阶段：看懂牌号和物性表 |
| 04-更多塑料原料 | 第 4 阶段：认识更多塑料原料 |
| grades/ | 牌号库数据（YAML 格式，见 grades/README.md） |
