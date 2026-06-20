"""
Euro 2036 — competing multi-country BIDS. Creates the 5 missing bid venues and tags
every bid venue's `tournaments` JSON with a 2036 entry carrying a `bid` label:
  {"tournament": "UEFA Euro 2036", "year": 2036, "status": "CANDIDATE", "bid": "<name>"}

Bids (all unofficial/proposed as of 2026): Poland (solo), Nordic (Denmark/Sweden/
Norway/Finland — no Iceland), Balkan (Croatia/Serbia/Bosnia/North Macedonia). No schema
change — `bid` is a JSON key like `status`. Idempotent.
"""
from django.db import migrations
from django.utils.text import slugify

TOURNAMENT = "UEFA Euro 2036"
YEAR = 2036

# venues to create: name -> (city, country, lat, lon, wiki)
NEW_VENUES = {
    "Stadion Śląski": ("Chorzów", "Poland", 50.288333, 18.973056,
                       "https://en.wikipedia.org/wiki/Silesian_Stadium"),
    "Tarczyński Arena": ("Wrocław", "Poland", 51.141111, 16.943889,
                         "https://en.wikipedia.org/wiki/Stadion_Wroc%C5%82aw"),
    "Stadion Miejski (Kraków)": ("Kraków", "Poland", 50.064722, 19.908889,
                                 "https://en.wikipedia.org/wiki/Stadion_Miejski_(Krak%C3%B3w)"),
    "Ullevaal Stadion": ("Oslo", "Norway", 59.948889, 10.734167,
                         "https://en.wikipedia.org/wiki/Ullevaal_Stadion"),
    "Bilino Polje": ("Zenica", "Bosnia and Herzegovina", 44.201667, 17.900556,
                     "https://en.wikipedia.org/wiki/Bilino_Polje_Stadium"),
}

# bid -> operational Stadium names (exact DB names)
BID_STADIUMS = {
    "Poland": ["PGE Narodowy", "Stadion Śląski", "Enea Poznań",
               "Polsat Plus Arena Gdańsk", "Tarczyński Arena", "Stadion Miejski (Kraków)"],
    "Nordic": ["Parken - connected by 3", "Strawberry Arena", "Ullevaal Stadion", "Bolt Arena"],
    "Balkan": ["Maksimir", "Poljud", "Rajko Mitić", "Koševo City Stadium",
               "Bilino Polje", "Nacionalna Arena Tose Proeski"],
}
# bid -> StadiumDevelopment names (future grounds proposed in a bid)
BID_DEVELOPMENTS = {
    "Balkan": ["National Stadium (Serbia)"],
}


def _uslug(Model, name):
    base = slugify(name) or "stadium"
    slug = base
    n = 2
    while Model.objects.filter(slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def _tag(obj, bid):
    tours = list(obj.tournaments or [])
    if any(t.get("tournament") == TOURNAMENT for t in tours):
        return False
    tours.append({"tournament": TOURNAMENT, "year": YEAR,
                  "status": "CANDIDATE", "bid": bid})
    obj.tournaments = tours
    return True


def forwards(apps, schema_editor):
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    City = apps.get_model("italiastadiaapp", "City")
    Development = apps.get_model("italiastadiaapp", "StadiumDevelopment")

    # 1. create missing venues
    for name, (city_name, country, lat, lon, wiki) in NEW_VENUES.items():
        if Stadium.objects.filter(name=name).exists():
            continue
        city, _ = City.objects.get_or_create(name=city_name, country=country)
        Stadium.objects.create(
            name=name, slug=_uslug(Stadium, name), city=city,
            latitude=lat, longitude=lon, ownership="PUBLIC", wikipedia_url=wiki,
        )

    # 2. tag operational bid venues
    for bid, names in BID_STADIUMS.items():
        for name in names:
            for s in Stadium.objects.filter(name=name):
                if _tag(s, bid):
                    s.save(update_fields=["tournaments"])

    # 3. tag under-development bid venues
    for bid, names in BID_DEVELOPMENTS.items():
        for name in names:
            for d in Development.objects.filter(name=name):
                if _tag(d, bid):
                    d.save(update_fields=["tournaments"])


def backwards(apps, schema_editor):
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    Development = apps.get_model("italiastadiaapp", "StadiumDevelopment")
    for Model in (Stadium, Development):
        for obj in Model.objects.exclude(tournaments=[]):
            tours = [t for t in (obj.tournaments or []) if t.get("tournament") != TOURNAMENT]
            if len(tours) != len(obj.tournaments or []):
                obj.tournaments = tours
                obj.save(update_fields=["tournaments"])


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0061_clear_famalicao_casapia_tm"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
