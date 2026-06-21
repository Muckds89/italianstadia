"""
Backfill Country.population for the stadium-density insight page. Figures are approximate
mid-2020s national populations (UN / national statistics; England/Scotland/Wales/N. Ireland
split from the UK total). Used only to compute stadiums-per-million, so round numbers are fine.
"""
from django.db import migrations

POPULATION = {
    "Albania": 2_740_000, "Andorra": 80_000, "Armenia": 2_780_000, "Austria": 9_100_000,
    "Azerbaijan": 10_140_000, "Belarus": 9_200_000, "Belgium": 11_700_000,
    "Bosnia and Herzegovina": 3_200_000, "Bulgaria": 6_400_000, "Croatia": 3_850_000,
    "Cyprus": 1_260_000, "Czechia": 10_900_000, "Denmark": 5_960_000, "England": 56_500_000,
    "Estonia": 1_370_000, "Finland": 5_550_000, "France": 68_200_000, "Georgia": 3_700_000,
    "Germany": 84_500_000, "Greece": 10_400_000, "Hungary": 9_600_000, "Iceland": 390_000,
    "Ireland": 5_150_000, "Italy": 58_900_000, "Kosovo": 1_760_000, "Latvia": 1_880_000,
    "Liechtenstein": 40_000, "Lithuania": 2_860_000, "Luxembourg": 660_000, "Malta": 540_000,
    "Moldova": 2_510_000, "Monaco": 38_000, "Montenegro": 620_000, "Netherlands": 17_800_000,
    "North Macedonia": 1_830_000, "Northern Ireland": 1_910_000, "Norway": 5_500_000,
    "Poland": 37_700_000, "Portugal": 10_300_000, "Romania": 19_000_000, "Russia": 143_800_000,
    "San Marino": 34_000, "Scotland": 5_450_000, "Serbia": 6_600_000, "Slovakia": 5_430_000,
    "Slovenia": 2_120_000, "Spain": 48_400_000, "Sweden": 10_500_000, "Switzerland": 8_850_000,
    "Turkey": 85_300_000, "Ukraine": 38_000_000, "Wales": 3_130_000,
}


def forwards(apps, schema_editor):
    Country = apps.get_model("italiastadiaapp", "Country")
    for name, pop in POPULATION.items():
        Country.objects.filter(name=name).update(population=pop)


def backwards(apps, schema_editor):
    Country = apps.get_model("italiastadiaapp", "Country")
    Country.objects.update(population=None)


class Migration(migrations.Migration):

    dependencies = [
        ("italiastadiaapp", "0074_country_population_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
