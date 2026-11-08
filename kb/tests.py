"""
数据库规则自测。运行：python manage.py test kb
（测试里的公司、牌号、数值都是虚构的，只用来检查规则。）
"""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from . import models as m
from .search import search


class HelperTests(TestCase):
    def test_normalize(self):
        self.assertEqual(m.normalize("pa 66"), "PA66")
        self.assertEqual(m.normalize("ＰＡ６６"), "PA66")
        self.assertEqual(m.normalize("PC/ABS"), "PCABS")
        self.assertEqual(m.normalize("聚丙烯"), "聚丙烯")

    def test_cas(self):
        self.assertTrue(m.is_valid_cas("9003-07-0"))
        self.assertTrue(m.is_valid_cas("7732-18-5"))
        self.assertFalse(m.is_valid_cas("9003-07-1"))
        self.assertFalse(m.is_valid_cas("abc"))


class DataRuleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.src = m.Source.objects.create(kind=m.Source.Kind.MAKER_DOC, title="示例 TDS")
        cls.pp = m.Entry.objects.create(kind=m.EntryKind.MATERIAL, name_zh="聚丙烯", name_en="Polypropylene", abbr="PP")
        cls.pom = m.Entry.objects.create(kind=m.EntryKind.MATERIAL, name_zh="聚甲醛", abbr="POM")
        m.Alias.objects.create(target=cls.pom, text="赛钢", kind=m.Alias.Kind.NICKNAME)
        # 同一个缩写对应两个东西
        cls.pir1 = m.Entry.objects.create(kind=m.EntryKind.TERM, name_zh="工业后回收料", abbr="PIR")
        cls.pir2 = m.Entry.objects.create(kind=m.EntryKind.MATERIAL, name_zh="聚异氰脲酸酯", abbr="PIR")
        cls.maker = m.Company.objects.create(name="示例化工")
        cls.grade = m.Grade.objects.create(
            code="ab-100", full_name="EXAMPLE AB-100", product_type=m.Grade.ProductType.RESIN,
            base_entry=cls.pp, manufacturer=cls.maker,
        )
        cls.tensile, _ = m.PropertyDefinition.objects.get_or_create(
            name_zh="拉伸强度", defaults={"group": m.PropertyDefinition.Group.MECHANICAL, "si_unit": "MPa"},
        )

    # —— 别名与搜索 ——
    def test_names_become_aliases(self):
        texts = set(self.pp.aliases.values_list("norm", flat=True))
        self.assertEqual(texts, {"PP", "聚丙烯", "POLYPROPYLENE"})

    def test_search_by_abbr_any_case(self):
        hits = search("pp")
        self.assertEqual(hits[0][0], self.pp)
        self.assertTrue(hits[0][2])

    def test_search_by_nickname(self):
        self.assertIn(self.pom, [h[0] for h in search("赛钢")])

    def test_search_ambiguous_lists_all(self):
        found = [h[0] for h in search("PIR") if h[2]]
        self.assertIn(self.pir1, found)
        self.assertIn(self.pir2, found)

    def test_search_grade_code_normalized(self):
        hits = search("AB100")
        self.assertEqual(hits[0][0], self.grade)
        self.assertEqual(hits[0][1], "牌号精确匹配")
        self.assertIn(self.grade, [h[0] for h in search("example ab-100")])

    def test_fuzzy_marked_not_exact(self):
        hits = search("丙烯")
        self.assertTrue(hits)
        self.assertFalse(hits[0][2])

    def test_bad_cas_rejected(self):
        a = m.Alias(target=self.pp, text="9003-07-1", kind=m.Alias.Kind.CAS)
        with self.assertRaises(ValidationError):
            a.full_clean()

    # —— 性能值 ——
    def test_property_value_si_copied(self):
        pv = m.PropertyValue.objects.create(
            grade=self.grade, prop=self.tensile, value_text="60", value_num=60, unit="MPa", source=self.src,
        )
        self.assertEqual(pv.value_si, 60)

    def test_property_value_other_unit_not_guessed(self):
        pv = m.PropertyValue.objects.create(
            grade=self.grade, prop=self.tensile, value_text="8700", value_num=8700, unit="psi", source=self.src,
        )
        self.assertIsNone(pv.value_si)

    def test_property_value_needs_exactly_one_owner(self):
        for kwargs in ({"grade": self.grade, "entry": self.pp}, {}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                m.PropertyValue.objects.create(prop=self.tensile, value_text="1", source=self.src, **kwargs)

    def test_property_value_min_le_max(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            m.PropertyValue.objects.create(
                grade=self.grade, prop=self.tensile, value_text="70–60",
                value_min=70, value_max=60, source=self.src,
            )

    # —— 其他约束 ——
    def test_grade_unique_per_maker(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            m.Grade.objects.create(code="AB 100", product_type="resin", base_entry=self.pp, manufacturer=self.maker)

    def test_relation_not_self(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            m.EntryRelation.objects.create(from_entry=self.pp, to_entry=self.pp, kind="related")

    def test_price_series_needs_target(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            m.PriceSeries.objects.create(name="空序列", price_type="spot", source=self.src)

    def test_price_point_one_per_day(self):
        s = m.PriceSeries.objects.create(name="示例 PP 现货", entry=self.pp, price_type="spot", source=self.src)
        m.PricePoint.objects.create(series=s, date="2026-11-02", price=7000)
        with self.assertRaises(IntegrityError), transaction.atomic():
            m.PricePoint.objects.create(series=s, date="2026-11-02", price=7100)

    def test_category_same_tree(self):
        root = m.Category.objects.create(kind=m.EntryKind.ADDITIVE, name="抗氧剂")
        c = m.Category(kind=m.EntryKind.MATERIAL, name="聚烯烃", parent=root)
        with self.assertRaises(ValidationError):
            c.full_clean()


NO_MANIFEST = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

SAMPLE_CONTENT = """---
kind: material
name_zh: 聚丙烯
name_en: Polypropylene
abbr: PP
aliases: [百折胶, {text: 9003-07-0, kind: cas}, {text: 9003-07-1, kind: cas}]
category: [通用塑料, 聚烯烃]
difficulty: 1
one_liner: 最常用的塑料之一
related: [{to: PE, kind: confusable}, 不存在的词]
path: {stage: "第 2 阶段：认识常见塑料", order: 20, goal: 说出 PP 的三种类型}
---
## 小白解释
PP 和 PE 都属于聚烯烃。百折胶说的就是它。

## 专业内容
| 类型 | 特点 |
|---|---|
| 均聚 | 刚性好 |

## 常见误区
- 不要和 PE 搞混

---
kind: material
name_zh: 聚乙烯
abbr: PE
category: [通用塑料, 聚烯烃]
one_liner: 产量最大的塑料
path: {stage: "第 2 阶段：认识常见塑料", order: 10}
---
## 小白解释
PE 和 PP 是一对“兄弟”。

## 某个自定义标题
补充内容
"""


@override_settings(STORAGES=NO_MANIFEST)
class SeedAndPageTests(TestCase):
    def test_seed_data_present(self):
        self.assertTrue(m.CompanyType.objects.filter(name="生产商").exists())
        hdt = m.PropertyDefinition.objects.get(abbr="HDT")
        self.assertEqual(hdt.si_unit, "°C")

    def test_no_login_needed(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_admin_pages_load(self):
        for url in ["/admin/", "/admin/kb/entry/add/", "/admin/kb/grade/add/", "/admin/kb/priceseries/add/",
                    "/admin/kb/entry/", "/admin/kb/propertydefinition/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)


@override_settings(STORAGES=NO_MANIFEST)
class ContentImportTests(TestCase):
    def setUp(self):
        from .content import Importer, parse_text
        self.parse_text, self.Importer = parse_text, Importer

    def run_import(self, text=SAMPLE_CONTENT):
        return self.Importer(self.parse_text(text, "test.md")).run()

    def test_import_creates_everything(self):
        report = self.run_import()
        self.assertEqual(sorted(report.created), ["聚丙烯", "聚乙烯"])
        pp = m.Entry.objects.get(name_zh="聚丙烯")
        self.assertEqual(pp.origin, m.ContentOrigin.AI_DRAFT)
        self.assertEqual(str(pp.category), "通用塑料 > 聚烯烃")
        self.assertIn("|---|", pp.pro_text)
        self.assertIn("不要和 PE 搞混", pp.pitfalls)
        self.assertTrue(pp.aliases.filter(text="百折胶", kind="nickname").exists())
        self.assertTrue(pp.aliases.filter(kind="cas", text="9003-07-0").exists())
        self.assertFalse(pp.aliases.filter(text="9003-07-1").exists())     # 校验不过的 CAS 不导入
        self.assertTrue(m.EntryRelation.objects.filter(kind="confusable").exists())
        self.assertTrue(any("不存在的词" in w for w in report.warnings))
        pe = m.Entry.objects.get(name_zh="聚乙烯")
        self.assertIn("### 某个自定义标题", pe.pro_text)
        items = list(m.PathItem.objects.order_by("order").values_list("entry__name_zh", flat=True))
        self.assertEqual(items, ["聚乙烯", "聚丙烯"])

    def test_reimport_is_idempotent(self):
        self.run_import()
        report = self.run_import()
        self.assertEqual(len(report.unchanged), 2)
        self.assertEqual(m.EntryRelation.objects.count(), 1)
        self.assertEqual(m.PathItem.objects.count(), 2)

    def test_content_update_applies(self):
        self.run_import()
        report = self.run_import(SAMPLE_CONTENT.replace("最常用的塑料之一", "最常用的塑料之一（新版）"))
        self.assertEqual(report.updated, ["聚丙烯"])
        self.assertEqual(m.Entry.objects.get(name_zh="聚丙烯").one_liner, "最常用的塑料之一（新版）")

    def test_admin_edit_is_not_overwritten(self):
        self.run_import()
        pp = m.Entry.objects.get(name_zh="聚丙烯")
        pp.one_liner = "我自己改过的"
        pp.save()
        report = self.run_import(SAMPLE_CONTENT.replace("最常用的塑料之一", "新版"))
        self.assertEqual(report.skipped_edited, ["聚丙烯"])
        self.assertEqual(m.Entry.objects.get(name_zh="聚丙烯").one_liner, "我自己改过的")

    def test_bad_yaml_raises(self):
        from .content import ContentError
        with self.assertRaises(ContentError):
            self.parse_text("---\nkind: [oops\n---\n正文\n", "bad.md")

    def test_entry_page_and_auto_links(self):
        self.run_import()
        pp = m.Entry.objects.get(name_zh="聚丙烯")
        pe = m.Entry.objects.get(name_zh="聚乙烯")
        resp = self.client.get(f"/e/{pp.pk}/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn(f'href="/e/{pe.pk}/"', html)          # 正文里的 PE 自动变成链接
        self.assertIn("AI 整理 · 待核对", html)
        self.assertIn("百折胶", html)                        # 其他叫法
        self.assertIn("<table>", html)
        self.assertEqual(m.EntryProgress.objects.get(entry=pp).view_count, 1)

    def test_progress_and_learn_pages(self):
        self.run_import()
        pp = m.Entry.objects.get(name_zh="聚丙烯")
        resp = self.client.post(f"/e/{pp.pk}/progress/", {"status": "confused"})
        self.assertEqual(resp.status_code, 302)
        self.client.post(f"/e/{pp.pk}/progress/", {"star": "1"})
        prog = m.EntryProgress.objects.get(entry=pp)
        self.assertEqual(prog.status, "confused")
        self.assertTrue(prog.starred)
        html = self.client.get("/learn/").content.decode()
        self.assertIn("第 2 阶段：认识常见塑料", html)
        self.assertIn("还不懂", html)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_search_and_browse_pages(self):
        self.run_import()
        html = self.client.get("/search/", {"q": "百折胶"}).content.decode()
        self.assertIn("PP 聚丙烯", html)
        self.assertIn("/e/", html)
        html = self.client.get("/search/", {"q": "兄弟"}).content.decode()   # 正文搜索
        self.assertIn("正文里提到", html)
        html = self.client.get("/browse/material/").content.decode()
        self.assertIn("聚烯烃", html)
        self.assertEqual(self.client.get("/browse/").status_code, 200)


class TermLinkerTests(TestCase):
    def test_ascii_boundaries_and_longest_first(self):
        from .render import TermLinker
        pp = m.Entry.objects.create(kind="material", name_zh="聚丙烯", abbr="PP")
        m.Entry.objects.create(kind="material", name_zh="聚苯硫醚", abbr="PPS")
        hi = m.Entry.objects.create(kind="material", name_zh="抗冲共聚聚丙烯")
        html = TermLinker().link("<p>PPS 不是 PP，抗冲共聚聚丙烯也是聚丙烯</p>")
        self.assertIn(f'href="/e/{hi.pk}/"', html)
        self.assertEqual(html.count(f'href="/e/{pp.pk}/"'), 1)   # 同一词条只链一次
        self.assertNotIn("<a class=\"term\" href=\"/e/%d/\" title=\"点击查看解释\">PP</a>S" % pp.pk, html)

    def test_no_links_inside_headings_or_links(self):
        from .render import TermLinker
        pp = m.Entry.objects.create(kind="material", name_zh="聚丙烯", abbr="PP")
        html = TermLinker().link('<h3>PP</h3><a href="#">PP</a><p>PP</p>')
        self.assertEqual(html.count(f'/e/{pp.pk}/'), 1)
        self.assertTrue(html.startswith("<h3>PP</h3>"))


class RepoContentTests(TestCase):
    """仓库 content/ 目录里的知识文件必须能无警告地导入。"""

    def test_repo_content_imports_cleanly(self):
        from django.conf import settings
        from .content import Importer, read_content_dir
        items = read_content_dir(settings.CONTENT_DIR)
        self.assertGreater(len(items), 30)
        report = Importer(items).run()
        self.assertEqual(report.warnings, [])
        self.assertEqual(len(report.created), len(items))
        # 每个词条都有一句话解释、小白解释、常见误区，并且在学习路线里
        for e in m.Entry.objects.all():
            self.assertTrue(e.one_liner and e.easy_text and e.pitfalls, e.name_zh)
            self.assertTrue(e.path_items.exists(), e.name_zh)

    def test_list_after_paragraph_renders_as_list(self):
        from .render import md_to_html
        html = md_to_html("它的特点：\n- 轻\n- 耐热")
        self.assertIn("<ul>", html)
        self.assertIn("<li>轻</li>", html)


# ============================================================
# 牌号库导入
# ============================================================

def _material(name, abbr):
    return m.Entry.objects.create(kind=m.EntryKind.MATERIAL, name_zh=name, abbr=abbr)


def _grade_item(**over):
    item = {
        "code": "2805", "manufacturer": "科思创", "material": "PC", "full_name": "Makrolon 2805",
        "verify": "verified", "_source": "test.yaml",
        "sources": [{"id": "s1", "title": "TDS", "url": "https://example.com/tds", "kind": "maker_doc"}],
        "properties": [
            {"prop": "MVR", "value": "9", "unit": "cm³/10min", "conditions": "300°C/1.2kg", "source": "s1"},
        ],
    }
    item.update(over)
    return item


@override_settings(STORAGES=NO_MANIFEST)
class GradeImportTests(TestCase):
    def setUp(self):
        self.pc = _material("聚碳酸酯", "PC")
        self.pp = _material("均聚聚丙烯", "PP-H")

    def run_import(self, grades, companies=None):
        from .grades_import import GradeImporter
        return GradeImporter(companies or [{"name": "科思创", "aliases": ["Covestro"]}], grades).run()

    def test_parse_value(self):
        from .grades_import import _parse_value
        self.assertEqual(_parse_value("62"), (62.0, None, None))
        self.assertEqual(_parse_value("60～65"), (None, 60.0, 65.0))
        self.assertEqual(_parse_value("3.0±0.5"), (None, 2.5, 3.5))
        self.assertEqual(_parse_value("≥30.0"), (None, 30.0, None))
        self.assertEqual(_parse_value("≤0.030"), (None, None, 0.03))
        self.assertEqual(_parse_value(">1,000"), (None, 1000.0, None))
        self.assertEqual(_parse_value("12,000"), (12000.0, None, None))
        self.assertEqual(_parse_value("HB"), (None, None, None))
        self.assertEqual(_parse_value("R-110"), (None, None, None))

    def test_creates_grade_with_sourced_values(self):
        report = self.run_import([_grade_item()])
        self.assertEqual(report.warnings, [])
        g = m.Grade.objects.get(code="2805")
        self.assertEqual(g.manufacturer.name, "科思创")
        self.assertEqual(g.base_entry, self.pc)
        pv = g.property_values.get()
        self.assertEqual((pv.value_num, pv.value_si, pv.conditions), (9.0, 9.0, "300°C/1.2kg"))
        self.assertTrue(pv.from_content)
        self.assertEqual(pv.source.url, "https://example.com/tds")

    def test_value_without_source_is_dropped(self):
        item = _grade_item(properties=[{"prop": "MVR", "value": "9", "unit": "cm³/10min"}])
        report = self.run_import([item])
        self.assertFalse(m.PropertyValue.objects.exists())
        self.assertTrue(any("没有有效来源" in w for w in report.warnings))

    def test_reimport_is_idempotent_and_updates(self):
        self.run_import([_grade_item()])
        report = self.run_import([_grade_item()])
        self.assertEqual(len(report.unchanged), 1)
        changed = _grade_item(summary="新的一句话")
        report = self.run_import([changed])
        self.assertEqual(len(report.updated), 1)
        self.assertEqual(m.Grade.objects.get().summary, "新的一句话")
        self.assertEqual(m.PropertyValue.objects.count(), 1)

    def test_admin_edits_are_not_overwritten(self):
        self.run_import([_grade_item()])
        pv = m.PropertyValue.objects.get()
        pv.value_text = "9.5"
        pv.save()
        report = self.run_import([_grade_item(summary="内容文件改了")])
        self.assertEqual(len(report.skipped_edited), 1)
        self.assertEqual(m.PropertyValue.objects.get().value_text, "9.5")
        self.assertEqual(m.Grade.objects.get().summary, "")

    def test_multi_producer_grade_without_manufacturer(self):
        item = _grade_item(code="T30S", manufacturer=None, material="PP-H", producers="中国石化多家企业",
                           properties=[{"prop": "MFR", "value": "3.0±0.5", "unit": "g/10min",
                                        "type": "guaranteed", "source": "s1"}])
        report = self.run_import([item])
        self.assertEqual(report.warnings, [])
        g = m.Grade.objects.get(code="T30S")
        self.assertIsNone(g.manufacturer)
        self.assertEqual(g.producers_note, "中国石化多家企业")
        pv = g.property_values.get()
        self.assertEqual((pv.value_min, pv.value_max, pv.value_type), (2.5, 3.5, "guaranteed"))
        # 再导入一次不会重复建
        report = self.run_import([item])
        self.assertEqual(len(report.unchanged), 1)
        self.assertEqual(m.Grade.objects.filter(code="T30S").count(), 1)

    def test_grade_needs_manufacturer_or_producers(self):
        report = self.run_import([_grade_item(manufacturer=None)])
        self.assertFalse(m.Grade.objects.exists())
        self.assertTrue(any("producers" in w for w in report.warnings))

    def test_conditioning_state_is_recorded(self):
        props = [
            {"prop": "拉伸模量", "value": "3000", "unit": "MPa", "state": "dry", "source": "s1"},
            {"prop": "拉伸模量", "value": "1100", "unit": "MPa", "state": "调湿", "source": "s1"},
        ]
        self.run_import([_grade_item(properties=props)])
        states = sorted(m.PropertyValue.objects.values_list("conditioning", flat=True))
        self.assertEqual(states, ["conditioned", "dry"])

    def test_manufacturer_matched_by_alias(self):
        self.run_import([_grade_item(manufacturer="Covestro")])
        self.assertEqual(m.Company.objects.count(), 1)
        self.assertEqual(m.Grade.objects.get().manufacturer.name, "科思创")

    def test_unknown_material_is_skipped(self):
        report = self.run_import([_grade_item(material="不存在的材料")])
        self.assertFalse(m.Grade.objects.exists())
        self.assertTrue(any("没找到对应词条" in w for w in report.warnings))

    def test_grade_pages_render(self):
        item = _grade_item(code="T30S", manufacturer=None, material="PP-H", producers="多家企业")
        self.run_import([_grade_item(), item])
        g = m.Grade.objects.get(code="2805")
        for url in ["/grades/", f"/g/{g.pk}/", f"/c/{g.manufacturer_id}/", f"/e/{self.pc.pk}/",
                    f"/g/{m.Grade.objects.get(code='T30S').pk}/", "/search/?q=2805"]:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
        self.assertContains(self.client.get("/grades/"), "多家生产")


class RepoGradesTests(TestCase):
    """仓库 content/grades 里的牌号必须能无警告地导入，并且每个数字都有来源。"""

    def test_repo_grades_import_cleanly(self):
        from django.conf import settings
        from .content import Importer, read_content_dir
        from .grades_import import GradeImporter, read_grades_dir
        Importer(read_content_dir(settings.CONTENT_DIR)).run()
        companies, grades = read_grades_dir(settings.CONTENT_DIR / "grades")
        self.assertGreaterEqual(len(grades), 20)
        report = GradeImporter(companies, grades).run()
        self.assertEqual(report.warnings, [])
        self.assertEqual(len(report.created), len(grades))
        self.assertFalse(m.PropertyValue.objects.filter(source__isnull=True).exists())
        # 每个牌号都写了一句话介绍和来源
        for g in m.Grade.objects.all():
            self.assertTrue(g.summary, g.code)
            self.assertTrue(g.sources.exists(), g.code)
            self.assertTrue(g.manufacturer_id or g.producers_note, g.code)
