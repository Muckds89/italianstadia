"""
Add 9 more national teams + their designated national stadiums (mirrors the
England/France/Serbia pattern: dedicated "National Football Team" league per country,
city, home stadium, flagcdn flag). Creates the missing Northern Ireland country and
the 7 stadiums not yet in the DB; reuses existing Arena Națională / Arena Kombëtare.

Coordinates from Wikipedia/Wikidata (Vazgen Sargsyan via OSM — no wiki geo).
Idempotent: get_or_create throughout. Team.stadium is NOT NULL so each stadium is
ensured first. Historical models lack custom save() → slugs generated here.
"""
from django.db import migrations
from django.utils.text import slugify


# country, ISO code (for new countries), flagcdn code, city, stadium, coords, wikis
NATIONS = [
    {"country": "Hungary", "flag": "hu", "city": "Budapest",
     "stadium": "Puskás Aréna", "lat": 47.503000, "lon": 19.097900,
     "wiki_s": "https://en.wikipedia.org/wiki/Pusk%C3%A1s_Ar%C3%A9na",
     "wiki_t": "https://en.wikipedia.org/wiki/Hungary_national_football_team"},
    {"country": "Northern Ireland", "new_code": "NI", "flag": "gb-nir", "city": "Belfast",
     "stadium": "Windsor Park", "lat": 54.582500, "lon": -5.955278,
     "wiki_s": "https://en.wikipedia.org/wiki/Windsor_Park",
     "wiki_t": "https://en.wikipedia.org/wiki/Northern_Ireland_national_football_team"},
    {"country": "Belgium", "flag": "be", "city": "Brussels",
     "stadium": "King Baudouin Stadium", "lat": 50.895833, "lon": 4.334167,
     "wiki_s": "https://en.wikipedia.org/wiki/King_Baudouin_Stadium",
     "wiki_t": "https://en.wikipedia.org/wiki/Belgium_national_football_team"},
    {"country": "Poland", "flag": "pl", "city": "Warsaw",
     "stadium": "PGE Narodowy", "lat": 52.239444, "lon": 21.045556,
     "wiki_s": "https://en.wikipedia.org/wiki/PGE_Narodowy",
     "wiki_t": "https://en.wikipedia.org/wiki/Poland_national_football_team"},
    {"country": "Romania", "flag": "ro", "city": "Bucharest",
     "stadium": "Arena Națională", "existing": True,
     "wiki_t": "https://en.wikipedia.org/wiki/Romania_national_football_team"},
    {"country": "Albania", "flag": "al", "city": "Tirana",
     "stadium": "Arena Kombëtare", "existing": True,
     "wiki_t": "https://en.wikipedia.org/wiki/Albania_national_football_team"},
    {"country": "Armenia", "flag": "am", "city": "Yerevan",
     "stadium": "Vazgen Sargsyan Republican Stadium", "lat": 40.174722, "lon": 44.523611,
     "wiki_s": "https://en.wikipedia.org/wiki/Republican_Stadium_(Yerevan)",
     "wiki_t": "https://en.wikipedia.org/wiki/Armenia_national_football_team"},
    {"country": "Georgia", "flag": "ge", "city": "Tbilisi",
     "stadium": "Boris Paichadze Dinamo Arena", "lat": 41.723056, "lon": 44.789722,
     "wiki_s": "https://en.wikipedia.org/wiki/Boris_Paichadze_Dinamo_Arena",
     "wiki_t": "https://en.wikipedia.org/wiki/Georgia_national_football_team"},
    {"country": "Azerbaijan", "flag": "az", "city": "Baku",
     "stadium": "Baku Olympic Stadium", "lat": 40.429800, "lon": 49.919800,
     "wiki_s": "https://en.wikipedia.org/wiki/Baku_Olympic_Stadium",
     "wiki_t": "https://en.wikipedia.org/wiki/Azerbaijan_national_football_team"},
]


def _uslug(Model, base, name):
    slug = base or slugify(name) or "x"
    n = 2
    while Model.objects.filter(slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def forwards(apps, schema_editor):
    Country = apps.get_model("italiastadiaapp", "Country")
    League = apps.get_model("italiastadiaapp", "League")
    City = apps.get_model("italiastadiaapp", "City")
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    Team = apps.get_model("italiastadiaapp", "Team")

    for n in NATIONS:
        country = Country.objects.filter(name=n["country"]).first()
        if not country and n.get("new_code"):
            country = Country.objects.create(name=n["country"], code=n["new_code"])
        if not country:
            continue

        city, _ = City.objects.get_or_create(
            name=n["city"], country=n["country"])

        if n.get("existing"):
            stadium = Stadium.objects.filter(name=n["stadium"]).first()
            if not stadium:
                continue
        else:
            stadium = Stadium.objects.filter(name=n["stadium"]).first()
            if not stadium:
                stadium = Stadium.objects.create(
                    name=n["stadium"],
                    slug=_uslug(Stadium, slugify(n["stadium"]), n["stadium"]),
                    city=city,
                    latitude=n["lat"], longitude=n["lon"],
                    ownership="PUBLIC",
                    wikipedia_url=n.get("wiki_s", ""),
                )

        league, _ = League.objects.get_or_create(
            name="National Football Team", country=country,
            defaults={"division_level": 0})

        if Team.objects.filter(name=n["country"], is_national=True).exists():
            continue
        Team.objects.create(
            name=n["country"],
            slug=_uslug(Team, slugify(n["country"]), n["country"]),
            is_national=True,
            league=league,
            city=city,
            stadium=stadium,
            image_url=f"https://flagcdn.com/w160/{n['flag']}.png",
            wikipedia_url=n.get("wiki_t", ""),
        )


def backwards(apps, schema_editor):
    Team = apps.get_model("italiastadiaapp", "Team")
    Team.objects.filter(name__in=[n["country"] for n in NATIONS], is_national=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0059_clear_wrong_team_tm_links"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
