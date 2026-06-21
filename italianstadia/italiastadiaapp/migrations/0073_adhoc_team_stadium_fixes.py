"""
Ad-hoc, owner-verified corrections (each stadium is locked=True so the weekly scraper
won't revert these manual fixes):

- Vestri Ísafjörður (Iceland): badge missing -> Wikipedia crest; the stadium's
  Transfermarkt link pointed at verein 18940 = "R Knokke FC" (Belgium!) -> repoint team
  and stadium to Vestri's verein 29224.
- Stal Mielec (Poland): Grzegorz Lato Stadium had no Wikipedia link -> Stadion Stali Mielec.
- Moldova: FC Dacia Buiucani and FC Politehnica UTM Chișinău wrongly SHARED one stadium row
  ("Tatnam Ground"). Split them: Dacia -> new "Nisporeni Central Stadium" (its real ground);
  the shared row stays with Politehnica and is corrected to its real ground (Cricova synthetic
  pitch, TM verein 90107), clearing the wrong Republican Stadium wiki link.
- Sepsi OSK (Romania): Sepsi Duna Arena had no coordinates -> exact WGS84 45.883611, 25.806111.
- Kolkheti-1913 Poti (Georgia): "Poti Central Stadium" -> Fazisi Stadium (wiki + coords).
"""
from django.db import migrations
from django.utils.text import slugify

VESTRI_LOGO = "https://upload.wikimedia.org/wikipedia/en/3/3b/Vestri_%28men%27s_football%29_logo.png"
VESTRI_TM = "https://www.transfermarkt.com/vestri-isafjordur/startseite/verein/29224"
VESTRI_STAD_TM = "https://www.transfermarkt.com/vestri-isafjordur/stadion/verein/29224"

NISPORENI_WIKI = "https://en.wikipedia.org/wiki/Nisporeni_Central_Stadium"
NISPORENI_TM = "https://www.transfermarkt.com/dacia-buiucani/stadion/verein/39003"
NISPORENI_IMG = "https://upload.wikimedia.org/wikipedia/commons/c/c1/Nisporeni_stadium_3.jpg"
NISPORENI_CREDIT = "Andrei Anghelov / Wikimedia Commons / CC BY 4.0"

POLI_TM = "https://www.transfermarkt.com/cstc-saksan/stadion/verein/90107"
FAZISI_WIKI = "https://en.wikipedia.org/wiki/Fazisi_Stadium"


def _uslug(Stadium, name, pk=None):
    base = slugify(name) or "stadium"
    slug, n = base, 2
    while Stadium.objects.filter(slug=slug).exclude(pk=pk).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def forwards(apps, schema_editor):
    Team = apps.get_model("italiastadiaapp", "Team")
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    City = apps.get_model("italiastadiaapp", "City")

    # --- Vestri ---
    for t in Team.objects.filter(name="Vestri Ísafjörður"):
        t.image_url = VESTRI_LOGO
        t.image_credit = "Vestri (men's football) crest (fair use)"
        t.transfermarkt_url = VESTRI_TM
        t.save(update_fields=["image_url", "image_credit", "transfermarkt_url"])
        if t.stadium:
            s = t.stadium
            s.transfermarkt_url = VESTRI_STAD_TM
            s.locked = True
            s.save(update_fields=["transfermarkt_url", "locked"])

    # --- Stal Mielec stadium ---
    for s in Stadium.objects.filter(name="Grzegorz Lato Stadium"):
        s.wikipedia_url = "https://en.wikipedia.org/wiki/Stadion_Stali_Mielec"
        s.locked = True
        s.save(update_fields=["wikipedia_url", "locked"])

    # --- Sepsi OSK coordinates ---
    for s in Stadium.objects.filter(name="Sepsi Duna Arena"):
        s.latitude = 45.883611
        s.longitude = 25.806111
        s.locked = True
        s.save(update_fields=["latitude", "longitude", "locked"])

    # --- Kolkheti: Poti Central Stadium -> Fazisi Stadium ---
    for s in Stadium.objects.filter(name="Poti Central Stadium"):
        s.name = "Fazisi Stadium"
        s.slug = _uslug(Stadium, "Fazisi Stadium", s.pk)
        s.wikipedia_url = FAZISI_WIKI
        s.latitude = 42.142500
        s.longitude = 41.665556
        s.locked = True
        s.save(update_fields=["name", "slug", "wikipedia_url", "latitude", "longitude", "locked"])

    # --- Moldova: split the shared "Tatnam Ground" row ---
    dacia = Team.objects.filter(name="FC Dacia Buiucani").first()
    if dacia and dacia.stadium:
        shared = dacia.stadium  # the row also used by Politehnica UTM
        city, _ = City.objects.get_or_create(name="Nisporeni", country="Moldova")
        nisporeni = Stadium.objects.create(
            name="Nisporeni Central Stadium",
            slug=_uslug(Stadium, "Nisporeni Central Stadium"),
            city=city,
            latitude=47.076444,
            longitude=28.179333,
            wikipedia_url=NISPORENI_WIKI,
            transfermarkt_url=NISPORENI_TM,
            image_url=NISPORENI_IMG,
            image_credit=NISPORENI_CREDIT,
            locked=True,
        )
        dacia.stadium = nisporeni
        dacia.save(update_fields=["stadium"])

        # The shared row now belongs only to Politehnica UTM (Cricova synthetic pitch).
        if shared.name == "Tatnam Ground":
            shared.name = "Cricova teren sintetic"
            shared.slug = _uslug(Stadium, "Cricova teren sintetic", shared.pk)
            shared.wikipedia_url = ""          # the old Republican Stadium link was wrong
            shared.transfermarkt_url = POLI_TM
            shared.surface = "ARTIFICIAL"
            shared.locked = True
            shared.save(update_fields=["name", "slug", "wikipedia_url",
                                       "transfermarkt_url", "surface", "locked"])


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0072_laliga_superliga_link_fixes"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
