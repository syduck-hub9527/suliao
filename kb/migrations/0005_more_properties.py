"""
补充一批性能指标。

国产通用料（T30S、SG-5 这类）的出厂指标里，常见的不是拉伸、冲击，而是等规指数、灰分、
黏数、K 值、表观密度这些“质量指标”。牌号库要照抄这些数字，先把指标定义加上。
重复执行不会重复添加；已经存在的指标不改动。
"""

from django.db import migrations

# (中文名, 英文名, 缩写, 分组, 数据形式, 统一单位, 常见单位, 必须记录的条件, 排序)
PROPERTIES = [
    ("拉伸屈服应变", "Tensile Strain at Yield", "", "mechanical", "number", "%", "%",
     "测试标准和拉伸速度；尼龙要分干态/调湿", 55),
    ("拉伸强度", "Tensile Strength", "", "mechanical", "number", "MPa", "MPa, psi, kg/cm²",
     "资料只写“拉伸强度”、没说是屈服还是断裂时用这一项（常见于老式或亚洲厂家的 TDS）", 58),
    ("撕裂强度", "Tear Strength", "", "mechanical", "number", "kN/m", "kN/m, N/mm, lb/in",
     "测试标准和试样形状（如 ISO 34-1、ASTM D624 Die C）", 200),
    ("表观密度", "Apparent (Bulk) Density", "", "basic", "number", "g/mL", "g/mL, g/cm³, kg/m³",
     "粉料、粒料堆积起来的密度，不是材料本身的密度", 15),
    ("等规指数", "Isotactic Index", "", "other", "number", "%", "%",
     "聚丙烯的规整度指标，常用正庚烷抽提法", 10),
    ("灰分", "Ash Content", "", "other", "number", "%", "%", "灼烧温度和方法", 20),
    ("挥发物含量", "Volatile Matter", "", "other", "number", "%", "%",
     "PVC 等粉料常用，一般含水分", 30),
    ("黏数", "Viscosity Number", "VN", "other", "number", "mL/g", "mL/g",
     "溶剂和浓度（PVC 按 GB/T 3401 / ISO 1628-2）", 40),
    ("K 值", "K Value", "", "other", "number", "", "",
     "PVC 分子量的习惯表示法，和黏数、聚合度一一对应", 50),
    ("平均聚合度", "Average Degree of Polymerization", "", "other", "number", "", "",
     "PVC 常用，由黏数换算", 60),
    ("特性黏度", "Intrinsic Viscosity", "IV", "other", "number", "dL/g", "dL/g",
     "PET 常用，注明溶剂（如苯酚/四氯乙烷）和温度", 70),
    ("雾度", "Haze", "", "optical", "number", "%", "%", "试样厚度（薄膜尤其要写）", 250),
]


def seed(apps, schema_editor):
    PropertyDefinition = apps.get_model("kb", "PropertyDefinition")
    for zh, en, abbr, group, kind, si, units, cond, order in PROPERTIES:
        PropertyDefinition.objects.get_or_create(
            name_zh=zh,
            defaults={
                "name_en": en, "abbr": abbr, "group": group, "value_kind": kind,
                "si_unit": si, "common_units": units, "required_conditions": cond, "order": order,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("kb", "0004_grade_library"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
