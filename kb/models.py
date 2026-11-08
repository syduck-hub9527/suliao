"""
塑料行业学习与资料平台 —— 数据库模型（Django）  v1

一共 22 张表，分 6 组：
  A 知识百科：Category 分类、Entry 词条、EntryRelation 词条关系、Alias 别名
  B 行业实体：CompanyType 公司类型、Company 公司、Brand 品牌、Plant 工厂、Grade 牌号、GradePlant 牌号-工厂
  C 性能数据：Standard 测试标准、PropertyDefinition 性能指标、PropertyValue 性能值
  D 资料来源：Source 来源、Document 技术文件
  E 价格行情：PriceSeries 价格序列、PricePoint 价格点
  F 学习记录：LearningPath 学习路线、PathItem 路线条目、EntryProgress 学习进度、Note 笔记、QARecord 问答记录

三条硬规则：
  1. 牌号、工厂、性能值、价格都要能追溯到 Source（来源）。
  2. verify_status（信不信得过）和 origin（谁写的）分开记，AI 写的内容永远标得出来。
  3. 所有叫法（缩写/英文/俗称/商品名/旧名/CAS）都进 Alias 表，搜索先查它。
     词条、公司、品牌、牌号的主名称保存时会自动同步进 Alias 表。

个人使用：不区分用户、不设权限。数据库：SQLite。
"""

import re
import unicodedata

from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


# ============================================================
# 工具函数
# ============================================================

_SEPARATORS = re.compile(r"[\s\-_/\.·・,，、()（）\[\]【】]+")


