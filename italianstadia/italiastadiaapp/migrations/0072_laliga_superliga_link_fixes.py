"""
More live link fixes from the consolidated audit (after teaching it to query each
URL's own language wiki):
  Athletic Club (La Liga)   -> generic "Athletic club" page => Athletic Bilbao
  Poli Iași (Romania)       -> a disambiguation page        => FC Politehnica Iași (2010)
"""
from django.db import migrations

TEAM_LINKS = {
    "Athletic Club": "https://en.wikipedia.org/wiki/Athletic_Bilbao",
    "Poli Iași": "https://en.wikipedia.org/wiki/FC_Politehnica_Ia%C8%99i_(2010)",
}


def forwards(apps, schema_editor):
    Team = apps.get_model("italiastadiaapp", "Team")
    for name, url in TEAM_LINKS.items():
        Team.objects.filter(name=name).update(wikipedia_url=url)


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0071_live_wronglink_fixes"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
