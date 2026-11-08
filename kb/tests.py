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
        cls.tensile = m.PropertyDefinition.objects.create(
            name_zh="拉伸强度", group=m.PropertyDefinition.Group.MECHANICAL, si_unit="MPa",
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


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class SeedAndPageTests(TestCase):
    def test_seed_data_present(self):
        self.assertTrue(m.CompanyType.objects.filter(name="生产商").exists())
        hdt = m.PropertyDefinition.objects.get(abbr="HDT")
        self.assertEqual(hdt.si_unit, "°C")

    def test_home_requires_login(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    def test_home_search_after_login(self):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_superuser("tester", "", "a-long-test-password")
        self.client.force_login(user)
        m.Entry.objects.create(kind=m.EntryKind.MATERIAL, name_zh="聚丙烯", abbr="PP", one_liner="最常见的通用塑料之一")
        resp = self.client.get("/", {"q": "pp"})
        self.assertContains(resp, "聚丙烯")
        self.assertContains(resp, "最常见的通用塑料之一")
        resp = self.client.get("/", {"q": "不存在的词"})
        self.assertContains(resp, "新建一个词条")

    def test_admin_pages_load(self):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_superuser("tester", "", "a-long-test-password")
        self.client.force_login(user)
        for url in ["/admin/", "/admin/kb/entry/add/", "/admin/kb/grade/add/", "/admin/kb/priceseries/add/",
                    "/admin/kb/entry/", "/admin/kb/propertydefinition/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