def normalize(text: str) -> str:
    """把各种写法统一成同一个“搜索键”。

    全角转半角、英文转大写、去掉空格和常见分隔符。
    例：“PA 66”“pa-66”“ＰＡ６６” → “PA66”；“9003-07-0” → “9003070”。
    存数据和搜索时都用它，两边才对得上。
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text).upper()
    return _SEPARATORS.sub("", t)


_CAS_RE = re.compile(r"^(\d{2,7})-(\d{2})-(\d)$")


def is_valid_cas(cas: str) -> bool:
    """检查 CAS 号格式和最后一位校验码，防止录错。"""
    m = _CAS_RE.match((cas or "").strip())
    if not m:
        return False
    body = (m.group(1) + m.group(2))[::-1]
    total = sum((i + 1) * int(d) for i, d in enumerate(body))
    return total % 10 == int(m.group(3))


# ============================================================
# 通用选项
# ============================================================

class VerifyStatus(models.TextChoices):
    """信不信得过。"""
    UNVERIFIED = "unverified", "待核实"
    PARTIAL = "partial", "部分核实"
    VERIFIED = "verified", "已核实"
    OUTDATED = "outdated", "已过期"
    DISPUTED = "disputed", "有争议"
    UNKNOWN = "unknown", "未知"


class ContentOrigin(models.TextChoices):
    """是谁写的。"""
    SELF = "self", "自己写的"
    EXCERPT = "excerpt", "资料摘录"
    AI_DRAFT = "ai_draft", "AI 草稿（未核对）"
    AI_CHECKED = "ai_checked", "AI 草稿（已核对）"


class Difficulty(models.IntegerChoices):
    INTRO = 1, "入门"
    BASIC = 2, "基础"
    ADVANCED = 3, "进阶"
    EXPERT = 4, "专业"


class EntryKind(models.TextChoices):
    """词条种类。分类树也按这个分。"""
    MATERIAL = "material", "材料"
    ADDITIVE = "additive", "助剂/填料"
    PROCESS = "process", "加工工艺"
    PROPERTY = "property", "性能指标"
    TERM = "term", "术语/概念"
    APPLICATION = "application", "应用领域"
    REGULATION = "regulation", "法规/标准/认证"
    DEFECT = "defect", "成型缺陷"


class NameAliasMixin:
    """保存时，把主名称（缩写/中文名/英文名/牌号等）自动写进别名表，搜索只需查别名表。

    改名后旧名字会留在别名表里，正好可以当“旧名称”继续被搜到。
    """

    def name_alias_pairs(self):
        return []

    def sync_name_aliases(self):
        ct = ContentType.objects.get_for_model(type(self))
        for text, kind in self.name_alias_pairs():
            text = (text or "").strip()
            key = normalize(text)
            if not key:
                continue
            Alias.objects.get_or_create(
                content_type=ct, object_id=self.pk, norm=key,
                defaults={"text": text, "kind": kind},
            )

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.sync_name_aliases()


class TimeStamped(models.Model):
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        abstract = True


# ============================================================
# D 组：资料来源（放前面，因为很多表都要引用它）
# ============================================================

class Document(TimeStamped):
    """技术文件：TDS、SDS、COA、UL 黄卡、检测报告等。文件本身存在 media 目录里。"""

    class Kind(models.TextChoices):
        TDS = "tds", "TDS 技术数据表"
        SDS = "sds", "SDS 安全数据表"
        COA = "coa", "COA 批次检验报告"
        UL = "ul", "UL 认证资料"
        TEST_REPORT = "test_report", "检测报告"
        COMPLIANCE = "compliance", "合规声明（RoHS/REACH/食品接触等）"
        BROCHURE = "brochure", "产品手册/选型指南"
        STANDARD = "standard", "标准文本"
        ARTICLE = "article", "文章/教材/资料"
        OTHER = "other", "其他"

    kind = models.CharField("文件类型", max_length=20, choices=Kind.choices)
    title = models.CharField("标题", max_length=300)
    file = models.FileField("文件", upload_to="documents/%Y/", blank=True)
    url = models.URLField("原始链接", max_length=1000, blank=True)
    company = models.ForeignKey(
        "Company", verbose_name="发布公司", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="documents",
    )
    grades = models.ManyToManyField(
        "Grade", verbose_name="涉及牌号", blank=True, related_name="documents",
    )
    language = models.CharField("语言", max_length=20, blank=True, help_text="如：中文、英文")
    version = models.CharField("版本号", max_length=50, blank=True)
    published_on = models.DateField("发布/修订日期", null=True, blank=True)
    retrieved_on = models.DateField("下载日期", null=True, blank=True)
    sha256 = models.CharField(
        "文件指纹", max_length=64, blank=True, db_index=True,
        help_text="用来发现重复上传的同一份文件，由程序自动计算",
    )
    note = models.TextField("备注", blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "技术文件"
        ordering = ["-retrieved_on", "-created_at"]

    def __str__(self):
        return f"[{self.get_kind_display()}] {self.title}"


class Source(TimeStamped):
    """来源：任何一条数据“从哪来”。可以指向一份技术文件，也可以是网页、书、某人口述。"""

    class Kind(models.TextChoices):
        MAKER_DOC = "maker_doc", "厂家技术文件"
        MAKER_WEB = "maker_web", "厂家官网"
        STANDARD = "standard", "标准/法规原文"
        CERT = "cert", "认证机构（如 UL）"
        LAB = "lab", "第三方检测报告"
        EXCHANGE = "exchange", "交易所/官方统计"
        MARKET = "market", "行情资讯"
        TRADER = "trader", "供应商/贸易商报价"
        BOOK = "book", "书籍/教材"
        MEDIA = "media", "行业媒体/文章"
        PERSON = "person", "同事/客户/前辈口述"
        AI = "ai", "AI 回答（需核对）"
        OTHER = "other", "其他"

    kind = models.CharField("来源类型", max_length=20, choices=Kind.choices)
    title = models.CharField("来源名称", max_length=300)
    publisher = models.CharField("发布方", max_length=200, blank=True)
    url = models.URLField("链接", max_length=1000, blank=True)
    document = models.ForeignKey(
        Document, verbose_name="对应文件", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="source_records",
    )
    published_on = models.DateField("发布日期", null=True, blank=True)
    accessed_on = models.DateField("获取日期", null=True, blank=True)
    note = models.TextField("备注", blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "来源"
        ordering = ["-accessed_on", "-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()}：{self.title}"


# ============================================================
# A 组：知识百科
# ============================================================

class Category(TimeStamped):
    """分类树。例：材料 > 通用塑料 > 聚烯烃。每种词条各有一棵树。"""

    kind = models.CharField("属于哪棵树", max_length=20, choices=EntryKind.choices)
    name = models.CharField("分类名", max_length=100)
    parent = models.ForeignKey(
        "self", verbose_name="上级分类", on_delete=models.PROTECT,
        null=True, blank=True, related_name="children",
    )
    order = models.IntegerField("排序", default=0)
    description = models.TextField("说明", blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "分类"
        ordering = ["kind", "order", "name"]

    def __str__(self):
        names, node, depth = [], self, 0
        while node is not None and depth < 10:
            names.append(node.name)
            node, depth = node.parent, depth + 1
        return " > ".join(reversed(names))

    def clean(self):
        if self.parent_id and self.parent.kind != self.kind:
            raise ValidationError("上级分类必须属于同一棵树。")
        node, depth = self.parent, 0
        while node is not None and depth < 50:
            if self.pk and node.pk == self.pk:
                raise ValidationError("分类不能挂在自己下面。")
            node, depth = node.parent, depth + 1


class Entry(NameAliasMixin, TimeStamped):
    """词条：一切知识点。材料、助剂、工艺、性能指标、术语、应用、法规、缺陷都在这里。"""

    kind = models.CharField("词条种类", max_length=20, choices=EntryKind.choices, db_index=True)
    name_zh = models.CharField("中文名", max_length=200, db_index=True)
    name_en = models.CharField("英文名", max_length=200, blank=True)
    abbr = models.CharField("常用缩写", max_length=50, blank=True, db_index=True,
                            help_text="最常用的一个；其他缩写写进别名")
    category = models.ForeignKey(
        Category, verbose_name="分类", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="entries",
    )
    parent = models.ForeignKey(
        "self", verbose_name="上级词条", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="children",
        help_text="例：PA66 的上级是 PA；均聚 PP 的上级是 PP",
    )

    # —— 内容：小白模式 / 专业模式 ——
    one_liner = models.CharField("一句话解释", max_length=200, blank=True)
    easy_text = models.TextField("小白解释", blank=True, help_text="Markdown，用大白话写")
    pro_text = models.TextField("专业内容", blank=True, help_text="Markdown")
    pitfalls = models.TextField("常见误区", blank=True, help_text="容易混淆、不能推断的地方")

    difficulty = models.IntegerField("难度", choices=Difficulty.choices, default=Difficulty.INTRO)
    origin = models.CharField("内容出处", max_length=20, choices=ContentOrigin.choices,
                              default=ContentOrigin.SELF)
    verify_status = models.CharField("核验状态", max_length=20, choices=VerifyStatus.choices,
                                     default=VerifyStatus.UNVERIFIED)
    sources = models.ManyToManyField(Source, verbose_name="来源", blank=True, related_name="entries")
    aliases = GenericRelation("Alias")
    imported_hash = models.CharField(
        "导入指纹", max_length=64, blank=True, editable=False,
        help_text="从 content/ 知识文件导入时记下的内容指纹；在后台改过的词条不会被再次导入覆盖",
    )

    class Meta:
        verbose_name = verbose_name_plural = "词条"
        ordering = ["kind", "name_zh"]
        constraints = [
            models.UniqueConstraint(fields=["kind", "name_zh"], name="uniq_entry_kind_name"),
        ]

    def __str__(self):
        return f"{self.abbr} {self.name_zh}".strip() if self.abbr else self.name_zh

    def name_alias_pairs(self):
        return [(self.abbr, Alias.Kind.ABBR), (self.name_zh, Alias.Kind.NAME_ZH), (self.name_en, Alias.Kind.NAME_EN)]

    def clean(self):
        if self.category_id and self.category.kind != self.kind:
            raise ValidationError({"category": "分类必须和词条种类一致。"})
        if self.parent_id and self.parent_id == self.pk:
            raise ValidationError({"parent": "上级词条不能是自己。"})


class EntryRelation(TimeStamped):
    """词条之间的关系，用来把知识连成网。例：PA6 —容易混淆— PA66。"""

    class Kind(models.TextChoices):
        RELATED = "related", "相关"
        CONFUSABLE = "confusable", "容易混淆"
        USED_WITH = "used_with", "常搭配使用"
        USED_IN = "used_in", "用于/应用在"
        ALTERNATIVE = "alternative", "可能替代（需验证）"

    from_entry = models.ForeignKey(Entry, verbose_name="词条", on_delete=models.CASCADE,
                                   related_name="relations_out")
    to_entry = models.ForeignKey(Entry, verbose_name="关联词条", on_delete=models.CASCADE,
                                 related_name="relations_in")
    kind = models.CharField("关系", max_length=20, choices=Kind.choices)
    note = models.CharField("说明", max_length=300, blank=True)
    source = models.ForeignKey(Source, verbose_name="来源", on_delete=models.SET_NULL,
                               null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = verbose_name_plural = "词条关系"
        constraints = [
            models.UniqueConstraint(fields=["from_entry", "to_entry", "kind"], name="uniq_entry_relation"),
            models.CheckConstraint(condition=~Q(from_entry=F("to_entry")), name="relation_not_self"),
        ]

    def __str__(self):
        return f"{self.from_entry} —{self.get_kind_display()}— {self.to_entry}"


class Alias(models.Model):
    """别名：一个东西的所有叫法。可以挂在词条、公司、品牌、牌号上。

    例：POM ← 赛钢（俗称）、聚甲醛（中文）、Polyoxymethylene（英文）、Acetal（英文俗称）
    一个别名可以对应多个东西（如 PIR），搜索时会把候选都列出来。
    """

    class Kind(models.TextChoices):
        ABBR = "abbr", "缩写"
        NAME_ZH = "name_zh", "中文名/学名"
        NAME_EN = "name_en", "英文名"
        NICKNAME = "nickname", "行业俗称"
        TRADE = "trade", "商品名/品牌叫法"
        FORMER = "former", "旧名称"
        TYPO = "typo", "常见错写"
        CAS = "cas", "CAS 号"
        OTHER = "other", "其他"

    text = models.CharField("写法", max_length=200)
    norm = models.CharField("搜索键", max_length=200, db_index=True, editable=False)
    kind = models.CharField("类型", max_length=20, choices=Kind.choices)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    target = GenericForeignKey("content_type", "object_id")
    note = models.CharField("备注", max_length=200, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "别名"
        indexes = [models.Index(fields=["content_type", "object_id"])]
        constraints = [
            models.UniqueConstraint(fields=["content_type", "object_id", "norm"], name="uniq_alias_per_target"),
        ]

    def __str__(self):
        return f"{self.text}（{self.get_kind_display()}）"

    def clean(self):
        if self.kind == self.Kind.CAS and not is_valid_cas(self.text):
            raise ValidationError({"text": "CAS 号格式或校验位不对，请核对。"})

    def save(self, *args, **kwargs):
        self.norm = normalize(self.text)
        super().save(*args, **kwargs)


# ============================================================
# B 组：行业实体
# ============================================================

class CompanyType(models.Model):
    """公司类型（固定几种，后台里先录好）：生产商、改性厂、助剂厂商、母粒厂、代理商、经销商、贸易商、加工厂、检测机构。"""

    name = models.CharField("类型", max_length=50, unique=True)
    order = models.IntegerField("排序", default=0)

    class Meta:
        verbose_name = verbose_name_plural = "公司类型"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class Company(NameAliasMixin, TimeStamped):
    """公司：生产商、改性厂、贸易商……一家公司可以有多个类型。"""

    name = models.CharField("常用名称", max_length=200, db_index=True)
    name_zh = models.CharField("中文全称", max_length=300, blank=True)
    name_en = models.CharField("英文全称", max_length=300, blank=True)
    types = models.ManyToManyField(CompanyType, verbose_name="公司类型", blank=True, related_name="companies")
    country = models.CharField("总部国家/地区", max_length=100, blank=True)
    city = models.CharField("总部城市", max_length=100, blank=True)
    website = models.URLField("官网", max_length=500, blank=True)
    parent = models.ForeignKey(
        "self", verbose_name="所属集团", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="subsidiaries",
    )
    intro = models.TextField("简介", blank=True)
    verify_status = models.CharField("核验状态", max_length=20, choices=VerifyStatus.choices,
                                     default=VerifyStatus.UNVERIFIED)
    last_checked_on = models.DateField("最后核实日期", null=True, blank=True)
    sources = models.ManyToManyField(Source, verbose_name="来源", blank=True, related_name="companies")
    aliases = GenericRelation(Alias)

    class Meta:
        verbose_name = verbose_name_plural = "公司"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def name_alias_pairs(self):
        return [(self.name, Alias.Kind.OTHER), (self.name_zh, Alias.Kind.NAME_ZH), (self.name_en, Alias.Kind.NAME_EN)]


class Brand(NameAliasMixin, TimeStamped):
    """品牌：如 Lexan、Ultramid。品牌可能换主人，历史写在 history 里。"""

    name = models.CharField("品牌名", max_length=100, db_index=True)
    owner = models.ForeignKey(Company, verbose_name="当前所属公司", on_delete=models.PROTECT,
                              null=True, blank=True, related_name="brands")
    intro = models.TextField("简介", blank=True)
    history = models.TextField("归属变化", blank=True, help_text="例：原属 A 公司，某年起归 B 公司")
    sources = models.ManyToManyField(Source, verbose_name="来源", blank=True, related_name="brands")
    aliases = GenericRelation(Alias)

    class Meta:
        verbose_name = verbose_name_plural = "品牌"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="uniq_brand_owner_name"),
        ]

    def __str__(self):
        return self.name

    def name_alias_pairs(self):
        return [(self.name, Alias.Kind.TRADE)]


class Plant(TimeStamped):
    """工厂：实际生产的地点。总部、销售办公室、仓库都不算工厂。"""

    class Status(models.TextChoices):
        RUNNING = "running", "运行中"
        BUILDING = "building", "在建"
        IDLE = "idle", "停车/闲置"
        CLOSED = "closed", "已关闭"
        UNKNOWN = "unknown", "未知"

    company = models.ForeignKey(Company, verbose_name="所属公司", on_delete=models.PROTECT, related_name="plants")
    name = models.CharField("工厂名称", max_length=200)
    country = models.CharField("国家/地区", max_length=100, blank=True)
    city = models.CharField("省/市", max_length=100, blank=True)
    address = models.CharField("地址", max_length=300, blank=True)
    products_note = models.TextField("主要产品", blank=True)
    capacity_note = models.CharField("产能", max_length=200, blank=True,
                                     help_text="写清单位和年份，例：XX 万吨/年（2025 年数据）")
    status = models.CharField("运行状态", max_length=20, choices=Status.choices, default=Status.UNKNOWN)
    status_on = models.DateField("状态确认日期", null=True, blank=True)
    verify_status = models.CharField("核验状态", max_length=20, choices=VerifyStatus.choices,
                                     default=VerifyStatus.UNVERIFIED)
    sources = models.ManyToManyField(Source, verbose_name="来源", blank=True, related_name="plants")
    note = models.TextField("备注", blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "工厂"
        ordering = ["company__name", "name"]

    def __str__(self):
        return f"{self.company} · {self.name}"


class Grade(NameAliasMixin, TimeStamped):
    """牌号：一个具体产品。树脂、改性料、母粒、助剂、填料的商品牌号都放这里。"""

    class ProductType(models.TextChoices):
        RESIN = "resin", "基础树脂（原料）"
        COMPOUND = "compound", "改性料/合金"
        MASTERBATCH = "masterbatch", "色母/功能母粒"
        ADDITIVE = "additive", "助剂"
        FILLER = "filler", "填料/增强材料"
        RECYCLED = "recycled", "再生料"
        OTHER = "other", "其他"

    class Lifecycle(models.TextChoices):
        ACTIVE = "active", "在产"
        DISCONTINUED = "discontinued", "已停产"
        UNKNOWN = "unknown", "未知"

    code = models.CharField("牌号", max_length=100, help_text="照厂家写法，例：141R")
    code_norm = models.CharField("搜索键", max_length=100, db_index=True, editable=False)
    full_name = models.CharField("完整叫法", max_length=200, blank=True, help_text="例：LEXAN 141R")
    product_type = models.CharField("产品类型", max_length=20, choices=ProductType.choices)
    base_entry = models.ForeignKey(
        Entry, verbose_name="属于什么材料/助剂", on_delete=models.PROTECT, related_name="grades",
        limit_choices_to={"kind__in": [EntryKind.MATERIAL, EntryKind.ADDITIVE]},
    )
    manufacturer = models.ForeignKey(Company, verbose_name="生产商", on_delete=models.PROTECT,
                                     null=True, blank=True, related_name="grades")
    brand = models.ForeignKey(Brand, verbose_name="品牌", on_delete=models.SET_NULL,
                              null=True, blank=True, related_name="grades")
    description = models.TextField("特点与用途", blank=True, help_text="尽量照厂家原话")
    applications = models.ManyToManyField(
        Entry, verbose_name="应用领域", blank=True, related_name="applied_grades",
        limit_choices_to={"kind": EntryKind.APPLICATION},
    )
    processes = models.ManyToManyField(
        Entry, verbose_name="适用工艺", blank=True, related_name="processed_grades",
        limit_choices_to={"kind": EntryKind.PROCESS},
    )
    plants = models.ManyToManyField(Plant, verbose_name="生产工厂", through="GradePlant", blank=True,
                                    related_name="grades")
    lifecycle = models.CharField("生产状态", max_length=20, choices=Lifecycle.choices, default=Lifecycle.UNKNOWN)
    verify_status = models.CharField("核验状态", max_length=20, choices=VerifyStatus.choices,
                                     default=VerifyStatus.UNVERIFIED)
    sources = models.ManyToManyField(Source, verbose_name="来源", blank=True, related_name="grades")
    aliases = GenericRelation(Alias)
    note = models.TextField("备注", blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "牌号"
        ordering = ["code_norm"]
        constraints = [
            models.UniqueConstraint(fields=["manufacturer", "code_norm"], name="uniq_grade_per_maker"),
        ]

    def __str__(self):
        if self.full_name:
            return self.full_name
        prefix = self.brand or self.manufacturer
        return f"{prefix} {self.code}" if prefix else self.code

    def name_alias_pairs(self):
        return [(self.full_name, Alias.Kind.TRADE)]

    def save(self, *args, **kwargs):
        self.code_norm = normalize(self.code)
        super().save(*args, **kwargs)


class GradePlant(models.Model):
    """哪个牌号在哪个工厂生产（有证据才录）。"""

    grade = models.ForeignKey(Grade, verbose_name="牌号", on_delete=models.CASCADE)
    plant = models.ForeignKey(Plant, verbose_name="工厂", on_delete=models.CASCADE)
    source = models.ForeignKey(Source, verbose_name="来源", on_delete=models.PROTECT,
                               null=True, blank=True, related_name="+")
    verify_status = models.CharField("核验状态", max_length=20, choices=VerifyStatus.choices,
                                     default=VerifyStatus.UNVERIFIED)
    note = models.CharField("备注", max_length=300, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "牌号-工厂"
        constraints = [
            models.UniqueConstraint(fields=["grade", "plant"], name="uniq_grade_plant"),
        ]

    def __str__(self):
        return f"{self.grade} @ {self.plant}"


# ============================================================
# C 组：性能数据
# ============================================================

class Standard(TimeStamped):
    """测试标准：例 ISO 527-2、ASTM D638、GB/T 1040.2。"""

    class Org(models.TextChoices):
        ISO = "ISO", "ISO"
        ASTM = "ASTM", "ASTM"
        GB = "GB", "GB/GB/T（中国）"
        IEC = "IEC", "IEC"
        UL = "UL", "UL"
        DIN = "DIN", "DIN/EN"
        JIS = "JIS", "JIS"
        OTHER = "OTHER", "其他"

    code = models.CharField("标准号", max_length=100, help_text="例：ISO 527-2")
    year = models.CharField("版本/年份", max_length=20, blank=True)
    title = models.CharField("标准名称", max_length=300, blank=True)
    org = models.CharField("体系", max_length=10, choices=Org.choices)
    explain_entry = models.ForeignKey(Entry, verbose_name="讲解词条", on_delete=models.SET_NULL,
                                      null=True, blank=True, related_name="standards")
    url = models.URLField("链接", max_length=500, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "测试标准"
        ordering = ["org", "code"]
        constraints = [
            models.UniqueConstraint(fields=["code", "year"], name="uniq_standard_code_year"),
        ]

    def __str__(self):
        return f"{self.code}:{self.year}" if self.year else self.code


class PropertyDefinition(TimeStamped):
    """性能指标的定义：拉伸强度、MFR、HDT……新增一个指标只需在这里加一行。"""

    class Group(models.TextChoices):
        BASIC = "basic", "基础性能"
        MECHANICAL = "mechanical", "力学性能"
        THERMAL = "thermal", "热性能"
        ELECTRICAL = "electrical", "电性能"
        FLAME = "flame", "燃烧性能"
        PROCESSING = "processing", "加工性能"
        OPTICAL = "optical", "光学性能"
        OTHER = "other", "其他"

    class ValueKind(models.TextChoices):
        NUMBER = "number", "数值"
        TEXT = "text", "文字/等级（如 V-0）"

    name_zh = models.CharField("中文名", max_length=100, unique=True)
    name_en = models.CharField("英文名", max_length=150, blank=True)
    abbr = models.CharField("缩写", max_length=30, blank=True)
    group = models.CharField("分组", max_length=20, choices=Group.choices)
    value_kind = models.CharField("数据形式", max_length=10, choices=ValueKind.choices, default=ValueKind.NUMBER)
    si_unit = models.CharField("统一单位", max_length=30, blank=True,
                               help_text="换算后统一用的单位，例：MPa、°C、g/10min、kJ/m²")
    common_units = models.CharField("常见单位", max_length=200, blank=True, help_text="例：MPa, psi, kgf/cm²")
    required_conditions = models.CharField("必须记录的条件", max_length=300, blank=True,
                                           help_text="例：MFR 必须记温度和负荷")
    entry = models.OneToOneField(
        Entry, verbose_name="讲解词条", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="property_definition", limit_choices_to={"kind": EntryKind.PROPERTY},
    )
    order = models.IntegerField("排序", default=0)

    class Meta:
        verbose_name = verbose_name_plural = "性能指标"
        ordering = ["group", "order", "name_zh"]

    def __str__(self):
        return f"{self.name_zh}（{self.abbr}）" if self.abbr else self.name_zh


class PropertyValue(TimeStamped):
    """性能值：某个牌号（或某类材料）的某项性能。原始写法照抄，另存一份换算值。"""

    class ValueType(models.TextChoices):
        TYPICAL = "typical", "典型值"
        GUARANTEED = "guaranteed", "保证值/规格值"
        MEASURED = "measured", "实测值"
        RANGE = "range", "范围"
        ESTIMATED = "estimated", "估算值"
        LITERATURE = "literature", "教材/文献参考值"

    class Direction(models.TextChoices):
        NA = "", "不适用/未注明"
        FLOW = "flow", "平行于流动方向"
        CROSS = "cross", "垂直于流动方向"

    class Conditioning(models.TextChoices):
        NA = "", "未注明"
        DRY = "dry", "干态"
        CONDITIONED = "conditioned", "调湿后"
        OTHER = "other", "其他（见条件）"

    # 属于谁：牌号 或 材料词条，二选一
    grade = models.ForeignKey(Grade, verbose_name="牌号", on_delete=models.CASCADE,
                              null=True, blank=True, related_name="property_values")
    entry = models.ForeignKey(Entry, verbose_name="材料（通用数据）", on_delete=models.CASCADE,
                              null=True, blank=True, related_name="property_values",
                              help_text="不针对具体牌号的一般数据，例：PP 的一般密度范围")
    prop = models.ForeignKey(PropertyDefinition, verbose_name="性能指标", on_delete=models.PROTECT,
                             related_name="values")

    # 照抄原文
    value_text = models.CharField("原文写法", max_length=100, help_text="照抄，例：62、60–65、V-0、不断裂")
    value_num = models.FloatField("数值", null=True, blank=True)
    value_min = models.FloatField("最小值", null=True, blank=True)
    value_max = models.FloatField("最大值", null=True, blank=True)
    unit = models.CharField("原文单位", max_length=30, blank=True)

    # 换算成统一单位（用于对比和筛选）
    value_si = models.FloatField("换算值", null=True, blank=True)
    value_si_min = models.FloatField("换算最小值", null=True, blank=True)
    value_si_max = models.FloatField("换算最大值", null=True, blank=True)

    value_type = models.CharField("数据类型", max_length=20, choices=ValueType.choices, default=ValueType.TYPICAL)

    # 测试条件
    standard = models.ForeignKey(Standard, verbose_name="测试标准", on_delete=models.PROTECT,
                                 null=True, blank=True, related_name="values")
    standard_text = models.CharField("测试标准（原文）", max_length=100, blank=True,
                                     help_text="标准表里还没有时先照抄在这里")
    conditions = models.CharField("测试条件", max_length=300, blank=True,
                                  help_text="例：230°C/2.16kg；23°C，缺口")
    thickness_mm = models.FloatField("试样厚度 (mm)", null=True, blank=True)
    direction = models.CharField("方向", max_length=10, choices=Direction.choices, blank=True, default="")
    conditioning = models.CharField("状态调节", max_length=20, choices=Conditioning.choices, blank=True,
                                    default="", help_text="尼龙等吸水材料尤其重要")

    # 来源（必填）
    source = models.ForeignKey(Source, verbose_name="来源", on_delete=models.PROTECT, related_name="property_values")
    document = models.ForeignKey(Document, verbose_name="具体文件", on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name="property_values")
    page = models.CharField("页码/位置", max_length=50, blank=True)
    verify_status = models.CharField("核验状态", max_length=20, choices=VerifyStatus.choices,
                                     default=VerifyStatus.UNVERIFIED)
    note = models.CharField("备注", max_length=300, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "性能值"
        indexes = [models.Index(fields=["prop", "value_si"])]
        constraints = [
            models.CheckConstraint(
                condition=(Q(grade__isnull=False, entry__isnull=True) | Q(grade__isnull=True, entry__isnull=False)),
                name="pv_grade_xor_entry",
            ),
            models.CheckConstraint(
                condition=(Q(value_min__isnull=True) | Q(value_max__isnull=True) | Q(value_min__lte=F("value_max"))),
                name="pv_min_le_max",
            ),
        ]

    def __str__(self):
        owner = self.grade or self.entry
        return f"{owner} · {self.prop.name_zh} = {self.value_text} {self.unit}".strip()

    def fill_si(self):
        """原文单位和统一单位相同时，直接复制。不同单位的换算交给导入程序（建议用 pint 库）。"""
        if self.unit and self.prop_id and self.unit == self.prop.si_unit:
            if self.value_si is None:
                self.value_si = self.value_num
            if self.value_si_min is None:
                self.value_si_min = self.value_min
            if self.value_si_max is None:
                self.value_si_max = self.value_max

    def save(self, *args, **kwargs):
        self.fill_si()
        super().save(*args, **kwargs)


# ============================================================
# E 组：价格行情
# ============================================================

class PriceSeries(TimeStamped):
    """价格序列：一条“条件固定”的价格曲线。地区、币种、含税、贸易条件都定好，每天往里记点。

    例：“大商所 聚丙烯 主力合约 结算价”“某贸易商 某牌号 华东 含税送到价”。
    条件不同的价格放在不同序列里，避免混在一起比。
    """

    class PriceType(models.TextChoices):
        FUTURES = "futures", "期货结算价"
        SPOT = "spot", "市场现货价"
        EX_WORKS = "ex_works", "厂家出厂价"
        DISTRIBUTOR = "distributor", "代理/经销商报价"
        TRADER = "trader", "贸易商报价"
        IMPORT = "import", "进口价"
        EXPORT = "export", "出口价"
        OTHER = "other", "其他"

    class Currency(models.TextChoices):
        CNY = "CNY", "人民币"
        USD = "USD", "美元"
        EUR = "EUR", "欧元"
        JPY = "JPY", "日元"
        KRW = "KRW", "韩元"
        OTHER = "OTHER", "其他"

    class Tax(models.TextChoices):
        INCLUDED = "included", "含税"
        EXCLUDED = "excluded", "不含税"
        UNKNOWN = "unknown", "未知"

    name = models.CharField("序列名称", max_length=200)
    entry = models.ForeignKey(Entry, verbose_name="材料", on_delete=models.PROTECT, null=True, blank=True,
                              related_name="price_series", limit_choices_to={"kind": EntryKind.MATERIAL})
    grade = models.ForeignKey(Grade, verbose_name="牌号", on_delete=models.PROTECT, null=True, blank=True,
                              related_name="price_series")
    spec_note = models.CharField("规格说明", max_length=200, blank=True, help_text="例：PP 拉丝级")
    price_type = models.CharField("价格类型", max_length=20, choices=PriceType.choices)
    market = models.CharField("市场/地区", max_length=100, blank=True, help_text="例：华东、大连商品交易所")
    currency = models.CharField("币种", max_length=10, choices=Currency.choices, default=Currency.CNY)
    unit = models.CharField("计价单位", max_length=20, default="吨", help_text="例：吨、千克")
    tax = models.CharField("含税", max_length=10, choices=Tax.choices, default=Tax.UNKNOWN)
    incoterm = models.CharField("贸易条件", max_length=20, blank=True, help_text="例：EXW、FOB、CFR、CIF、送到")
    delivery_place = models.CharField("交货地点", max_length=100, blank=True)
    source = models.ForeignKey(Source, verbose_name="来源", on_delete=models.PROTECT, related_name="price_series")
    is_active = models.BooleanField("仍在跟踪", default=True)
    note = models.TextField("备注", blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "价格序列"
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(entry__isnull=False) | Q(grade__isnull=False)),
                name="price_series_has_target",
            ),
        ]

    def __str__(self):
        return self.name


class PricePoint(models.Model):
    """价格点：某一天的价格。历史数据只增不改。"""

    series = models.ForeignKey(PriceSeries, verbose_name="价格序列", on_delete=models.CASCADE, related_name="points")
    date = models.DateField("价格日期")
    price = models.DecimalField("价格", max_digits=14, decimal_places=4)
    price_low = models.DecimalField("区间低", max_digits=14, decimal_places=4, null=True, blank=True)
    price_high = models.DecimalField("区间高", max_digits=14, decimal_places=4, null=True, blank=True)
    min_qty = models.CharField("起订量", max_length=50, blank=True)
    valid_until = models.DateField("有效期至", null=True, blank=True)
    document = models.ForeignKey(Document, verbose_name="凭证", on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name="+")
    note = models.CharField("备注", max_length=300, blank=True, help_text="例：为什么涨/跌")
    recorded_at = models.DateTimeField("记录时间", auto_now_add=True)

    class Meta:
        verbose_name = verbose_name_plural = "价格点"
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(fields=["series", "date"], name="uniq_price_series_date"),
            models.CheckConstraint(
                condition=(Q(price_low__isnull=True) | Q(price_high__isnull=True) | Q(price_low__lte=F("price_high"))),
                name="price_low_le_high",
            ),
        ]

    def __str__(self):
        return f"{self.series} {self.date}: {self.price}"


# ============================================================
# F 组：学习记录
# ============================================================

class LearningPath(TimeStamped):
    """学习路线，例：“入行 8 阶段”。"""

    name = models.CharField("路线名称", max_length=100, unique=True)
    description = models.TextField("说明", blank=True)
    order = models.IntegerField("排序", default=0)

    class Meta:
        verbose_name = verbose_name_plural = "学习路线"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class PathItem(models.Model):
    """路线里的一步：属于哪个阶段、学哪个词条、学完能做到什么。"""

    path = models.ForeignKey(LearningPath, verbose_name="路线", on_delete=models.CASCADE, related_name="items")
    stage = models.CharField("阶段", max_length=100, help_text="例：第 1 阶段：认识塑料行业")
    order = models.PositiveIntegerField("顺序", default=0)
    entry = models.ForeignKey(Entry, verbose_name="词条", on_delete=models.PROTECT, related_name="path_items")
    goal = models.CharField("学完应该能……", max_length=300, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "路线条目"
        ordering = ["path", "order"]
        constraints = [
            models.UniqueConstraint(fields=["path", "entry"], name="uniq_path_entry"),
        ]

    def __str__(self):
        return f"{self.path} · {self.stage} · {self.entry}"


class EntryProgress(models.Model):
    """学习进度：每个词条学到哪了。标“还不懂”的就是生词本。"""

    class Status(models.TextChoices):
        NEW = "new", "未学"
        LEARNING = "learning", "学习中"
        CONFUSED = "confused", "还不懂"
        MASTERED = "mastered", "已掌握"

    entry = models.OneToOneField(Entry, verbose_name="词条", on_delete=models.CASCADE, related_name="progress")
    status = models.CharField("状态", max_length=20, choices=Status.choices, default=Status.NEW)
    starred = models.BooleanField("收藏", default=False)
    stuck_note = models.CharField("卡在哪里", max_length=300, blank=True)
    view_count = models.PositiveIntegerField("查看次数", default=0)
    last_viewed_at = models.DateTimeField("最近查看", null=True, blank=True)
    last_reviewed_at = models.DateTimeField("最近复习", null=True, blank=True)
    next_review_on = models.DateField("下次复习", null=True, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "学习进度"

    def __str__(self):
        return f"{self.entry}：{self.get_status_display()}"


class Note(TimeStamped):
    """个人笔记，可以挂在词条或牌号上。"""

    title = models.CharField("标题", max_length=200)
    body = models.TextField("内容", blank=True, help_text="Markdown")
    entries = models.ManyToManyField(Entry, verbose_name="相关词条", blank=True, related_name="notes")
    grades = models.ManyToManyField(Grade, verbose_name="相关牌号", blank=True, related_name="notes")
    tags = models.CharField("标签", max_length=200, blank=True, help_text="逗号分隔")

    class Meta:
        verbose_name = verbose_name_plural = "笔记"
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title


class QARecord(TimeStamped):
    """问答记录：工作中遇到的真实问题 → 查到的答案 → 依据。最贴近实战的学习素材。"""

    class Asker(models.TextChoices):
        CUSTOMER = "customer", "客户"
        COLLEAGUE = "colleague", "同事/前辈"
        SELF = "self", "自己"
        OTHER = "other", "其他"

    class Status(models.TextChoices):
        OPEN = "open", "待查"
        ANSWERED = "answered", "已有答案"
        CONFIRMED = "confirmed", "已找专业人员确认"

    question = models.TextField("问题")
    asker = models.CharField("谁问的", max_length=20, choices=Asker.choices, default=Asker.CUSTOMER)
    context = models.TextField("背景", blank=True, help_text="例：客户做什么产品、什么工艺")
    answer = models.TextField("答案", blank=True)
    status = models.CharField("状态", max_length=20, choices=Status.choices, default=Status.OPEN)
    asked_on = models.DateField("日期", default=timezone.localdate)
    entries = models.ManyToManyField(Entry, verbose_name="相关词条", blank=True, related_name="qa_records")
    grades = models.ManyToManyField(Grade, verbose_name="相关牌号", blank=True, related_name="qa_records")
    sources = models.ManyToManyField(Source, verbose_name="依据", blank=True, related_name="qa_records")

    class Meta:
        verbose_name = verbose_name_plural = "问答记录"
        ordering = ["-asked_on", "-created_at"]

    def __str__(self):
        return self.question[:40]
