from django.test import TestCase

from . import models as m
from .grades_import import GradeImporter
from .phase2_import import Phase2Importer


class Phase2ImporterTests(TestCase):
    def setUp(self):
        self.additive = m.Entry.objects.create(
            kind=m.EntryKind.ADDITIVE, name_zh="抗氧剂", abbr="AO"
        )
        self.companies = [{
            "name": "示例助剂公司",
            "country": "日本",
            "sources": [{
                "id": "company-source", "title": "公司官方资料",
                "url": "https://example.com/company", "publisher": "示例助剂公司",
                "kind": "maker_web", "accessed": "2026-11-10",
            }],
            "brands": [{
                "name": "ExampleStab", "intro": "示例稳定剂品牌",
                "aliases": ["Example Stabilizer"], "sources": ["company-source"],
            }],
            "plants": [{
                "name": "示例工厂", "country": "日本", "city": "大阪",
                "products_note": "示例助剂产品", "status": "running",
                "status_on": "2026-11-10", "verify": "verified",
                "sources": ["company-source"],
            }],
        }]
        self.grades = [{
            "code": "AO-100", "full_name": "ExampleStab AO-100",
            "manufacturer": "示例助剂公司", "brand": "ExampleStab",
            "material": "抗氧剂", "product_type": "additive",
            "verify": "verified", "summary": "示例抗氧剂牌号",
            "sources": [{
                "id": "tds", "title": "AO-100 Technical Data Sheet",
                "url": "https://example.com/ao-100.pdf", "publisher": "示例助剂公司",
                "kind": "maker_doc", "accessed": "2026-11-10",
                "document": {"kind": "tds", "language": "en", "version": "1.0"},
            }],
            "plants": [{
                "name": "示例工厂", "source": "tds", "verify": "verified",
                "note": "仅在该厂家公开资料明确对应此牌号时建立此关系",
            }],
        }]

    def _run(self):
        GradeImporter(self.companies, self.grades).run()
        return Phase2Importer(self.companies, self.grades).run()

    def test_imports_brand_plant_document_and_grade_plant_link(self):
        report = self._run()
        company = m.Company.objects.get(name="示例助剂公司")
        grade = m.Grade.objects.get(code="AO-100")
        brand = m.Brand.objects.get(name="ExampleStab", owner=company)
        plant = m.Plant.objects.get(name="示例工厂", company=company)
        document = m.Document.objects.get(title="AO-100 Technical Data Sheet")

        self.assertEqual(report.warnings, [])
        self.assertTrue(company.sources.exists())
        self.assertTrue(brand.sources.exists())
        self.assertTrue(plant.sources.exists())
        self.assertEqual(grade.brand, brand)
        self.assertEqual(grade.documents.get(), document)
        self.assertEqual(grade.plants.get(), plant)
        self.assertEqual(m.GradePlant.objects.get(grade=grade, plant=plant).source.title,
                         "AO-100 Technical Data Sheet")

    def test_reimport_is_idempotent(self):
        self._run()
        self._run()
        self.assertEqual(m.Company.objects.filter(name="示例助剂公司").count(), 1)
        self.assertEqual(m.Brand.objects.filter(name="ExampleStab").count(), 1)
        self.assertEqual(m.Plant.objects.filter(name="示例工厂").count(), 1)
        self.assertEqual(m.Document.objects.filter(title="AO-100 Technical Data Sheet").count(), 1)
        self.assertEqual(m.GradePlant.objects.count(), 1)
