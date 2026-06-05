"""
Remove clubs relegated after the 2024/25 season and their now-orphaned stadiums.

Premier League: Ipswich Town, Leicester City, Southampton
Bundesliga: Holstein Kiel, VfL Bochum

Identified by Transfermarkt URL (stable across environments — not by PK which
differs between local SQLite and production PostgreSQL).
"""

from django.db import migrations

RELEGATED_TEAM_TM_URLS = [
    # Premier League 2024/25 → Championship
    "https://www.transfermarkt.com/ipswich-town/startseite/verein/677",
    "https://www.transfermarkt.com/leicester-city/startseite/verein/1003",
    "https://www.transfermarkt.com/southampton/startseite/verein/180",
    # Bundesliga 2024/25 → 2. Bundesliga
    "https://www.transfermarkt.com/holstein-kiel/startseite/verein/273",
    "https://www.transfermarkt.com/vfl-bochum/startseite/verein/80",
]


def remove_relegated(apps, schema_editor):
    Team = apps.get_model("italiastadiaapp", "Team")
    Stadium = apps.get_model("italiastadiaapp", "Stadium")

    for tm_url in RELEGATED_TEAM_TM_URLS:
        try:
            team = Team.objects.get(transfermarkt_url=tm_url)
            stadium = team.stadium
            team.delete()
            # Delete stadium only if it is now orphaned
            if stadium and not Team.objects.filter(stadium=stadium).exists():
                stadium.delete()
        except Team.DoesNotExist:
            pass  # Already removed — idempotent


def noop(apps, schema_editor):
    # No meaningful reverse: we don't want to re-insert scraped data via migration
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0030_seed_european_countries"),
    ]

    operations = [
        migrations.RunPython(remove_relegated, reverse_code=noop),
    ]
