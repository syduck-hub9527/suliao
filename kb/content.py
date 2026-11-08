"""
知识内容文件的读取和导入。

content/ 目录下的每个 .md 文件可以放一个或多个词条。每个词条的格式：

    ---
    kind: material              # 词条种类，见 content/README.md
    name_zh: 聚丙烯
    name_en: Polypropylene
    abbr: PP
    aliases: [百折胶, {text: 9003-07-0, kind: cas}]
    category: [通用塑料, 聚烯烃]  # 分类路径
    parent: 聚烯烃               # 上级词条（可选）
    difficulty: 1               # 1 入门 2 基础 3 进阶 4 专业
    one_liner: 一句话解释
    related: [PE, {to: 聚乙烯, kind: confusable}]
    path: {stage: "第 2 阶段：认识常见塑料", order: 20, goal: "学完能……"}
    ---
    ## 小白解释
    ……
    ## 专业内容
    ……
    ## 常见误区
    ……

注意：正文里不要单独一行写 ---（会被当成下一个词条的开头）。
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from . import models as m

_HEADER_RE = re.compile(r"^---[ \t]*\n(.*?)\n---[ \t]*\n", re.S | re.M)

SECTION_FIELDS = {"小白解释": "easy_text", "专业内容": "pro_text", "常见误区": "pitfalls"}
CONTENT_FIELDS = ["name_en", "abbr", "one_liner", "difficulty", "easy_text", "pro_text", "pitfalls", "category_id"]

LEARNING_PATH_NAME = "入行学习路线"
AI_SOURCE_TITLE = "Claude 整理的知识内容（AI 生成，待核对）"


class ContentError(Exception):
    pass


# ---------------- 读取文件 ----------------

def _split_sections(body: str) -> dict:
    """按“## 标题”切分正文。认识的标题放进对应字段，其他标题并入“专业内容”。"""
    result = {f: [] for f in SECTION_FIELDS.values()}
    current, extra = None, []
    for line in body.split("\n"):
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            title = heading.group(1)
            if title in SECTION_FIELDS:
                current = SECTION_FIELDS[title]
                continue
            current = "pro_text"
            result[current].append(f"### {title}")
            continue
        if current is None:
            extra.append(line)
        else:
            result[current].append(line)
    out = {k: "\n".join(v).strip() for k, v in result.items()}
    lead = "\n".join(extra).strip()
    if lead:
        out["easy_text"] = (lead + "\n\n" + out["easy_text"]).strip()
    return out


def parse_text(text: str, source_name: str = "") -> list[dict]:
    text = text.replace("\r\n", "\n")
    matches = list(_HEADER_RE.finditer(text))
    items = []
    for i, match in enumerate(matches):
        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as exc:
            raise ContentError(f"{source_name}: 第 {i + 1} 个词条的头部格式有误：{exc}") from exc
        if not isinstance(meta, dict):
            raise ContentError(f"{source_name}: 第 {i + 1} 个词条的头部不是“键: 值”格式")
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        meta["_sections"] = _split_sections(text[match.end():end])
        meta["_source"] = source_name
        items.append(meta)
    return items


