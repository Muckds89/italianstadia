"""
Correct Wikipedia URLs for 8 Ekstraklasa stadiums whose original URLs
pointed to non-existent or wrong Wikipedia articles.

All matches are by Transfermarkt stadium URL (stable cross-environment
identifier — does not depend on PK which differs between local SQLite
and production PostgreSQL).

Corrections:
  Motor Lublin Arena   PKO_BP_Motor_Lublin_Arena        -> Arena_Lublin
  GOSiR Stadium        GOSiR_Stadium,_Gdynia             -> Stadion_Miejski_(Gdynia)
  Cracovia stadium     Marshal_Jozef_Pilsudski_Stadium   -> Jozef_Pilsudski_Cracovia_Stadium
  Lech Poznan stadium  Enea_Stadium                      -> Poznan_Stadium
  Zaglebie Lubin       KGHM_Zaglebie_Arena               -> Lubin_Stadium
  Piast Gliwice        Stadion_Miejski_w_Gliwicach        -> Piotr_Wieczorek_Municipal_Stadium
  Bruk-Bet Termalica   Bruk-Bet_Stadium,_Nieciecza        -> Stadion_Sportowy_Bruk-Bet_Termalica
  Korona Kielce        Suzuki_Arena_Kielce                -> Stadion_Miejski_(Kielce)
  Radomiak Radom       Bruk-Bet_Stadium_Radom             -> Stadion_im._Braci_Czachorow
"""

from django.db import migrations

# (transfermarkt_stadium_url, new_wikipedia_url)
FIXES = [
    (
        "https://www.transfermarkt.com/motor-lublin/stadion/verein/3527",
        "https://en.wikipedia.org/wiki/Arena_Lublin",
    ),
    (
        "https://www.transfermarkt.com/arka-gdynia/stadion/verein/6107",
        "https://en.wikipedia.org/wiki/Stadion_Miejski_(Gdynia)",
    ),
    (
        "https://www.transfermarkt.com/cracovia/stadion/verein/5689",
        "https://en.wikipedia.org/wiki/J%C3%B3zef_Pi%C5%82sudski_Cracovia_Stadium",
    ),
    (
        "https://www.transfermarkt.com/lech-posen/stadion/verein/238",
        "https://en.wikipedia.org/wiki/Pozna%C5%84_Stadium",
    ),
    (
        "https://www.transfermarkt.com/zaglebie-lubin/stadion/verein/168",
        "https://en.wikipedia.org/wiki/Lubin_Stadium",
    ),
    (
        "https://www.transfermarkt.com/piast-gliwice/stadion/verein/6112",
        "https://en.wikipedia.org/wiki/Piotr_Wieczorek_Municipal_Stadium",
    ),
    (
        "https://www.transfermarkt.com/bruk-bet-termalica-nieciecza/stadion/verein/15906",
        "https://en.wikipedia.org/wiki/Stadion_Sportowy_Bruk-Bet_Termalica",
    ),
    (
        "https://www.transfermarkt.com/korona-kielce/stadion/verein/6110",
        "https://en.wikipedia.org/wiki/Stadion_Miejski_(Kielce)",
    ),
    (
        "https://www.transfermarkt.com/radomiak-radom/stadion/verein/7154",
        "https://en.wikipedia.org/wiki/Stadion_im._Braci_Czachor%C3%B3w",
    ),
]


def fix_wiki_urls(apps, schema_editor):
    Stadium = apps.get_model("italiastadiaapp", "Stadium")
    for tm_url, new_wiki_url in FIXES:
        Stadium.objects.filter(transfermarkt_url=tm_url).update(wikipedia_url=new_wiki_url)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0032_fix_ekstraklasa_missing_coords"),
    ]

    operations = [
        migrations.RunPython(fix_wiki_urls, reverse_code=noop),
    ]
