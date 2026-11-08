"""
第一版搜索（数据量几千条以内够用）。

顺序：牌号精确 → 别名精确 → 别名包含 → 牌号包含。
每条结果都带“命中原因”，模糊结果明确标出来，不冒充精确结果。
一个写法对应多个东西时（例如 PIR），全部列出让人自己选。

以后数据多了、需要搜正文内容时，再加 SQLite FTS5 全文索引 + jieba 中文分词。
"""

from .models import Alias, Grade, normalize


def search(query: str, limit: int = 30):
    """返回 [(对象, 命中原因, 是否精确)]。对象可能是 词条/公司/品牌/牌号。"""
    q = (query or "").strip()
    key = normalize(q)
    if not key:
        return []

    results, seen = [], set()

    def add(obj, reason, exact):
        if obj is None:
            return
        k = (obj._meta.label, obj.pk)
        if k in seen:
            return
        seen.add(k)
        results.append((obj, reason, exact))

    # 1. 牌号精确：输入“141r”“141-R”都能找到 141R
    for g in Grade.objects.filter(code_norm=key).select_related("manufacturer", "brand"):
        add(g, "牌号精确匹配", True)

    # 2. 别名精确：缩写、中文名、英文名、俗称、商品名、旧名、CAS 号
    for a in Alias.objects.filter(norm=key).select_related("content_type"):
        add(a.target, f"{a.get_kind_display()}：{a.text}", True)

    # 3. 别名包含（模糊）
    if len(results) < limit:
        for a in Alias.objects.filter(norm__contains=key).exclude(norm=key).select_related("content_type")[: limit * 2]:
            add(a.target, f"模糊匹配 · {a.get_kind_display()}：{a.text}", False)

    # 4. 牌号包含（模糊）
    if len(results) < limit:
        for g in Grade.objects.filter(code_norm__contains=key).exclude(code_norm=key)[:limit]:
            add(g, "模糊匹配 · 牌号", False)

    return results[:limit]
