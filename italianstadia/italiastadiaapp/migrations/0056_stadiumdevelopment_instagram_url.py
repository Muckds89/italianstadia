from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0055_fix_dasaki_achnas_country"),
    ]

    operations = [
        migrations.AddField(
            model_name="stadiumdevelopment",
            name="instagram_url",
            field=models.URLField(blank=True, max_length=500, null=True),
        ),
    ]
