from collections import OrderedDict

from django.db.models import Count, Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST


from . import models as m
from .content import LEARNING_PATH_NAME
from .render import TermLinker
from .search import search


# ---------------- 小工具 ----------------

def _object_url(obj) -> str:
    if isinstance(obj, m.Entry):
        return reverse("kb:entry", args=[obj.pk])
    if isinstance(obj, m.Grade):
        return reverse("kb:grade", args=[obj.pk])
    if isinstance(obj, m.Company):
        return reverse("kb:company", args=[obj.pk])
    if isinstance(obj, m.Brand) and obj.owner_id:
        return reverse("kb:company", args=[obj.owner_id])
    meta = obj._meta
    return reverse(f"admin:{meta.app_label}_{meta.model_name}_change", args=[obj.pk])


def _summary(obj) -> str:
    if isinstance(obj, m.Entry):
        return obj.one_liner or obj.get_kind_display()
    if isinstance(obj, m.Grade):
        parts = [p for p in [str(obj.manufacturer or "多家生产"), str(obj.base_entry), obj.grade_class] if p]
        return " · ".join(parts) + (f" — {obj.summary}" if obj.summary else "")
    if isinstance(obj, m.Company):
        return obj.country or "公司"
    if isinstance(obj, m.Brand):
        return f"品牌 · {obj.owner}" if obj.owner else "品牌"
    return ""


def _learning_path():
    return m.LearningPath.objects.filter(name=LEARNING_PATH_NAME).first()


def _progress_map(entry_ids) -> dict:
    return {p.entry_id: p for p in m.EntryProgress.objects.filter(entry_id__in=entry_ids)}


def _path_stages(path):
    """把学习路线按阶段分组，并附上每个词条的学习状态。"""
    if path is None:
        return []
    items = list(path.items.select_related("entry").order_by("order", "pk"))
    progress = _progress_map([i.entry_id for i in items])
    stages = OrderedDict()
    for item in items:
        p = progress.get(item.entry_id)
        status = p.status if p else m.EntryProgress.Status.NEW
        stages.setdefault(item.stage, []).append({"item": item, "entry": item.entry, "status": status,
                                                  "status_label": m.EntryProgress.Status(status).label})
    result = []
    for name, rows in stages.items():
        done = sum(1 for r in rows if r["status"] == m.EntryProgress.Status.MASTERED)
        result.append({"name": name, "rows": rows, "done": done, "total": len(rows),
                       "percent": round(done * 100 / len(rows)) if rows else 0})
    return result


# ---------------- 页面 ----------------

def home(request):
    path = _learning_path()
    stages = _path_stages(path)
    total = sum(s["total"] for s in stages)
    done = sum(s["done"] for s in stages)
    next_up = None
    for stage in stages:
        for row in stage["rows"]:
            if row["status"] != m.EntryProgress.Status.MASTERED:
                next_up = row
                break
        if next_up:
            break

    kinds = (m.Entry.objects.values("kind").annotate(n=Count("pk")).order_by("kind"))
    kind_tiles = [{"kind": k["kind"], "label": m.EntryKind(k["kind"]).label, "count": k["n"]} for k in kinds]
    recent = (m.EntryProgress.objects.filter(last_viewed_at__isnull=False)
              .select_related("entry").order_by("-last_viewed_at")[:8])
    return render(request, "kb/home.html", {
        "stages": stages, "total": total, "done": done,
        "percent": round(done * 100 / total) if total else 0,
        "next_up": next_up, "kind_tiles": kind_tiles, "recent": recent,
        "entry_count": m.Entry.objects.count(),
        "grade_count": m.Grade.objects.count(),
    })


def search_view(request):
    query = request.GET.get("q", "").strip()
    results = []
    if query:
        for obj, reason, exact in search(query):
            results.append({
                "title": str(obj), "type": obj._meta.verbose_name, "summary": _summary(obj),
                "reason": reason, "exact": exact, "url": _object_url(obj),
            })
        # 名称里搜不到时，再到正文里找找
        if len(results) < 5:
            seen = {r["url"] for r in results}
            body_hits = m.Entry.objects.filter(
                Q(one_liner__icontains=query) | Q(easy_text__icontains=query) |
                Q(pro_text__icontains=query) | Q(pitfalls__icontains=query))[:10]
            for e in body_hits:
                url = _object_url(e)
                if url not in seen:
                    results.append({"title": str(e), "type": "词条", "summary": e.one_liner or "",
                                    "reason": "正文里提到", "exact": False, "url": url})
    return render(request, "kb/search.html", {"query": query, "results": results})


