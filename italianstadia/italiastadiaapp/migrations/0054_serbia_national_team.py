"""
Add the Serbia national football team (mirrors England/France: dedicated
"National Football Team" league, Belgrade as city, Rajko Mitić as home ground,
crest from Wikipedia) and link it as the future tenant of the National Stadium
(Serbia) under-development project. Runs after 0053 (which seeds that dev row).
Idempotent. Historical models lack custom save(), so the Team slug is set here.
"""
from django.db import migrations
from django.utils.text import slugify


def forwards(apps, schema_editor):
    League = apps.get_model("italiastadiaapp", "League")
    City = apps.get_model("italiastadiaapp", "City")
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    Team = apps.get_model("italiastadiaapp", "Team")
    Country = apps.get_model("italiastadiaapp", "Country")
    StadiumDevelopment = apps.get_model("italiastadiaapp", "StadiumDevelopment")

    rs = Country.objects.filter(name="Serbia").first()
    if not rs:
        return  # no Serbia country row → nothing to attach to

    league, _ = League.objects.get_or_create(
        name="National Football Team", country=rs,
        defaults={"division_level": 0},
    )
    city = City.objects.filter(name="Belgrade", country="Serbia").first()
    home = Stadium.objects.filter(name="Rajko Mitić").first()
    if not home:
        return  # Team.stadium is NOT NULL; skip if Serbia data isn't present yet
                # (e.g. fresh test DB). Production has Rajko Mitić from the scrape.

    team = Team.objects.filter(name="Serbia", is_national=True).first()
    if not team:
        slug = "serbia"
        n = 2
        while Team.objects.filter(slug=slug).exclude(name="Serbia").exists():
            slug = f"serbia-{n}"
            n += 1
        team = Team.objects.create(
            name="Serbia",
            slug=slug,
            is_national=True,
            league=league,
            city=city,
            stadium=home,
            image_url="https://upload.wikimedia.org/wikipedia/en/thumb/e/eb/"
                      "Football_Association_of_Serbia_logo.svg/"
                      "250px-Football_Association_of_Serbia_logo.svg.png",
            wikipedia_url="https://en.wikipedia.org/wiki/Serbia_national_football_team",
        )

    dev = StadiumDevelopment.objects.filter(name="National Stadium (Serbia)").first()
    if dev:
        dev.future_tenants.set([team])


def backwards(apps, schema_editor):
    Team = apps.get_model("italiastadiaapp", "Team")
    Team.objects.filter(name="Serbia", is_national=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0053_seed_dev_candidates"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
