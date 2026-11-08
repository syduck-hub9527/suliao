"""
牌号数据的读取和导入。

content/grades/ 目录下的 .yaml 文件：
- companies.yaml 里写公司（厂家）；
- 其他文件按材料分，写牌号。格式见 content/grades/README.md。

规则：
- 每个性能数值都必须带来源（sources 里的 id）；
- 只写资料里查得到的数字，查不到的留空；
- 在后台改过的牌号（包括它的性能数据）不会被再次导入覆盖。
"""

import datetime
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q

from . import models as m
from .content import ContentError

GRADE_FIELDS = ["full_name", "product_type", "grade_class", "summary", "description", "producers_note",
                "base_entry_id", "brand_id", "lifecycle", "verify_status"]

# 状态调节、方向的几种写法（YAML 里写中文或英文都行）
_CONDITIONING = {"dry": "dry", "干态": "dry", "conditioned": "conditioned", "cond": "conditioned",
                 "调湿": "conditioned", "调湿后": "conditioned", "other": "other", "其他": "other"}
_DIRECTION = {"flow": "flow", "平行": "flow", "平行于流动方向": "flow",
              "cross": "cross", "垂直": "cross", "垂直于流动方向": "cross"}

_N = r"(-?\d+(?:,\d{3})*(?:\.\d+)?)"
_RANGE_RE = re.compile(rf"^\s*{_N}\s*[～~–—-]\s*{_N}\s*$")
_PM_RE = re.compile(rf"^\s*{_N}\s*±\s*{_N}\s*$")
_BOUND_RE = re.compile(rf"^\s*(≥|>=|>|≤|<=|<)\s*{_N}\s*$")
_NUM_RE = re.compile(rf"^\s*{_N}\s*$")