def entry_detail(request, pk):
    entry = get_object_or_404(m.Entry.objects.select_related("category", "parent"), pk=pk)
    progress, _ = m.EntryProgress.objects.get_or_create(entry=entry)
    progress.view_count += 1
    progress.last_viewed_at = timezone.now()
    progress.save(update_fields=["view_count", "last_viewed_at"])

    linker = TermLinker(exclude_entry_id=entry.pk)
    sections = []
    for title, text, css in [("小白解释", entry.easy_text, "easy"), ("专业内容", entry.pro_text, "pro"),
                             ("常见误区", entry.pitfalls, "pitfall")]:
        if text:
            sections.append({"title": title, "html": linker.render(text), "css": css})

    # 相关词条：按关系分组，两个方向都显示
    groups = OrderedDict()
    for rel in entry.relations_out.select_related("to_entry"):
        groups.setdefault(rel.get_kind_display(), []).append({"entry": rel.to_entry, "note": rel.note})
    for rel in entry.relations_in.select_related("from_entry"):
        label = rel.get_kind_display() if rel.kind in ("related", "confusable", "alternative") else "相关"
        groups.setdefault(label, []).append({"entry": rel.from_entry, "note": rel.note})
    for label in groups:
        uniq, seen = [], set()
        for row in groups[label]:
            if row["entry"].pk not in seen:
                seen.add(row["entry"].pk)
                uniq.append(row)
        groups[label] = uniq

    own_names = {m.normalize(x) for x in [entry.name_zh, entry.name_en, entry.abbr] if x}
    aliases = [a for a in entry.aliases.all().order_by("kind", "text") if a.norm not in own_names]

    path_item = entry.path_items.select_related("path").first()
    prev_item = next_item = None
    if path_item:
        siblings = list(path_item.path.items.select_related("entry").order_by("order", "pk"))
        idx = [s.pk for s in siblings].index(path_item.pk)
        prev_item = siblings[idx - 1] if idx > 0 else None
        next_item = siblings[idx + 1] if idx + 1 < len(siblings) else None

    makers = maker_groups(m.Grade.objects.filter(Q(base_entry=entry) | Q(base_entry__parent=entry))
                          .select_related("manufacturer", "base_entry", "brand"))
    return render(request, "kb/entry.html", {
        "entry": entry, "sections": sections, "relation_groups": groups, "aliases": aliases,
        "children": entry.children.order_by("name_zh"), "progress": progress,
        "statuses": m.EntryProgress.Status.choices, "path_item": path_item,
        "prev_item": prev_item, "next_item": next_item,
        "makers": makers,
        "maker_count": sum(1 for r in makers if r["company"]),
        "grade_total": sum(len(r["grades"]) for r in makers),
        "show_subtype": entry.children.exists(),
        "admin_url": reverse("admin:kb_entry_change", args=[entry.pk]),
    })


@require_POST
def entry_progress(request, pk):
    entry = get_object_or_404(m.Entry, pk=pk)
    progress, _ = m.EntryProgress.objects.get_or_create(entry=entry)
    status = request.POST.get("status")
    if status in m.EntryProgress.Status.values:
        progress.status = status
        progress.last_reviewed_at = timezone.now()
    if "star" in request.POST:
        progress.starred = request.POST.get("star") == "1"
    progress.save()
    return HttpResponseRedirect(reverse("kb:entry", args=[pk]) + "#progress")


def browse(request, kind=None):
    if kind is None:
        kinds = (m.Entry.objects.values("kind").annotate(n=Count("pk")).order_by("kind"))
        tiles = [{"kind": k["kind"], "label": m.EntryKind(k["kind"]).label, "count": k["n"]} for k in kinds]
        return render(request, "kb/browse.html", {"tiles": tiles})

    if kind not in m.EntryKind.values:
        return HttpResponseRedirect(reverse("kb:browse"))
    entries = list(m.Entry.objects.filter(kind=kind).order_by("name_zh"))
    progress = _progress_map([e.pk for e in entries])
    by_cat = {}
    for e in entries:
        by_cat.setdefault(e.category_id, []).append({"entry": e, "progress": progress.get(e.pk)})

    def build(parent_id, depth):
        nodes = []
        for cat in m.Category.objects.filter(kind=kind, parent_id=parent_id).order_by("order", "name"):
            children = build(cat.pk, depth + 1)
            rows = by_cat.get(cat.pk, [])
            if rows or children:
                nodes.append({"cat": cat, "rows": rows, "children": children, "depth": depth})
        return nodes

    return render(request, "kb/browse_kind.html", {
        "kind": kind, "label": m.EntryKind(kind).label, "tree": build(None, 0),
        "uncategorized": by_cat.get(None, []), "count": len(entries),
    })


