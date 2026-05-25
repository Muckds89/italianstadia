from django.db import migrations


def seed_italian_leagues(apps, schema_editor):
    Country = apps.get_model("italiastadiaapp", "Country")
    League = apps.get_model("italiastadiaapp", "League")
    Team = apps.get_model("italiastadiaapp", "Team")

    italy, _ = Country.objects.get_or_create(name="Italy", defaults={"code": "IT"})

    serie_a, _ = League.objects.get_or_create(
        name="Serie A", country=italy, defaults={"division_level": 1}
    )
    serie_b, _ = League.objects.get_or_create(
        name="Serie B", country=italy, defaults={"division_level": 2}
    )
    serie_c, _ = League.objects.get_or_create(
        name="Serie C", country=italy, defaults={"division_level": 3}
    )

    tier_to_league = {1: serie_a, 2: serie_b, 3: serie_c}
    for team in Team.objects.filter(league__isnull=True):
        if team.tier in tier_to_league:
            team.league = tier_to_league[team.tier]
            team.save(update_fields=["league"])


def unseed_italian_leagues(apps, schema_editor):
    Country = apps.get_model("italiastadiaapp", "Country")
    Country.objects.filter(code="IT").delete()  # cascades to League; Team FK is SET_NULL


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0021_country_league_team_league"),
    ]

    operations = [
        migrations.RunPython(seed_italian_leagues, unseed_italian_leagues),
    ]
