from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse

from . import models as m
from .search import search


def _summary(obj) -> str:
    """搜索结果下面那行小字。"""
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


@login_required
def home(request):
    query = request.GET.get("q", "").strip()
    results = []
    if query:
        for obj, reason, exact in search(query):
            meta = obj._meta
            results.append({
                "title": str(obj),
                "type": meta.verbose_name,
                "summary": _summary(obj),
                "reason": reason,
                "exact": exact,
                "url": reverse(f"admin:{meta.app_label}_{meta.model_name}_change", args=[obj.pk]),
            })

    stats = [
        ("词条", m.Entry.objects.count(), "kb_entry"),
        ("牌号", m.Grade.objects.count(), "kb_grade"),
        ("公司", m.Company.objects.count(), "kb_company"),
        ("性能数据", m.PropertyValue.objects.count(), "kb_propertyvalue"),
        ("问答记录", m.QARecord.objects.count(), "kb_qarecord"),
    ]
    return render(request, "kb/home.html", {
        "query": query,
        "results": results,
        "stats": [{"label": label, "count": count, "url": reverse(f"admin:{name}_changelist")}
                  for label, count, name in stats],
    })
