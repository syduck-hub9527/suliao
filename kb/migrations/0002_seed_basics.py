"""
预置基础数据：公司类型、常用性能指标。

这些是录数据时下拉框里要选的东西，先放一批常用的。以后可以在后台随时增删改。
重复执行不会重复添加。
"""

from django.db import migrations

COMPANY_TYPES = [
    "生产商",
    "改性厂",
    "助剂厂商",
    "色母/母粒厂",
    "代理商",
    "经销商",
    "贸易商",
    "加工厂（注塑/挤出等）",
    "检测/认证机构",
]

# (中文名, 英文名, 缩写, 分组, 数据形式, 统一单位, 常见单位, 必须记录的条件)
PROPERTIES = [
    # 基础性能
    ("密度", "Density", "", "basic", "number", "g/cm³", "g/cm³, kg/m³", "测试标准（如 ISO 1183）"),
    ("吸水率", "Water Absorption", "", "basic", "number", "%", "%",
     "测试条件：23°C 浸水 24 小时，或 23°C/50%RH 下吸湿平衡，两者不能直接比"),
    # 加工性能
    ("熔体质量流动速率", "Melt Mass-Flow Rate", "MFR", "processing", "number", "g/10min", "g/10min",
     "必须记录温度和负荷，例：230°C/2.16kg"),
    ("熔体体积流动速率", "Melt Volume-Flow Rate", "MVR", "processing", "number", "cm³/10min", "cm³/10min",
     "必须记录温度和负荷，例：300°C/1.2kg"),
    ("成型收缩率", "Molding Shrinkage", "", "processing", "number", "%", "%",
     "注明平行/垂直于流动方向、试样厚度"),
    # 力学性能
    ("拉伸屈服强度", "Tensile Stress at Yield", "", "mechanical", "number", "MPa", "MPa, psi",
     "测试标准和拉伸速度"),
    ("拉伸断裂强度", "Tensile Stress at Break", "", "mechanical", "number", "MPa", "MPa, psi",
     "测试标准和拉伸速度（增强料通常只有断裂强度）"),
    ("断裂伸长率", "Elongation at Break", "", "mechanical", "number", "%", "%", "测试标准和拉伸速度"),
    ("拉伸模量", "Tensile Modulus", "", "mechanical", "number", "MPa", "MPa, GPa, psi", "测试标准"),
    ("弯曲强度", "Flexural Strength", "", "mechanical", "number", "MPa", "MPa, psi", "测试标准"),
    ("弯曲模量", "Flexural Modulus", "", "mechanical", "number", "MPa", "MPa, GPa, psi", "测试标准"),
    ("简支梁缺口冲击强度", "Charpy Notched Impact Strength", "", "mechanical", "number", "kJ/m²", "kJ/m²",
     "测试温度（23°C、-30°C 等），常用 ISO 179"),
    ("悬臂梁缺口冲击强度", "Izod Notched Impact Strength", "", "mechanical", "number", "kJ/m²", "kJ/m², J/m",
     "测试温度。ISO 180 用 kJ/m²，ASTM D256 用 J/m，两种单位不能直接换算"),
    ("洛氏硬度", "Rockwell Hardness", "", "mechanical", "text", "", "R、M 等标尺", "注明标尺，例：R120"),
    ("邵氏硬度", "Shore Hardness", "", "mechanical", "text", "", "A、D 标尺", "注明标尺，例：85A、60D"),
    # 热性能
    ("热变形温度", "Heat Deflection Temperature", "HDT", "thermal", "number", "°C", "°C, °F",
     "必须注明负荷：0.45 MPa 或 1.8 MPa，两者差别很大"),
    ("维卡软化温度", "Vicat Softening Temperature", "", "thermal", "number", "°C", "°C, °F",
     "注明负荷和升温速率，例：50N、50°C/h"),
    ("玻璃化转变温度", "Glass Transition Temperature", "Tg", "thermal", "number", "°C", "°C",
     "测试方法（DSC 或 DMA）"),
    ("熔点", "Melting Temperature", "Tm", "thermal", "number", "°C", "°C", "测试方法（通常 DSC）"),
    # 燃烧性能
    ("阻燃等级（UL 94）", "Flammability (UL 94)", "", "flame", "text", "", "HB、V-2、V-1、V-0、5VA 等",
     "必须注明试样厚度和颜色，例：V-0 @ 1.5 mm"),
    ("极限氧指数", "Limiting Oxygen Index", "LOI", "flame", "number", "%", "%", "测试标准（如 ISO 4589）"),
    # 电性能
    ("相比电痕化指数", "Comparative Tracking Index", "CTI", "electrical", "number", "V", "V",
     "测试标准（如 IEC 60112）"),
    ("体积电阻率", "Volume Resistivity", "", "electrical", "number", "Ω·cm", "Ω·cm, Ω·m", "测试标准"),
    ("介电强度", "Dielectric Strength", "", "electrical", "number", "kV/mm", "kV/mm", "试样厚度"),
    # 光学性能
    ("透光率", "Light Transmittance", "", "optical", "number", "%", "%", "试样厚度"),
]


def seed(apps, schema_editor):
    CompanyType = apps.get_model("kb", "CompanyType")
    PropertyDefinition = apps.get_model("kb", "PropertyDefinition")

    for i, name in enumerate(COMPANY_TYPES):
        CompanyType.objects.get_or_create(name=name, defaults={"order": i * 10})

    for i, (zh, en, abbr, group, kind, si, units, cond) in enumerate(PROPERTIES):
        PropertyDefinition.objects.get_or_create(
            name_zh=zh,
            defaults={
                "name_en": en, "abbr": abbr, "group": group, "value_kind": kind,
                "si_unit": si, "common_units": units, "required_conditions": cond, "order": i * 10,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("kb", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
