"""
Four Belarusian Premier League teams were scraped with their Wikipedia link pointing at
the city / a disambiguation page instead of the football club:
  Dinamo Minsk -> disambig, Gomel -> city, Neman Grodno -> disambig, Vitebsk -> city.
Re-point each at the club article (FC <name>).
"""
from django.db import migrations

LINKS = {
    "Dinamo Minsk": "https://en.wikipedia.org/wiki/FC_Dinamo_Minsk",
    "Gomel": "https://en.wikipedia.org/wiki/FC_Gomel",
    "Neman Grodno": "https://en.wikipedia.org/wiki/FC_Neman_Grodno",
    "Vitebsk": "https://en.wikipedia.org/wiki/FC_Vitebsk",
}


def forwards(apps, schema_editor):
    Team = apps.get_model("italiastadiaapp", "Team")
    for name, url in LINKS.items():
        Team.objects.filter(name=name).update(wikipedia_url=url)


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0069_naftan_atlant_stadium"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
