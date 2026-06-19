"""
Fix the country of Dasaki Achnas (home of Ethnikos Achnas) — a bad scrape tagged
it "Akrotiri and Dhekelia" (the British base areas), which surfaced as a bogus
country in the map/export filters. It belongs to Cyprus.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    City = apps.get_model("italiastadiaapp", "City")
    City.objects.filter(country="Akrotiri and Dhekelia").update(country="Cyprus")


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0054_serbia_national_team"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
