import pytest

from italiastadiaapp.models import City, Country, League, Stadium, Team, StadiumDevelopment


@pytest.mark.django_db
def test_stadium_string_representation():

    city = City.objects.create(
        name="Milan",
        population=1300000,
        country="Italy",
    )

    stadium = Stadium.objects.create(
        name="San Siro",
        city=city,
        latitude=45.4781,
        longitude=9.1240,
        ownership="PUBLIC",
    )

    assert str(stadium) == "San Siro"

@pytest.mark.django_db
def test_team_string_representation_team():

    city = City.objects.create(
        name="Milan",
        population=1300000,
        country="Italy",
    )
    stadium = Stadium.objects.create(
        name="San Siro",
        city=city,
        latitude=45.4781,
        longitude=9.1240,
        ownership="PUBLIC",
    )
    
    team = Team.objects.create(
        name="AC Milan",
        city=city,
        stadium=stadium,
        tier=1,
        )
    
    assert str(team) == "AC Milan"

@pytest.mark.django_db
def test_stadium_development_string_representation():
    stadium_development = StadiumDevelopment.objects.create(
        name="Test New Stadium",
        project_type="NEW",
        status="PLANNING",
        future_capacity=30000,
        estimated_opening=2028,
        latitude=45.0,
        longitude=9.0,
    )
    assert str(stadium_development) == "Test New Stadium"


@pytest.mark.django_db
def test_country_and_league_str():
    # Use get_or_create — data migration may have already seeded Italy
    country, _ = Country.objects.get_or_create(name="Italy", defaults={"code": "IT"})
    assert str(country) == "Italy"

    league, _ = League.objects.get_or_create(
        name="Serie A", country=country, defaults={"division_level": 1}
    )
    assert "Serie A" in str(league)
    assert "Italy" in str(league)


@pytest.mark.django_db
def test_country_uefa_rank_field():
    country, _ = Country.objects.get_or_create(name="England", defaults={"code": "GB"})
    country.uefa_rank = 1
    country.save()
    country.refresh_from_db()
    assert country.uefa_rank == 1

    # Null is valid (countries not yet ranked in our DB)
    country.uefa_rank = None
    country.save()
    country.refresh_from_db()
    assert country.uefa_rank is None


@pytest.mark.django_db
def test_all_country_codes_fit_max_length():
    """
    Guard against the SQLite-silent / PostgreSQL-fatal max_length overflow.

    SQLite accepts CharField values longer than max_length without complaint.
    PostgreSQL raises DataError and breaks the Render deploy.  This test runs
    against the test DB (SQLite locally) but explicitly checks the Python-level
    constraint so the CI catches the issue before it ever reaches Render.

    What it validates:
    - Every code value seeded by migrations satisfies len(code) <= max_length.
    - Any future migration that inserts an over-length code will fail this test.
    """
    import django.apps
    from django.db import models as db_models

    # Collect every CharField(max_length=N) across all models in this app
    app_config = django.apps.apps.get_app_config("italiastadiaapp")
    violations = []

    for model in app_config.get_models():
        for field in model._meta.get_fields():
            if not isinstance(field, db_models.CharField):
                continue
            max_len = getattr(field, "max_length", None)
            if not max_len:
                continue
            for obj in model.objects.all():
                value = getattr(obj, field.name, None)
                if value and len(value) > max_len:
                    violations.append(
                        f"{model.__name__}.{field.name}: "
                        f"value {value!r} ({len(value)} chars) "
                        f"exceeds max_length={max_len}"
                    )

    assert not violations, (
        "CharField max_length violations found — PostgreSQL would reject these:\n"
        + "\n".join(violations)
    )


@pytest.mark.django_db
def test_country_code_values():
    """
    Explicit check: every Country.code must be exactly 2 characters.
    Catches bad seed data (e.g. 'GB-SCT') before Render deploy fails.
    """
    from italiastadiaapp.models import Country

    bad = [
        (c.name, c.code)
        for c in Country.objects.all()
        if len(c.code) != 2
    ]
    assert not bad, (
        "Country codes must be exactly 2 chars (ISO 3166-1 alpha-2). "
        "Bad entries: " + str(bad)
    )


@pytest.mark.django_db
def test_league_ordering():
    # Use get_or_create — data migration may have already seeded these rows
    country, _ = Country.objects.get_or_create(name="Italy", defaults={"code": "IT"})
    League.objects.get_or_create(name="Serie C", country=country, defaults={"division_level": 3})
    League.objects.get_or_create(name="Serie A", country=country, defaults={"division_level": 1})
    League.objects.get_or_create(name="Serie B", country=country, defaults={"division_level": 2})

    names = list(League.objects.filter(country=country).values_list("name", flat=True))
    assert names == ["Serie A", "Serie B", "Serie C"]