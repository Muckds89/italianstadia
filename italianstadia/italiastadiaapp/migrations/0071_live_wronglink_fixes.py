"""
Live-data link fixes found by the consolidated audit (team links pointing at a
disambiguation / village page, and one stadium pointing at a club page):
  Breiðablik (Iceland)            team -> disambig   => Breiðablik (men's football)
  Stal Rzeszów (Poland, I Liga)   team -> disambig   => Stal Rzeszów (football)
  CSF Spartanii Sportul Selemet   team -> Selemet village => CSF Spartanii Sportul
  Stadiumi Flamurtari (Albania)   stadium -> Flamurtari FC (a club) => Flamurtari Stadium
"""
from django.db import migrations

TEAM_LINKS = {
    "Breiðablik": "https://en.wikipedia.org/wiki/Brei%C3%B0ablik_(men%27s_football)",
    "Stal Rzeszów": "https://en.wikipedia.org/wiki/Stal_Rzesz%C3%B3w_(football)",
    "CSF Spartanii Sportul Selemet": "https://en.wikipedia.org/wiki/CSF_Spartanii_Sportul",
}
STADIUM_LINKS = {
    "Stadiumi Flamurtari": "https://en.wikipedia.org/wiki/Flamurtari_Stadium",
}


def forwards(apps, schema_editor):
    Team = apps.get_model("italiastadiaapp", "Team")
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    for name, url in TEAM_LINKS.items():
        Team.objects.filter(name=name).update(wikipedia_url=url)
    for name, url in STADIUM_LINKS.items():
        Stadium.objects.filter(name=name).update(wikipedia_url=url)


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0070_belarus_team_wiki_links"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
