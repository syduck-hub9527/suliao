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
    meta = obj._meta
    return reverse(f"admin:{meta.app_label}_{meta.model_name}_change", args=[obj.pk])


def _summary(obj) -> str:
    if isinstance(obj, m.Entry):
        return obj.one_liner or obj.get_kind_display()
    if isinstance(obj, m.Grade):
        parts = [str(obj.base_entry), obj.get_product_type_display()]
        if obj.manufacturer:
            parts.append(str(obj.manufacturer))
        return " · ".join(parts)
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

    return render(request, "kb/entry.html", {
        "entry": entry, "sections": sections, "relation_groups": groups, "aliases": aliases,
        "children": entry.children.order_by("name_zh"), "progress": progress,
        "statuses": m.EntryProgress.Status.choices, "path_item": path_item,
        "prev_item": prev_item, "next_item": next_item,
        "grades": entry.grades.select_related("manufacturer")[:30],
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