def read_content_dir(content_dir: Path) -> list[dict]:
    items = []
    for path in sorted(Path(content_dir).rglob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        items.extend(parse_text(path.read_text(encoding="utf-8"), str(path.relative_to(content_dir))))
    return items


# ---------------- 导入数据库 ----------------

def _fingerprint(values: dict) -> str:
    payload = json.dumps({k: values.get(k) for k in CONTENT_FIELDS}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _entry_values(entry) -> dict:
    return {k: getattr(entry, k) for k in CONTENT_FIELDS}


@dataclass
class ImportReport:
    created: list = field(default_factory=list)
    updated: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    skipped_edited: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def summary(self) -> str:
        return (f"新增 {len(self.created)} 条，更新 {len(self.updated)} 条，未变 {len(self.unchanged)} 条，"
                f"后台改过而跳过 {len(self.skipped_edited)} 条，提醒 {len(self.warnings)} 条")


class Importer:
    def __init__(self, items: list[dict]):
        self.items = items
        self.report = ImportReport()
        self.entry_ct = ContentType.objects.get_for_model(m.Entry)

    # —— 工具 ——
    def _category(self, kind, path):
        if not path:
            return None
        if isinstance(path, str):
            path = [path]
        parent = None
        for name in path:
            cat = m.Category.objects.filter(kind=kind, name=str(name), parent=parent).first()
            if cat is None:
                siblings = m.Category.objects.filter(kind=kind, parent=parent).count()
                cat = m.Category.objects.create(kind=kind, name=str(name), parent=parent, order=siblings * 10)
            parent = cat
        return parent

    def _find_entry(self, ref: str, prefer_kind=None):
        ref = str(ref).strip()
        qs = m.Entry.objects.filter(name_zh=ref)
        if prefer_kind and qs.filter(kind=prefer_kind).exists():
            qs = qs.filter(kind=prefer_kind)
        found = list(qs[:2])
        if len(found) == 1:
            return found[0]
        ids = list(m.Alias.objects.filter(content_type=self.entry_ct, norm=m.normalize(ref))
                   .values_list("object_id", flat=True).distinct()[:2])
        if len(ids) == 1:
            return m.Entry.objects.get(pk=ids[0])
        return None

    # —— 主流程 ——
    @transaction.atomic
    def run(self) -> ImportReport:
        source, _ = m.Source.objects.get_or_create(kind=m.Source.Kind.AI, title=AI_SOURCE_TITLE)
        entries = []
        seen = set()
        for meta in self.items:
            entry = self._import_entry(meta, source, seen)
            entries.append((entry, meta))
        for entry, meta in entries:
            if entry is not None:
                self._import_links(entry, meta)
                if entry.kind == m.EntryKind.PROPERTY:
                    self._link_property_definition(entry)
        return self.report

    def _link_property_definition(self, entry):
        """性能指标词条 ↔ 预置的性能指标定义（按缩写或中文名对上），让性能表里的指标可以点进讲解页。"""
        cond = m.PropertyDefinition.objects.filter(name_zh=entry.name_zh)
        if entry.abbr:
            cond = cond | m.PropertyDefinition.objects.filter(abbr__iexact=entry.abbr)
        cond.filter(entry__isnull=True).update(entry=entry)

    def _import_entry(self, meta, source, seen):
        where = meta.get("_source", "")
        kind, name = meta.get("kind"), str(meta.get("name_zh", "")).strip()
        if kind not in m.EntryKind.values or not name:
            self.report.warnings.append(f"{where}: 缺少有效的 kind 或 name_zh（{kind!r} {name!r}），已跳过")
            return None
        if (kind, name) in seen:
            self.report.warnings.append(f"{where}: 词条“{name}”重复出现，只导入第一次")
            return None
        seen.add((kind, name))

        sections = meta.get("_sections", {})
        category = self._category(kind, meta.get("category"))
        values = {
            "name_en": str(meta.get("name_en") or "").strip(),
            "abbr": str(meta.get("abbr") or "").strip(),
            "one_liner": str(meta.get("one_liner") or "").strip(),
            "difficulty": int(meta.get("difficulty") or 1),
            "easy_text": sections.get("easy_text", ""),
            "pro_text": sections.get("pro_text", ""),
            "pitfalls": sections.get("pitfalls", ""),
            "category_id": category.pk if category else None,
        }
        new_hash = _fingerprint(values)

        entry = m.Entry.objects.filter(kind=kind, name_zh=name).first()
        if entry is None:
            entry = m.Entry(kind=kind, name_zh=name, origin=m.ContentOrigin.AI_DRAFT,
                            verify_status=m.VerifyStatus.UNVERIFIED, imported_hash=new_hash, **values)
            entry.save()
            self.report.created.append(name)
        elif entry.imported_hash and _fingerprint(_entry_values(entry)) != entry.imported_hash:
            self.report.skipped_edited.append(name)
        elif entry.imported_hash == new_hash:
            self.report.unchanged.append(name)
        else:
            for k, v in values.items():
                setattr(entry, k, v)
            entry.imported_hash = new_hash
            entry.save()
            self.report.updated.append(name)

        entry.sources.add(source)
        for alias in meta.get("aliases") or []:
            if isinstance(alias, dict):
                text, akind = str(alias.get("text", "")).strip(), alias.get("kind", m.Alias.Kind.OTHER)
            else:
                text, akind = str(alias).strip(), m.Alias.Kind.NICKNAME
            if akind not in m.Alias.Kind.values:
                akind = m.Alias.Kind.OTHER
            if akind == m.Alias.Kind.CAS and not m.is_valid_cas(text):
                self.report.warnings.append(f"{where}: “{name}”的 CAS 号 {text} 校验不通过，已跳过")
                continue
            if m.normalize(text):
                m.Alias.objects.get_or_create(content_type=self.entry_ct, object_id=entry.pk,
                                              norm=m.normalize(text), defaults={"text": text, "kind": akind})
        return entry

    def _import_links(self, entry, meta):
        where = meta.get("_source", "")
        parent_ref = meta.get("parent")
        if parent_ref:
            parent = self._find_entry(parent_ref, entry.kind)
            if parent is None:
                self.report.warnings.append(f"{where}: “{entry.name_zh}”的上级“{parent_ref}”没找到")
            elif parent.pk != entry.pk and entry.parent_id != parent.pk:
                entry.parent = parent
                entry.save(update_fields=["parent"])

        for rel in meta.get("related") or []:
            if isinstance(rel, dict):
                ref, kind, note = rel.get("to"), rel.get("kind", "related"), rel.get("note", "")
            else:
                ref, kind, note = rel, "related", ""
            if kind not in m.EntryRelation.Kind.values:
                kind = "related"
            target = self._find_entry(ref)
            if target is None:
                self.report.warnings.append(f"{where}: “{entry.name_zh}”的相关词条“{ref}”没找到")
                continue
            if target.pk == entry.pk:
                continue
            exists = m.EntryRelation.objects.filter(
                from_entry__in=[entry, target], to_entry__in=[entry, target], kind=kind).exists()
            if not exists:
                m.EntryRelation.objects.create(from_entry=entry, to_entry=target, kind=kind, note=str(note or ""))

        path = meta.get("path")
        if path:
            lp, _ = m.LearningPath.objects.get_or_create(
                name=LEARNING_PATH_NAME,
                defaults={"description": "从零开始入行塑料行业的学习顺序，按阶段一步步来。"},
            )
            m.PathItem.objects.update_or_create(
                path=lp, entry=entry,
                defaults={"stage": str(path.get("stage", "")), "order": int(path.get("order", 0)),
                          "goal": str(path.get("goal", ""))},
            )
