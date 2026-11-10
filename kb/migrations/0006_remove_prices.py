"""
删掉价格功能的两张表。

直接整表删除，不逐个字段改：这样无论服务器上之前装没装过 v0.4 的价格版本，都能顺利升级。
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("kb", "0005_more_properties"),
    ]

    operations = [
        migrations.DeleteModel(name="PricePoint"),
        migrations.DeleteModel(name="PriceSeries"),
    ]