def learn(request):
    path = _learning_path()
    stages = _path_stages(path)
    confused = (m.EntryProgress.objects.filter(status=m.EntryProgress.Status.CONFUSED)
                .select_related("entry").order_by("-last_reviewed_at"))
    starred = m.EntryProgress.objects.filter(starred=True).select_related("entry").order_by("entry__name_zh")
    total = sum(s["total"] for s in stages)
    done = sum(s["done"] for s in stages)
    return render(request, "kb/learn.html", {
        "path": path, "stages": stages, "confused": confused, "starred": starred,
        "total": total, "done": done, "percent": round(done * 100 / total) if total else 0,
    })


# ---------------- 厂商分组 ----------------

# 国家/地区 → 大区，以及大区的显示顺序（先国内，再按亚洲、中东、欧洲、美洲）
REGIONS = ["中国大陆", "中国台湾", "日本", "韩国", "东南亚和南亚", "中东", "欧洲", "北美", "其他"]
_COUNTRY_REGION = {
    "中国": "中国大陆", "中国大陆": "中国大陆", "中国香港": "中国大陆", "中国台湾": "中国台湾",
    "日本": "日本", "韩国": "韩国",
    "泰国": "东南亚和南亚", "新加坡": "东南亚和南亚", "马来西亚": "东南亚和南亚", "印度尼西亚": "东南亚和南亚",
    "印度": "东南亚和南亚", "越南": "东南亚和南亚",
    "沙特阿拉伯": "中东", "阿联酋": "中东", "伊朗": "中东", "卡塔尔": "中东", "阿曼": "中东", "以色列": "中东",
    "科威特": "中东",
    "德国": "欧洲", "法国": "欧洲", "比利时": "欧洲", "荷兰": "欧洲", "瑞士": "欧洲", "英国": "欧洲",
    "意大利": "欧洲", "奥地利": "欧洲", "瑞典": "欧洲", "芬兰": "欧洲", "西班牙": "欧洲", "挪威": "欧洲",
    "丹麦": "欧洲", "卢森堡": "欧洲", "波兰": "欧洲",
    "美国": "北美", "加拿大": "北美", "墨西哥": "北美",
}


def region_of(country: str) -> str:
    return _COUNTRY_REGION.get((country or "").strip(), "其他")


def _region_rank(country: str) -> int:
    return REGIONS.index(region_of(country))


def maker_groups(grades):
    """把一批牌号按厂商分组：[{company, region, brands, grades}]，多家生产的通用牌号放最后一组。"""
    groups, common = OrderedDict(), []
    for g in grades:
        if g.manufacturer_id is None:
            common.append(g)
            continue
        row = groups.setdefault(g.manufacturer_id, {"company": g.manufacturer, "brands": [], "grades": []})
        row["grades"].append(g)
        if g.brand_id and g.brand.name not in row["brands"]:
            row["brands"].append(g.brand.name)
    rows = list(groups.values())
    for row in rows:
        row["region"] = region_of(row["company"].country)
        row["grades"].sort(key=lambda g: g.code_norm)
    rows.sort(key=lambda r: (_region_rank(r["company"].country), -len(r["grades"]), r["company"].name))
    if common:
        rows.append({"company": None, "region": "", "brands": [], "grades": sorted(common, key=lambda g: g.code_norm)})
    return rows


# ---------------- 牌号 ----------------

# 性能数据按“先基础、再加工、再力学和热”的阅读顺序分组，和大多数 TDS 的排法一致
_GROUP_ORDER = {g: i for i, g in enumerate(["basic", "processing", "mechanical", "thermal", "flame",
                                             "electrical", "optical", "other"])}


def _mfr_map(grade_ids) -> dict:
    """每个牌号的熔融指数（列表里快速参考用）。"""
    result = {}
    qs = (m.PropertyValue.objects.filter(grade_id__in=grade_ids)
          .filter(Q(prop__abbr__in=["MFR", "MVR"]))
          .select_related("prop").order_by("prop__order", "pk"))
    for pv in qs:
        if pv.grade_id not in result:
            result[pv.grade_id] = f"{pv.value_text} {pv.unit}".strip() + (f"（{pv.conditions}）" if pv.conditions else "")
    return result


