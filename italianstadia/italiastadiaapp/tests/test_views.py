import pytest
from django.urls import reverse

from italiastadiaapp.models import City, Country, League, Stadium, StadiumDevelopment, Team


@pytest.mark.django_db
def test_stadium_development_detail_loads(client):
    dev = StadiumDevelopment.objects.create(
        name="New Stadio",
        project_type="NEW",
        status="PLANNING",
        future_capacity=35000,
        estimated_opening=2027,
        latitude=45.0,
        longitude=9.0,
    )
    response = client.get(
        reverse("italiastadiaapp:stadium_development_detail", args=[dev.slug])
    )
    assert response.status_code == 200
    assert b"New Stadio" in response.content


@pytest.mark.django_db
def test_stadium_development_detail_redirects_pk_to_slug(client):
    dev = StadiumDevelopment.objects.create(
        name="Redirect Stadio",
        project_type="NEW",
        status="PLANNING",
        latitude=45.0,
        longitude=9.0,
    )
    response = client.get(
        reverse("italiastadiaapp:stadium_development_detail_by_id", args=[dev.pk])
    )
    assert response.status_code == 301
    assert response.url == reverse(
        "italiastadiaapp:stadium_development_detail", args=[dev.slug]
    )


@pytest.mark.django_db
def test_stadium_development_detail_404(client):
    response = client.get(
        reverse("italiastadiaapp:stadium_development_detail", args=["no-such-slug"])
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_homepage_loads(client):
    response = client.get(reverse("italiastadiaapp:home"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_stadium_detail_page_loads(client):
    city = City.objects.create(name="Rome", population=2800000, country="Italy")
    stadium = Stadium.objects.create(
        name="Olimpico", city=city,
        latitude=41.9339, longitude=12.4547, ownership="PUBLIC",
    )
    response = client.get(reverse("italiastadiaapp:stadium_detail", args=[stadium.slug]))
    assert response.status_code == 200


@pytest.mark.django_db
def test_stadium_detail_numeric_redirect(client):
    city = City.objects.create(name="Rome", population=2800000, country="Italy")
    stadium = Stadium.objects.create(
        name="Olimpico Redirect", city=city,
        latitude=41.9339, longitude=12.4547, ownership="PUBLIC",
    )
    response = client.get(reverse("italiastadiaapp:stadium_detail_by_id", args=[stadium.id]))
    assert response.status_code == 301
    assert stadium.slug in response["Location"]


@pytest.mark.django_db
def test_country_stats_page_loads(client):
    city = City.objects.create(name="Rome", population=2800000, country="Italy")
    Stadium.objects.create(
        name="Olimpico Stats", city=city,
        latitude=41.9339, longitude=12.4547, ownership="PUBLIC", capacity=70000,
    )
    response = client.get(reverse("italiastadiaapp:country_stats", args=["Italy"]))
    assert response.status_code == 200
    assert response.context["total_stadiums"] >= 1


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def two_country_data(db):
    """Italy (Serie A) + Germany (Bundesliga) with one team + stadium each."""
    it, _ = Country.objects.get_or_create(name="Italy", defaults={"code": "IT"})
    de, _ = Country.objects.get_or_create(name="Germany", defaults={"code": "DE"})
    serie_a, _ = League.objects.get_or_create(name="Serie A", country=it, defaults={"division_level": 1})
    bundesliga, _ = League.objects.get_or_create(name="Bundesliga", country=de, defaults={"division_level": 1})

    city_it, _ = City.objects.get_or_create(name="Milan", defaults={"country": "Italy", "population": 1400000})
    city_de, _ = City.objects.get_or_create(name="Munich", defaults={"country": "Germany", "population": 1500000})

    stad_it, _ = Stadium.objects.get_or_create(
        name="San Siro", city=city_it,
        defaults={"capacity": 75923, "latitude": 45.4781, "longitude": 9.1240, "ownership": "PUBLIC"},
    )
    stad_de, _ = Stadium.objects.get_or_create(
        name="Allianz Arena", city=city_de,
        defaults={"capacity": 75024, "latitude": 48.2188, "longitude": 11.6248, "ownership": "PRIVATE"},
    )

    Team.objects.get_or_create(name="Inter", defaults={"league": serie_a, "stadium": stad_it, "city": city_it, "tier": 1})
    Team.objects.get_or_create(name="Bayern", defaults={"league": bundesliga, "stadium": stad_de, "city": city_de, "tier": 1})

    return {"serie_a": serie_a, "bundesliga": bundesliga}


# ---------------------------------------------------------------------------
# team_detail
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_team_detail_page_loads(client, two_country_data):
    team = Team.objects.get(name="Inter")
    response = client.get(reverse("italiastadiaapp:team_detail", args=[team.slug]))
    assert response.status_code == 200
    assert b"Inter" in response.content


@pytest.mark.django_db
def test_team_detail_redirect(client, two_country_data):
    team = Team.objects.get(name="Inter")
    response = client.get(reverse("italiastadiaapp:team_detail_by_id", args=[team.pk]))
    assert response.status_code == 301
    assert f"/team/{team.slug}/" in response["Location"]


@pytest.mark.django_db
def test_team_detail_404(client):
    response = client.get(reverse("italiastadiaapp:team_detail", args=["no-such-team"]))
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# stadium_list
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_stadium_list_all_countries(client, two_country_data):
    response = client.get(reverse("italiastadiaapp:stadium_list"))
    assert response.status_code == 200
    sections = response.context["sections"]
    league_labels = [s["league_label"] for s in sections]
    assert "Serie A" in league_labels
    assert "Bundesliga" in league_labels


@pytest.mark.django_db
def test_stadium_list_filter_germany(client, two_country_data):
    response = client.get(reverse("italiastadiaapp:stadium_list") + "?country=Germany")
    assert response.status_code == 200
    sections = response.context["sections"]
    assert all(s["league"].country.name == "Germany" for s in sections if s["league"])
    stadia_names = [s.name for sec in sections for s in sec["stadia"]]
    assert "Allianz Arena" in stadia_names
    assert "San Siro" not in stadia_names


@pytest.mark.django_db
def test_stadium_list_filter_unknown_country(client, two_country_data):
    response = client.get(reverse("italiastadiaapp:stadium_list") + "?country=Zzz")
    assert response.status_code == 200
    assert response.context["sections"] == []


# ---------------------------------------------------------------------------
# team_list
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_team_list_all_countries(client, two_country_data):
    response = client.get(reverse("italiastadiaapp:team_list"))
    assert response.status_code == 200
    sections = response.context["sections"]
    league_labels = [s["league_label"] for s in sections]
    assert "Serie A" in league_labels
    assert "Bundesliga" in league_labels


@pytest.mark.django_db
def test_team_list_filter_germany(client, two_country_data):
    response = client.get(reverse("italiastadiaapp:team_list") + "?country=Germany")
    assert response.status_code == 200
    sections = response.context["sections"]
    team_names = [t.name for sec in sections for t in sec["teams"]]
    assert "Bayern" in team_names
    assert "Inter" not in team_names


# ---------------------------------------------------------------------------
# city_list
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_city_list_all_countries(client, two_country_data):
    response = client.get(reverse("italiastadiaapp:city_list"))
    assert response.status_code == 200
    city_names = [c.name for c in response.context["cities"]]
    assert "Milan" in city_names
    assert "Munich" in city_names


@pytest.mark.django_db
def test_city_list_filter_germany(client, two_country_data):
    response = client.get(reverse("italiastadiaapp:city_list") + "?country=Germany")
    assert response.status_code == 200
    city_names = [c.name for c in response.context["cities"]]
    assert "Munich" in city_names
    assert "Milan" not in city_names


@pytest.mark.django_db
def test_city_list_filter_unknown_country(client, two_country_data):
    response = client.get(reverse("italiastadiaapp:city_list") + "?country=Zzz")
    assert response.status_code == 200
    assert list(response.context["cities"]) == []


# ---------------------------------------------------------------------------
# tournament pages
# ---------------------------------------------------------------------------

@pytest.fixture
def euro_2028_venue(db):
    city = City.objects.create(name="London", population=9000000, country="England")
    stadium = Stadium.objects.create(
        name="Test Arena",
        city=city,
        latitude=51.555,
        longitude=-0.108,
        capacity=60000,
        ownership="PRIVATE",
        tournaments=[{"tournament": "UEFA Euro 2028", "year": 2028, "status": "CONFIRMED", "matches": 5}],
    )
    return stadium


@pytest.mark.django_db
def test_tournament_list_redirects_to_home(client):
    response = client.get(reverse("italiastadiaapp:tournament_list"))
    assert response.status_code == 302


@pytest.mark.django_db
def test_tournament_detail_page_loads(client, euro_2028_venue):
    response = client.get(reverse("italiastadiaapp:tournament_detail", args=["uefa-euro-2028"]))
    assert response.status_code == 200
    assert b"UEFA Euro 2028" in response.content
    assert b"Test Arena" in response.content
    assert response.context["confirmed_count"] == 1


@pytest.mark.django_db
def test_tournament_detail_404_unknown_slug(client):
    response = client.get(reverse("italiastadiaapp:tournament_detail", args=["no-such-tournament"]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_euro2036_groups_by_competing_bids(client):
    # Euro 2036 venues are seeded with `bid` labels by migration 0062.
    response = client.get(reverse("italiastadiaapp:tournament_detail", args=["uefa-euro-2036"]))
    assert response.status_code == 200
    html = response.content.decode()
    assert "Poland bid" in html
    assert "Nordic bid" in html
    assert "Balkan bid" in html
    assert "Host not yet decided" in html   # competing-bids explainer


@pytest.mark.django_db
def test_single_host_tournament_not_bid_grouped(client):
    # Regression: a tournament whose venues carry no `bid` keeps country grouping,
    # with no bid boxes (the 2036 bid layer must not leak into normal tournaments).
    city = City.objects.create(name="Testville", country="Italy")
    Stadium.objects.create(
        name="Regression Arena", slug="regression-arena", city=city,
        latitude=45.0, longitude=9.0, ownership="PUBLIC",
        tournaments=[{"tournament": "Test Cup 2040", "year": 2040, "status": "CONFIRMED"}],
    )
    response = client.get(reverse("italiastadiaapp:tournament_detail", args=["test-cup-2040"]))
    assert response.status_code == 200
    assert "Host not yet decided" not in response.content.decode()


@pytest.mark.django_db
def test_tournament_editorial_renders_for_euro2032(client):
    """Euro 2032 page shows the hand-written editorial card (Italy–Turkey joint bid)."""
    city = City.objects.create(name="Rome", country="Italy")
    Stadium.objects.create(
        name="Olimpico Editorial", city=city,
        latitude=41.93, longitude=12.45,
        ownership="PUBLIC",
        tournaments=[{"tournament": "UEFA Euro 2032", "year": 2032, "status": "CONFIRMED"}],
    )
    response = client.get(
        reverse("italiastadiaapp:tournament_detail", args=["uefa-euro-2032"])
    )
    assert response.status_code == 200
    html = response.content.decode()
    assert "Italy" in html and "Turkey" in html   # editorial mentions both nations
    assert response.context["tournament_editorial"] is not None
    assert "heading" in response.context["tournament_editorial"]


@pytest.mark.django_db
def test_export_options_includes_dev_statuses(client):
    """export_options must return dev_statuses so the frontend doesn't need to hardcode them."""
    response = client.get(reverse("italiastadiaapp:export_options"))
    assert response.status_code == 200
    data = response.json()
    assert "dev_statuses" in data
    values = [s["value"] for s in data["dev_statuses"]]
    assert set(values) == {"PLANNING", "APPROVED", "UNDER_CONSTRUCTION", "ON_HOLD", "COMPLETED"}