"""为助剂牌号补充常见技术性能指标定义。"""
from django.db import migrations

PROPERTIES = [
    ("分子量", "Molecular Weight", "MW", "basic", "number", "g/mol", "g/mol", "注明来源和测定/计算方式", 100),
    ("熔融范围", "Melting Range", "", "thermal", "number", "°C", "°C", "注明测试方法（如 DSC）", 110),
    ("堆积密度", "Bulk Density", "", "basic", "number", "kg/m³", "kg/m³, g/cm³", "注明松装/振实及测试方法", 120),
    ("分解温度", "Decomposition Temperature", "", "thermal", "number", "°C", "°C", "注明测试方法、气氛和失重比例", 130),
    ("平均粒径", "Mean Particle Size", "D50", "other", "number", "μm", "μm", "注明 D50/D97 和测试方法", 140),
    ("比重", "Specific Gravity", "", "basic", "number", "", "", "注明测试温度", 150),
    ("纯度", "Purity", "", "other", "number", "%", "%", "注明测试方法和规格/典型值类型", 160),
    ("含水量", "Water Content", "", "other", "number", "%", "%", "注明测试方法", 170),
    ("色度", "Color", "", "optical", "number", "Pt/Co", "Pt/Co", "注明色度标度和测试方法", 180),
    ("溶解温度", "Dissolution Temperature", "", "processing", "number", "°C", "°C", "注明对应树脂体系和加工步骤", 190),
    ("筛余物", "Residue on Sieve", "", "other", "text", "", "", "注明筛网目数和测试方法", 200),
]

def seed(apps, schema_editor):
    PropertyDefinition = apps.get_model("kb", "PropertyDefinition")
    for zh, en, abbr, group, kind, si, units, conditions, order in PROPERTIES:
        PropertyDefinition.objects.get_or_create(
            name_zh=zh,
            defaults={
                "name_en": en, "abbr": abbr, "group": group, "value_kind": kind,
                "si_unit": si, "common_units": units, "required_conditions": conditions,
                "order": order,
            },
        )

class Migration(migrations.Migration):
    dependencies = [("kb", "0006_remove_prices")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