def grades_list(request):
    grades = list(m.Grade.objects.select_related("base_entry", "base_entry__parent", "manufacturer"))
    mfr = _mfr_map([g.pk for g in grades])
    path_order = dict(m.PathItem.objects.values_list("entry_id", "order"))
    families = OrderedDict()
    for g in grades:
        family = g.base_entry.parent or g.base_entry
        families.setdefault(family, []).append({"grade": g, "mfr": mfr.get(g.pk, "")})
    ordered = sorted(families.items(), key=lambda kv: (path_order.get(kv[0].pk, 10**6), kv[0].name_zh))
    for _, rows in ordered:
        rows.sort(key=lambda r: (r["grade"].base_entry.name_zh, r["grade"].code_norm))
    return render(request, "kb/grades.html", {"families": ordered, "count": len(grades)})


def grade_detail(request, pk):
    grade = get_object_or_404(m.Grade.objects.select_related("base_entry", "base_entry__parent", "manufacturer",
                                                             "brand"), pk=pk)
    linker = TermLinker()
    description = linker.render(grade.description) if grade.description else ""

    groups = OrderedDict()
    pvs = sorted(grade.property_values.select_related("prop", "prop__entry", "source", "standard"),
                 key=lambda pv: (_GROUP_ORDER.get(pv.prop.group, 99), pv.prop.order, pv.pk))
    for pv in pvs:
        groups.setdefault(pv.prop.get_group_display(), []).append(pv)

    own = {m.normalize(x) for x in [grade.code, grade.full_name] if x}
    aliases = [a for a in grade.aliases.all() if a.norm not in own]

    plants = grade.plants.select_related("company").order_by("company__name", "name")
    plant_links = grade.gradeplant_set.select_related("plant", "source").order_by("plant__company__name", "plant__name")
    documents = grade.documents.select_related("company").order_by("kind", "title")

    family = grade.base_entry.parent or grade.base_entry
    siblings = (m.Grade.objects.filter(Q(base_entry=family) | Q(base_entry__parent=family))
                .exclude(pk=grade.pk).select_related("manufacturer", "base_entry").order_by("base_entry__name_zh",
                                                                                           "code_norm")[:16])
    return render(request, "kb/grade.html", {
        "grade": grade, "description": description, "groups": groups, "aliases": aliases,
        "sources": grade.sources.all().order_by("title"), "siblings": siblings, "family": family,
        "admin_url": reverse("admin:kb_grade_change", args=[grade.pk]),
        "plants": plants, "plant_links": plant_links, "documents": documents,
    })


def company_detail(request, pk):
    company = get_object_or_404(m.Company.objects.select_related("parent"), pk=pk)
    grades = list(company.grades.select_related("base_entry", "brand").order_by("base_entry__name_zh", "code_norm"))
    by_material = OrderedDict()
    for g in grades:
        by_material.setdefault(g.base_entry, []).append(g)
    return render(request, "kb/company.html", {
        "company": company, "grades": grades, "by_material": list(by_material.items()), "types": company.types.all(),
        "region": region_of(company.country),
        "brands": company.brands.all(), "subsidiaries": company.subsidiaries.all(),
        "plants": company.plants.prefetch_related("sources").order_by("city", "name"),
        "documents": company.documents.prefetch_related("grades").order_by("kind", "title"),
        "admin_url": reverse("admin:kb_company_change", args=[company.pk]),
    })


# ---------------- 原料总览、厂商一览 ----------------