def read_grades_dir(grades_dir: Path) -> tuple[list[dict], list[dict]]:
    companies, grades = [], []
    for path in sorted(Path(grades_dir).glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ContentError(f"{path.name}: YAML 格式有误：{exc}") from exc
        for c in data.get("companies") or []:
            c["_source"] = path.name
            companies.append(c)
        for g in data.get("grades") or []:
            g["_source"] = path.name
            grades.append(g)
    return companies, grades


def _f(text: str) -> float:
    return float(text.replace(",", ""))


def _parse_value(raw: str):
    """从原文写法里解析出 (数值, 最小值, 最大值)。原文照样保留；解析不了的三项都是 None。

    "62" → 数值 62；"60～65" → 范围；"3.0±0.5" → 2.5～3.5；
    "≥30" → 最小值 30；"≤0.03" → 最大值 0.03；">1,000" → 最小值 1000。
    """
    text = str(raw).strip()
    if m_ := _RANGE_RE.match(text):
        lo, hi = _f(m_.group(1)), _f(m_.group(2))
        return None, min(lo, hi), max(lo, hi)
    if m_ := _PM_RE.match(text):
        mid, tol = _f(m_.group(1)), abs(_f(m_.group(2)))
        return None, round(mid - tol, 10), round(mid + tol, 10)
    if m_ := _BOUND_RE.match(text):
        val = _f(m_.group(2))
        return (None, val, None) if m_.group(1) in ("≥", ">=", ">") else (None, None, val)
    if m_ := _NUM_RE.match(text):
        return _f(m_.group(1)), None, None
    return None, None, None


def _fp(fields: dict, pvs: list) -> str:
    payload = json.dumps({"f": {k: fields.get(k) for k in GRADE_FIELDS}, "p": sorted(map(list, pvs), key=str)},
                         ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _pv_tuple(pv) -> tuple:
    return (pv.prop_id, pv.value_text, pv.value_num, pv.value_min, pv.value_max, pv.unit, pv.conditions,
            pv.standard_text, pv.value_type, pv.thickness_mm, pv.conditioning, pv.direction, pv.source_id,
            pv.verify_status, pv.note)


@dataclass
class GradeImportReport:
    created: list = field(default_factory=list)
    updated: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    skipped_edited: list = field(default_factory=list)
    companies_created: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def summary(self) -> str:
        return (f"牌号新增 {len(self.created)} 个，更新 {len(self.updated)} 个，未变 {len(self.unchanged)} 个，"
                f"后台改过而跳过 {len(self.skipped_edited)} 个；新增公司 {len(self.companies_created)} 家；"
                f"提醒 {len(self.warnings)} 条")


class GradeImporter:
    def __init__(self, companies: list[dict], grades: list[dict]):
        self.companies = companies
        self.grades = grades
        self.report = GradeImportReport()
        self.grade_ct = ContentType.objects.get_for_model(m.Grade)
        self.company_ct = ContentType.objects.get_for_model(m.Company)
        self.entry_ct = ContentType.objects.get_for_model(m.Entry)

    # ---------- 工具 ----------
    def _add_aliases(self, ct, obj_id, aliases, default_kind):
        for alias in aliases or []:
            if isinstance(alias, dict):
                text, kind = str(alias.get("text", "")).strip(), alias.get("kind", default_kind)
            else:
                text, kind = str(alias).strip(), default_kind
            if kind not in m.Alias.Kind.values:
                kind = m.Alias.Kind.OTHER
            if m.normalize(text):
                m.Alias.objects.get_or_create(content_type=ct, object_id=obj_id, norm=m.normalize(text),
                                              defaults={"text": text, "kind": kind})

    def _company(self, name, where):
        comp = m.Company.objects.filter(name=str(name).strip()).first()
        if comp is None:
            ids = list(m.Alias.objects.filter(content_type=self.company_ct, norm=m.normalize(str(name)))
                       .values_list("object_id", flat=True).distinct()[:2])
            if len(ids) == 1:
                comp = m.Company.objects.get(pk=ids[0])
        if comp is None:
            comp = m.Company.objects.create(name=str(name).strip())
            self.report.companies_created.append(comp.name)
            self.report.warnings.append(f"{where}: 公司“{name}”没有在 companies.yaml 里登记，已按名字新建")
        return comp

    def _entry(self, ref):
        ref = str(ref).strip()
        qs = m.Entry.objects.filter(name_zh=ref, kind__in=[m.EntryKind.MATERIAL, m.EntryKind.ADDITIVE])
        if qs.count() == 1:
            return qs.first()
        ids = list(m.Alias.objects.filter(content_type=self.entry_ct, norm=m.normalize(ref))
                   .values_list("object_id", flat=True).distinct())
        found = list(m.Entry.objects.filter(pk__in=ids, kind__in=[m.EntryKind.MATERIAL, m.EntryKind.ADDITIVE])[:2])
        return found[0] if len(found) == 1 else None

    def _prop(self, ref):
        ref = str(ref).strip()
        return (m.PropertyDefinition.objects.filter(Q(name_zh=ref) | Q(abbr__iexact=ref)).first()
                if ref else None)

    # ---------- 主流程 ----------
    @transaction.atomic
    def run(self) -> GradeImportReport:
        self._import_companies()
        seen = set()
        for g in self.grades:
            self._import_grade(g, seen)
        return self.report

    def _import_companies(self):
        parents = []
        for c in self.companies:
            name = str(c.get("name", "")).strip()
            if not name:
                self.report.warnings.append(f"{c.get('_source')}: 有一家公司缺少 name，已跳过")
                continue
            comp = m.Company.objects.filter(name=name).first()
            values = {k: str(c.get(k) or "").strip() for k in ["name_zh", "name_en", "country", "city", "website", "intro"]}
            if comp is None:
                comp = m.Company.objects.create(name=name, **values)
                self.report.companies_created.append(name)
            else:
                changed = [k for k, v in values.items() if v and not getattr(comp, k)]
                for k in changed:
                    setattr(comp, k, values[k])
                if changed:
                    comp.save()
            for t in c.get("types") or []:
                ctype, _ = m.CompanyType.objects.get_or_create(name=str(t))
                comp.types.add(ctype)
            self._add_aliases(self.company_ct, comp.pk, c.get("aliases"), m.Alias.Kind.OTHER)
            if c.get("parent"):
                parents.append((comp, c["parent"], c.get("_source")))
        for comp, parent_name, where in parents:
            parent = m.Company.objects.filter(name=str(parent_name)).first()
            if parent is None:
                self.report.warnings.append(f"{where}: “{comp.name}”的所属集团“{parent_name}”没找到")
            elif comp.parent_id is None and parent.pk != comp.pk:
                comp.parent = parent
                comp.save(update_fields=["parent"])

    def _import_grade(self, g, seen):
        where = g.get("_source", "")
        code = str(g.get("code", "")).strip()
        producers = str(g.get("producers") or "").strip()
        if not code or not g.get("material") or not (g.get("manufacturer") or producers):
            self.report.warnings.append(
                f"{where}: 牌号缺少 code / material，或者 manufacturer 和 producers 都没写，已跳过：{g.get('code')!r}")
            return
        maker = self._company(g["manufacturer"], where) if g.get("manufacturer") else None
        label = f"{maker.name} {code}" if maker else f"{code}（多家生产）"

        entry = self._entry(g["material"])
        if entry is None:
            self.report.warnings.append(f"{where}: {label} 的材料“{g['material']}”没找到对应词条，已跳过")
            return
        # 有厂家：同一厂家下牌号唯一；多家生产的通用牌号：同一种材料下牌号唯一
        key = (maker.pk, m.normalize(code)) if maker else (None, m.normalize(code), entry.pk)
        if key in seen:
            self.report.warnings.append(f"{where}: {label} 重复出现，只导入第一次")
            return
        seen.add(key)

        brand = None
        if g.get("brand"):
            if maker is None:
                self.report.warnings.append(f"{where}: {label} 没有单一厂家，品牌“{g['brand']}”已忽略")
            else:
                brand, _ = m.Brand.objects.get_or_create(name=str(g["brand"]).strip(), owner=maker)

        product_type = g.get("product_type", m.Grade.ProductType.RESIN)
        if product_type not in m.Grade.ProductType.values:
            self.report.warnings.append(f"{where}: {label} 的 product_type“{product_type}”无效，按“基础树脂”处理")
            product_type = m.Grade.ProductType.RESIN
        lifecycle = g.get("lifecycle", m.Grade.Lifecycle.UNKNOWN)
        if lifecycle not in m.Grade.Lifecycle.values:
            lifecycle = m.Grade.Lifecycle.UNKNOWN
        verify = g.get("verify", m.VerifyStatus.UNVERIFIED)
        if verify not in m.VerifyStatus.values:
            verify = m.VerifyStatus.UNVERIFIED

        fields = {
            "full_name": str(g.get("full_name") or "").strip(),
            "product_type": product_type,
            "grade_class": str(g.get("grade_class") or "").strip(),
            "summary": str(g.get("summary") or "").strip(),
            "description": str(g.get("description") or "").strip(),
            "producers_note": "" if maker else producers,
            "base_entry_id": entry.pk,
            "brand_id": brand.pk if brand else None,
            "lifecycle": lifecycle,
            "verify_status": verify,
        }

        # 来源
        sources = {}
        for s in g.get("sources") or []:
            sid = str(s.get("id", "")).strip()
            title = str(s.get("title", "")).strip()
            if not sid or not title:
                self.report.warnings.append(f"{where}: {label} 有来源缺少 id 或 title")
                continue
            kind = s.get("kind", m.Source.Kind.OTHER)
            if kind not in m.Source.Kind.values:
                kind = m.Source.Kind.OTHER
            accessed = s.get("accessed")
            if isinstance(accessed, str):
                try:
                    accessed = datetime.date.fromisoformat(accessed)
                except ValueError:
                    accessed = None
            src, _ = m.Source.objects.get_or_create(
                kind=kind, title=title, url=str(s.get("url") or ""),
                defaults={"publisher": str(s.get("publisher") or ""), "accessed_on": accessed},
            )
            sources[sid] = src

        # 性能数据
        new_pvs = []
        for p in g.get("properties") or []:
            prop = self._prop(p.get("prop"))
            if prop is None:
                self.report.warnings.append(f"{where}: {label} 的性能指标“{p.get('prop')}”没有定义，已跳过")
                continue
            src = sources.get(str(p.get("source", "")))
            if src is None:
                self.report.warnings.append(f"{where}: {label} 的“{prop.name_zh}”没有有效来源，已跳过（不收没有出处的数字）")
                continue
            raw = str(p.get("value", "")).strip()
            num, vmin, vmax = _parse_value(raw)
            value_type = p.get("type", m.PropertyValue.ValueType.TYPICAL)
            if value_type not in m.PropertyValue.ValueType.values:
                value_type = m.PropertyValue.ValueType.TYPICAL
            pv_verify = p.get("verify", verify)
            if pv_verify not in m.VerifyStatus.values:
                pv_verify = verify
            thickness = p.get("thickness_mm")
            conditioning = _CONDITIONING.get(str(p.get("state") or "").strip().lower(), "")
            if p.get("state") and not conditioning:
                self.report.warnings.append(f"{where}: {label} 的“{prop.name_zh}”state 写法不认识：{p.get('state')!r}")
            direction = _DIRECTION.get(str(p.get("direction") or "").strip().lower(), "")
            new_pvs.append({
                "prop": prop, "value_text": raw, "value_num": num, "value_min": vmin, "value_max": vmax,
                "unit": str(p.get("unit") or "").strip(), "conditions": str(p.get("conditions") or "").strip(),
                "standard_text": str(p.get("standard") or "").strip(), "value_type": value_type,
                "thickness_mm": float(thickness) if thickness not in (None, "") else None,
                "conditioning": conditioning, "direction": direction,
                "source": src, "verify_status": pv_verify, "note": str(p.get("note") or "").strip(),
            })
        new_tuples = [(v["prop"].pk, v["value_text"], v["value_num"], v["value_min"], v["value_max"], v["unit"],
                       v["conditions"], v["standard_text"], v["value_type"], v["thickness_mm"], v["conditioning"],
                       v["direction"], v["source"].pk, v["verify_status"], v["note"]) for v in new_pvs]
        new_fp = _fp(fields, new_tuples)

        if maker:
            grade = m.Grade.objects.filter(manufacturer=maker, code_norm=m.normalize(code)).first()
        else:
            grade = m.Grade.objects.filter(manufacturer__isnull=True, code_norm=m.normalize(code),
                                           base_entry=entry).first()
        if grade is None:
            grade = m.Grade(code=code, manufacturer=maker, imported_hash=new_fp, **fields)
            grade.save()
            self._write_pvs(grade, new_pvs)
            self.report.created.append(label)
        else:
            db_tuples = [_pv_tuple(pv) for pv in grade.property_values.filter(from_content=True)]
            db_fp = _fp({k: getattr(grade, k) for k in GRADE_FIELDS}, db_tuples)
            if grade.imported_hash and db_fp != grade.imported_hash:
                self.report.skipped_edited.append(label)
            elif grade.imported_hash == new_fp:
                self.report.unchanged.append(label)
            else:
                for k, v in fields.items():
                    setattr(grade, k, v)
                grade.imported_hash = new_fp
                grade.save()
                grade.property_values.filter(from_content=True).delete()
                self._write_pvs(grade, new_pvs)
                self.report.updated.append(label)

        grade.sources.add(*sources.values())
        self._add_aliases(self.grade_ct, grade.pk, g.get("aliases"), m.Alias.Kind.TRADE)

    def _write_pvs(self, grade, pvs):
        for v in pvs:
            pv = m.PropertyValue(grade=grade, from_content=True, **v)
            pv.save()
