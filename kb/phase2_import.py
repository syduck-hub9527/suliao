"""
第二阶段补充实体导入：品牌、生产工厂、技术文件，以及牌号与工厂的可追溯关系。

数据仍然保存在 content/grades/*.yaml；重复导入安全，不覆盖后台已经填写的非空字段。
"""
import datetime
from dataclasses import dataclass, field

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from . import models as m


def _as_date(value):
    if not value:
        return None
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


@dataclass
class Phase2ImportReport:
    brands_created: list = field(default_factory=list)
    plants_created: list = field(default_factory=list)
    documents_created: list = field(default_factory=list)
    grade_plants_created: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def summary(self):
        return (
            f"品牌新增 {len(self.brands_created)} 个，工厂新增 {len(self.plants_created)} 个，"
            f"技术文件新增 {len(self.documents_created)} 份，牌号-工厂关系新增 "
            f"{len(self.grade_plants_created)} 条，提醒 {len(self.warnings)} 条"
        )


class Phase2Importer:
    def __init__(self, companies, grades):
        self.companies = companies
        self.grades = grades
        self.report = Phase2ImportReport()
        self.company_ct = ContentType.objects.get_for_model(m.Company)
        self.brand_ct = ContentType.objects.get_for_model(m.Brand)

    def _source(self, data, where):
        title = str(data.get("title") or "").strip()
        if not title:
            self.report.warnings.append(f"{where}: 来源缺少 title，已跳过")
            return None
        kind = data.get("kind", m.Source.Kind.OTHER)
        if kind not in m.Source.Kind.values:
            kind = m.Source.Kind.OTHER
        url = str(data.get("url") or "").strip()
        source = m.Source.objects.filter(kind=kind, title=title, url=url).first()
        values = {
            "publisher": str(data.get("publisher") or "").strip(),
            "accessed_on": _as_date(data.get("accessed")),
            "published_on": _as_date(data.get("published")),
            "note": str(data.get("note") or "").strip(),
        }
        if source is None:
            source = m.Source.objects.create(kind=kind, title=title, url=url, **values)
        else:
            changed = []
            for field, value in values.items():
                if value and not getattr(source, field):
                    setattr(source, field, value)
                    changed.append(field)
            if changed:
                source.save(update_fields=changed + ["updated_at"])
        return source

    def _company(self, name):
        name = str(name or "").strip()
        if not name:
            return None
        company = m.Company.objects.filter(name=name).first()
        if company:
            return company
        ids = list(
            m.Alias.objects.filter(content_type=self.company_ct, norm=m.normalize(name))
            .values_list("object_id", flat=True).distinct()[:2]
        )
        return m.Company.objects.get(pk=ids[0]) if len(ids) == 1 else None

    def _add_aliases(self, content_type, object_id, aliases):
        for item in aliases or []:
            if isinstance(item, dict):
                text = str(item.get("text") or "").strip()
                kind = item.get("kind", m.Alias.Kind.OTHER)
            else:
                text, kind = str(item).strip(), m.Alias.Kind.OTHER
            if kind not in m.Alias.Kind.values:
                kind = m.Alias.Kind.OTHER
            norm = m.normalize(text)
            if norm:
                m.Alias.objects.get_or_create(
                    content_type=content_type, object_id=object_id, norm=norm,
                    defaults={"text": text, "kind": kind},
                )

    def _import_company_entities(self):
        for item in self.companies:
            company = self._company(item.get("name"))
            if company is None:
                continue
            sources = {}
            for raw in item.get("sources") or []:
                sid = str(raw.get("id") or "").strip()
                source = self._source(raw, f"公司 {company.name}")
                if sid and source:
                    sources[sid] = source
                    company.sources.add(source)

            verify = item.get("verify", m.VerifyStatus.UNVERIFIED)
            if verify not in m.VerifyStatus.values:
                verify = m.VerifyStatus.UNVERIFIED
            changed = []
            if company.verify_status == m.VerifyStatus.UNVERIFIED and verify != m.VerifyStatus.UNVERIFIED:
                company.verify_status = verify
                changed.append("verify_status")
            checked = _as_date(item.get("last_checked"))
            if checked and not company.last_checked_on:
                company.last_checked_on = checked
                changed.append("last_checked_on")
            if changed:
                company.save(update_fields=changed + ["updated_at"])

            for brand_data in item.get("brands") or []:
                if isinstance(brand_data, str):
                    brand_data = {"name": brand_data}
                name = str(brand_data.get("name") or "").strip()
                if not name:
                    self.report.warnings.append(f"公司 {company.name}: 品牌缺少 name，已跳过")
                    continue
                brand = m.Brand.objects.filter(owner=company, name=name).first()
                if brand is None:
                    brand = m.Brand.objects.create(owner=company, name=name)
                    self.report.brands_created.append(f"{company.name} · {name}")
                brand_changed = []
                for field in ("intro", "history"):
                    value = str(brand_data.get(field) or "").strip()
                    if value and not getattr(brand, field):
                        setattr(brand, field, value)
                        brand_changed.append(field)
                if brand_changed:
                    brand.save(update_fields=brand_changed + ["updated_at"])
                self._add_aliases(self.brand_ct, brand.pk, brand_data.get("aliases"))
                for sid in brand_data.get("sources") or []:
                    if str(sid) in sources:
                        brand.sources.add(sources[str(sid)])
                    else:
                        self.report.warnings.append(
                            f"品牌 {company.name} · {name}: 找不到来源 ID {sid!r}"
                        )

            for plant_data in item.get("plants") or []:
                name = str(plant_data.get("name") or "").strip()
                if not name:
                    self.report.warnings.append(f"公司 {company.name}: 工厂缺少 name，已跳过")
                    continue
                city = str(plant_data.get("city") or "").strip()
                plant = m.Plant.objects.filter(company=company, name=name, city=city).first()
                status = plant_data.get("status", m.Plant.Status.UNKNOWN)
                if status not in m.Plant.Status.values:
                    status = m.Plant.Status.UNKNOWN
                verify = plant_data.get("verify", m.VerifyStatus.UNVERIFIED)
                if verify not in m.VerifyStatus.values:
                    verify = m.VerifyStatus.UNVERIFIED
                fields = {
                    "country": str(plant_data.get("country") or "").strip(),
                    "city": city,
                    "address": str(plant_data.get("address") or "").strip(),
                    "products_note": str(plant_data.get("products_note") or "").strip(),
                    "capacity_note": str(plant_data.get("capacity_note") or "").strip(),
                    "status": status,
                    "status_on": _as_date(plant_data.get("status_on")),
                    "verify_status": verify,
                    "note": str(plant_data.get("note") or "").strip(),
                }
                if plant is None:
                    plant = m.Plant.objects.create(company=company, name=name, **fields)
                    self.report.plants_created.append(f"{company.name} · {name}")
                else:
                    plant_changed = []
                    for field, value in fields.items():
                        current = getattr(plant, field)
                        if value and (not current or (field == "status" and current == m.Plant.Status.UNKNOWN)
                                      or (field == "verify_status" and current == m.VerifyStatus.UNVERIFIED)):
                            setattr(plant, field, value)
                            plant_changed.append(field)
                    if plant_changed:
                        plant.save(update_fields=plant_changed + ["updated_at"])
                for sid in plant_data.get("sources") or []:
                    if str(sid) in sources:
                        plant.sources.add(sources[str(sid)])
                    else:
                        self.report.warnings.append(
                            f"工厂 {company.name} · {name}: 找不到来源 ID {sid!r}"
                        )

    def _import_grade_documents_and_plants(self):
        for item in self.grades:
            company = self._company(item.get("manufacturer"))
            code = str(item.get("code") or "").strip()
            if not code or company is None:
                continue
            grade = m.Grade.objects.filter(
                manufacturer=company, code_norm=m.normalize(code)
            ).first()
            if grade is None:
                continue

            sources = {}
            for raw in item.get("sources") or []:
                sid = str(raw.get("id") or "").strip()
                source = self._source(raw, f"牌号 {company.name} {code}")
                if not source:
                    continue
                if sid:
                    sources[sid] = source
                grade.sources.add(source)

                document_data = raw.get("document")
                if not document_data:
                    continue
                title = str(document_data.get("title") or raw.get("title") or "").strip()
                url = str(document_data.get("url") or raw.get("url") or "").strip()
                if not title:
                    self.report.warnings.append(f"牌号 {company.name} {code}: 技术文件缺少标题")
                    continue
                kind = document_data.get("kind", "tds" if raw.get("kind") == m.Source.Kind.MAKER_DOC else "other")
                if kind not in m.Document.Kind.values:
                    kind = m.Document.Kind.OTHER
                document = m.Document.objects.filter(title=title, url=url).first()
                document_fields = {
                    "language": str(document_data.get("language") or "").strip(),
                    "version": str(document_data.get("version") or "").strip(),
                    "published_on": _as_date(document_data.get("published_on")),
                    "retrieved_on": _as_date(raw.get("accessed")),
                    "note": str(document_data.get("note") or "").strip(),
                }
                if document is None:
                    document = m.Document.objects.create(
                        kind=kind, title=title, url=url, company=company, **document_fields
                    )
                    self.report.documents_created.append(title)
                else:
                    changed = []
                    if not document.company_id:
                        document.company = company
                        changed.append("company")
                    for field, value in document_fields.items():
                        if value and not getattr(document, field):
                            setattr(document, field, value)
                            changed.append(field)
                    if changed:
                        document.save(update_fields=changed + ["updated_at"])
                document.grades.add(grade)
                if source.document_id != document.pk:
                    source.document = document
                    source.save(update_fields=["document", "updated_at"])

            for plant_data in item.get("plants") or []:
                if isinstance(plant_data, str):
                    plant_data = {"name": plant_data}
                plant_name = str(plant_data.get("name") or "").strip()
                plant = m.Plant.objects.filter(company=company, name=plant_name).first()
                source = sources.get(str(plant_data.get("source") or ""))
                if plant is None:
                    self.report.warnings.append(
                        f"牌号 {company.name} {code}: 工厂 {plant_name!r} 未在公司工厂档案中登记"
                    )
                    continue
                if source is None:
                    self.report.warnings.append(
                        f"牌号 {company.name} {code}: 工厂关系 {plant_name!r} 缺少有效来源，未建立关联"
                    )
                    continue
                verify = plant_data.get("verify", m.VerifyStatus.UNVERIFIED)
                if verify not in m.VerifyStatus.values:
                    verify = m.VerifyStatus.UNVERIFIED
                relation = m.GradePlant.objects.filter(grade=grade, plant=plant).first()
                if relation is None:
                    relation = m.GradePlant.objects.create(
                        grade=grade, plant=plant, source=source, verify_status=verify,
                        note=str(plant_data.get("note") or "").strip(),
                    )
                    self.report.grade_plants_created.append(f"{grade.code} · {plant.name}")
                else:
                    changed = []
                    if not relation.source_id:
                        relation.source = source
                        changed.append("source")
                    if relation.verify_status == m.VerifyStatus.UNVERIFIED and verify != m.VerifyStatus.UNVERIFIED:
                        relation.verify_status = verify
                        changed.append("verify_status")
                    if plant_data.get("note") and not relation.note:
                        relation.note = str(plant_data["note"])
                        changed.append("note")
                    if changed:
                        relation.save(update_fields=changed)

    @transaction.atomic
    def run(self):
        self._import_company_entities()
        self._import_grade_documents_and_plants()
        return self.report