def materials(request):
    """原料总览：按大类列出每种材料、主要厂商和收录的牌号数。"""
    entries = list(m.Entry.objects.filter(kind=m.EntryKind.MATERIAL).select_related("category", "parent"))
    grades = list(m.Grade.objects.select_related("manufacturer", "base_entry"))
    own = {}
    for g in grades:
        for key in {g.base_entry_id, g.base_entry.parent_id}:
            if key:
                own.setdefault(key, []).append(g)
    progress = _progress_map([e.pk for e in entries])

    def row(e):
        gs = own.get(e.pk, [])
        counts = {}
        for g in gs:
            if g.manufacturer_id:
                counts.setdefault(g.manufacturer, 0)
                counts[g.manufacturer] += 1
        makers = sorted(counts, key=lambda c: (_region_rank(c.country), -counts[c], c.name))
        return {"entry": e, "grades": len(gs), "makers": makers[:6], "more": max(0, len(makers) - 6),
                "maker_count": len(makers), "common": sum(1 for g in gs if not g.manufacturer_id),
                "progress": progress.get(e.pk)}

    by_cat = OrderedDict()
    for e in entries:
        by_cat.setdefault(e.category_id, []).append(e)
    path_order = dict(m.PathItem.objects.values_list("entry_id", "order"))

    def sort_entries(items):
        # 父类在前、子类紧跟其后
        tops = sorted([e for e in items if not e.parent_id or e.parent_id not in {x.pk for x in items}],
                      key=lambda e: (path_order.get(e.pk, 10**6), e.name_zh))
        out = []
        for t in tops:
            out.append((t, False))
            kids = sorted([e for e in items if e.parent_id == t.pk], key=lambda e: (path_order.get(e.pk, 10**6), e.name_zh))
            out.extend((k, True) for k in kids)
        return out

    sections = []
    for top in m.Category.objects.filter(kind=m.EntryKind.MATERIAL, parent=None).order_by("order", "name"):
        cats = [top] + list(m.Category.objects.filter(parent=top).order_by("order", "name"))
        blocks = []
        for cat in cats:
            items = by_cat.get(cat.pk, [])
            if items:
                rows = []
                for e, is_child in sort_entries(items):
                    r = row(e)
                    r["is_child"] = is_child
                    rows.append(r)
                blocks.append({"name": "" if cat == top else cat.name, "rows": rows})
        if blocks:
            sections.append({"cat": top, "blocks": blocks, "count": sum(len(b["rows"]) for b in blocks)})
    return render(request, "kb/materials.html", {
        "sections": sections, "count": len(entries), "grade_count": len(grades),
        "company_count": m.Company.objects.filter(grades__isnull=False).distinct().count(),
    })


def additives(request):
    """助剂总览：按助剂类别展示知识词条及已收录商品牌号数量。"""
    entries = list(
        m.Entry.objects.filter(kind=m.EntryKind.ADDITIVE)
        .select_related("category", "parent").order_by("category__order", "category__name", "name_zh")
    )
    grades = list(
        m.Grade.objects.filter(base_entry__kind=m.EntryKind.ADDITIVE)
        .select_related("manufacturer", "base_entry")
    )
    by_entry = {}
    for grade in grades:
        by_entry.setdefault(grade.base_entry_id, []).append(grade)

    grouped = OrderedDict()
    for entry in entries:
        section = entry.category.name if entry.category_id else "未分类"
        rows = grouped.setdefault(section, [])
        rows.append({"entry": entry, "grade_count": len(by_entry.get(entry.pk, []))})

    sections = [{"name": name, "rows": rows} for name, rows in grouped.items()]
    return render(request, "kb/additives.html", {
        "sections": sections,
        "count": len(entries),
        "grade_count": len(grades),
        "company_count": m.Company.objects.filter(grades__base_entry__kind=m.EntryKind.ADDITIVE)
            .distinct().count(),
    })


def documents(request):
    """技术文件中心：按 TDS、SDS、检测报告等类型分组。"""
    docs = list(
        m.Document.objects.select_related("company").prefetch_related("grades")
        .order_by("kind", "title")
    )
    grouped = OrderedDict()
    for doc in docs:
        grouped.setdefault(doc.get_kind_display(), []).append(doc)
    groups = [{"label": label, "documents": items} for label, items in grouped.items()]
    return render(request, "kb/documents.html", {"groups": groups, "count": len(docs)})


def companies(request):
    """厂商一览：按国家/地区分组，每家列出品牌和生产的材料。"""
    rows = []
    for c in m.Company.objects.prefetch_related("brands", "grades__base_entry").order_by("name"):
        gs = list(c.grades.all())
        mats = OrderedDict()
        for g in sorted(gs, key=lambda g: g.base_entry.abbr or g.base_entry.name_zh):
            mats.setdefault(g.base_entry_id, g.base_entry)
        rows.append({"company": c, "region": region_of(c.country), "grades": len(gs),
                     "materials": list(mats.values()), "brands": [b.name for b in c.brands.all()]})
    groups = OrderedDict((r, []) for r in REGIONS)
    for r in rows:
        groups[r["region"]].append(r)
    for items in groups.values():
        items.sort(key=lambda r: (-r["grades"], r["company"].name))
    return render(request, "kb/companies.html", {
        "groups": [(k, v) for k, v in groups.items() if v], "count": len(rows),
    })
