"""
数据录入后台。启动网站后打开 /admin/ 就能录数据。
"""

from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline

from . import models as m

admin.site.site_header = "塑料学习资料库 · 管理后台"
admin.site.site_title = "塑料学习资料库"
admin.site.index_title = "数据录入"


# ---------- 内嵌表格 ----------

class AliasInline(GenericTabularInline):
    model = m.Alias
    extra = 1
    fields = ["text", "kind", "note"]


class EntryRelationInline(admin.TabularInline):
    model = m.EntryRelation
    fk_name = "from_entry"
    extra = 0
    autocomplete_fields = ["to_entry", "source"]


class EntryProgressInline(admin.StackedInline):
    model = m.EntryProgress
    extra = 0
    max_num = 1
    fields = ["status", "starred", "stuck_note", "next_review_on"]


class PropertyValueInline(admin.TabularInline):
    model = m.PropertyValue
    fk_name = "grade"
    extra = 0
    fields = ["prop", "value_text", "value_num", "unit", "value_type", "standard", "standard_text",
              "conditions", "thickness_mm", "source", "page", "verify_status"]
    autocomplete_fields = ["prop", "standard", "source"]


class GradePlantInline(admin.TabularInline):
    model = m.GradePlant
    extra = 0
    autocomplete_fields = ["plant", "source"]


class PricePointInline(admin.TabularInline):
    model = m.PricePoint
    extra = 1
    fields = ["date", "price", "price_low", "price_high", "note"]


class PathItemInline(admin.TabularInline):
    model = m.PathItem
    extra = 1
    autocomplete_fields = ["entry"]


# ---------- 各张表 ----------

@admin.register(m.Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ["title", "kind", "publisher", "accessed_on"]
    list_filter = ["kind"]
    search_fields = ["title", "publisher", "url"]
    autocomplete_fields = ["document"]


@admin.register(m.Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ["title", "kind", "company", "version", "published_on", "retrieved_on"]
    list_filter = ["kind"]
    search_fields = ["title", "version", "company__name"]
    autocomplete_fields = ["company", "grades"]


@admin.register(m.Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["__str__", "kind", "order"]
    list_filter = ["kind"]
    search_fields = ["name"]
    autocomplete_fields = ["parent"]


@admin.register(m.Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ["__str__", "kind", "category", "difficulty", "origin", "verify_status", "updated_at"]
    list_filter = ["kind", "difficulty", "origin", "verify_status"]
    search_fields = ["name_zh", "name_en", "abbr", "aliases__text"]
    autocomplete_fields = ["category", "parent", "sources"]
    inlines = [AliasInline, EntryRelationInline, EntryProgressInline]
    fieldsets = [
        ("基本信息", {"fields": ["kind", "name_zh", "name_en", "abbr", "category", "parent", "difficulty"]}),
        ("小白模式", {"fields": ["one_liner", "easy_text"]}),
        ("专业模式", {"fields": ["pro_text", "pitfalls"]}),
        ("可信度", {"fields": ["origin", "verify_status", "sources"]}),
    ]


@admin.register(m.Alias)
class AliasAdmin(admin.ModelAdmin):
    list_display = ["text", "kind", "content_type", "target"]
    list_filter = ["kind", "content_type"]
    search_fields = ["text", "norm"]


@admin.register(m.CompanyType)
class CompanyTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "order"]
    search_fields = ["name"]


@admin.register(m.Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ["name", "country", "verify_status", "last_checked_on"]
    list_filter = ["types", "country", "verify_status"]
    search_fields = ["name", "name_zh", "name_en", "aliases__text"]
    autocomplete_fields = ["types", "parent", "sources"]
    inlines = [AliasInline]


@admin.register(m.Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ["name", "owner"]
    search_fields = ["name", "owner__name", "aliases__text"]
    autocomplete_fields = ["owner", "sources"]
    inlines = [AliasInline]


@admin.register(m.Plant)
class PlantAdmin(admin.ModelAdmin):
    list_display = ["name", "company", "country", "city", "status", "status_on", "verify_status"]
    list_filter = ["status", "country", "verify_status"]
    search_fields = ["name", "company__name", "city"]
    autocomplete_fields = ["company", "sources"]


@admin.register(m.Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ["__str__", "base_entry", "product_type", "manufacturer", "lifecycle", "verify_status"]
    list_filter = ["product_type", "lifecycle", "verify_status", "base_entry__kind"]
    search_fields = ["code", "code_norm", "full_name", "aliases__text", "manufacturer__name", "brand__name"]
    autocomplete_fields = ["base_entry", "manufacturer", "brand", "applications", "processes", "sources"]
    inlines = [AliasInline, PropertyValueInline, GradePlantInline]


@admin.register(m.Standard)
class StandardAdmin(admin.ModelAdmin):
    list_display = ["__str__", "org", "title"]
    list_filter = ["org"]
    search_fields = ["code", "title"]
    autocomplete_fields = ["explain_entry"]


@admin.register(m.PropertyDefinition)
class PropertyDefinitionAdmin(admin.ModelAdmin):
    list_display = ["name_zh", "abbr", "group", "value_kind", "si_unit", "order"]
    list_filter = ["group", "value_kind"]
    search_fields = ["name_zh", "name_en", "abbr"]
    autocomplete_fields = ["entry"]


@admin.register(m.PropertyValue)
class PropertyValueAdmin(admin.ModelAdmin):
    list_display = ["__str__", "value_type", "standard", "conditions", "verify_status"]
    list_filter = ["prop__group", "value_type", "verify_status"]
    search_fields = ["grade__code", "entry__name_zh", "prop__name_zh", "value_text"]
    autocomplete_fields = ["grade", "entry", "prop", "standard", "source", "document"]


@admin.register(m.PriceSeries)
class PriceSeriesAdmin(admin.ModelAdmin):
    list_display = ["name", "price_type", "market", "currency", "unit", "tax", "is_active"]
    list_filter = ["price_type", "currency", "tax", "is_active"]
    search_fields = ["name", "spec_note", "market"]
    autocomplete_fields = ["entry", "grade", "source"]
    inlines = [PricePointInline]


@admin.register(m.LearningPath)
class LearningPathAdmin(admin.ModelAdmin):
    list_display = ["name", "order"]
    search_fields = ["name"]
    inlines = [PathItemInline]


@admin.register(m.EntryProgress)
class EntryProgressAdmin(admin.ModelAdmin):
    list_display = ["entry", "status", "starred", "last_viewed_at", "next_review_on"]
    list_filter = ["status", "starred"]
    search_fields = ["entry__name_zh", "entry__abbr"]


@admin.register(m.Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ["title", "tags", "updated_at"]
    search_fields = ["title", "body", "tags"]
    autocomplete_fields = ["entries", "grades"]


@admin.register(m.QARecord)
class QARecordAdmin(admin.ModelAdmin):
    list_display = ["__str__", "asker", "status", "asked_on"]
    list_filter = ["asker", "status"]
    search_fields = ["question", "answer", "context"]
    autocomplete_fields = ["entries", "grades", "sources"]
