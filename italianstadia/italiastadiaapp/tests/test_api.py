import pytest
from django.urls import reverse

from italiastadiaapp.models import (
    City,
    Country,
    League,
    Stadium,
    StadiumDevelopment,
    Team,
)


@pytest.mark.django_db
def test_stadiums_geojson_returns_valid_feature_collection(client):
    city = City.objects.create(
        name="Test City",
        population=100000,
        country="Italy",
    )

    Stadium.objects.create(
        name="Test Stadium",
        city=city,
        latitude=45.0,
        longitude=9.0,
        ownership="PUBLIC",
    )

    response = client.get(reverse("italiastadiaapp:stadiums_geojson"))

    assert response.status_code == 200

    data = response.json()

    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1
    feature = data["features"][0]
    assert feature["geometry"]["coordinates"] == [9.0, 45.0]
    assert "country" in feature["properties"]


@pytest.mark.django_db
def test_stadiums_geojson_team_league_fields(client):
    # Use get_or_create — data migration may have already seeded Italy / Serie A
    country, _ = Country.objects.get_or_create(name="Italy", defaults={"code": "IT"})
    league, _ = League.objects.get_or_create(
        name="Serie A", country=country, defaults={"division_level": 1}
    )

    city = City.objects.create(name="Milan", population=1300000, country="Italy")
    stadium = Stadium.objects.create(
        name="San Siro", city=city, latitude=45.478, longitude=9.124, ownership="PUBLIC"
    )
    Team.objects.create(
        name="AC Milan", city=city, stadium=stadium, tier=1, league=league
    )

    response = client.get(reverse("italiastadiaapp:stadiums_geojson"))
    assert response.status_code == 200

    teams = response.json()["features"][0]["properties"]["teams"]
    assert len(teams) == 1
    t = teams[0]
    assert "league_id" in t
    assert "league_name" in t
    assert "division_level" in t
    assert "country" in t
    assert t["league_name"] == "Serie A"
    assert t["division_level"] == 1
    assert t["country"] == "Italy"
    assert "country_rank" in t  # UEFA rank exposed in GeoJSON for map sorting
    assert "image_url" in t     # required for badge marker rendering


@pytest.fixture
def two_league_data():
    """Italy (Serie A) + Germany (Bundesliga) — two stadiums, one per country."""
    it, _ = Country.objects.get_or_create(name="Italy",   defaults={"code": "IT"})
    de, _ = Country.objects.get_or_create(name="Germany", defaults={"code": "DE"})
    serie_a, _    = League.objects.get_or_create(name="Serie A",    country=it, defaults={"division_level": 1})
    bundesliga, _ = League.objects.get_or_create(name="Bundesliga", country=de, defaults={"division_level": 1})

    city_it = City.objects.create(name="Rome",   population=2800000, country="Italy")
    city_de = City.objects.create(name="Munich", population=1400000, country="Germany")

    st_it = Stadium.objects.create(name="Olimpico",    city=city_it, latitude=41.934, longitude=12.455, ownership="PUBLIC")
    st_de = Stadium.objects.create(name="Allianz",     city=city_de, latitude=48.219, longitude=11.625, ownership="PRIVATE")

    Team.objects.create(name="AS Roma",   city=city_it, stadium=st_it, tier=1, league=serie_a)
    Team.objects.create(name="FC Bayern", city=city_de, stadium=st_de, tier=1, league=bundesliga)
    return {"stadiums": [st_it, st_de]}


@pytest.mark.django_db
def test_server_filter_by_country(client, two_league_data):
    url = reverse("italiastadiaapp:stadiums_geojson")
    data = client.get(url + "?country=Italy").json()
    assert len(data["features"]) == 1
    assert data["features"][0]["properties"]["name"] == "Olimpico"


@pytest.mark.django_db
def test_server_filter_by_league(client, two_league_data):
    url = reverse("italiastadiaapp:stadiums_geojson")
    data = client.get(url + "?league=Bundesliga").json()
    assert len(data["features"]) == 1
    assert data["features"][0]["properties"]["name"] == "Allianz"


@pytest.mark.django_db
def test_server_filter_by_ownership(client, two_league_data):
    url = reverse("italiastadiaapp:stadiums_geojson")
    data = client.get(url + "?ownership=PUBLIC").json()
    names = [f["properties"]["name"] for f in data["features"]]
    assert "Olimpico" in names
    assert "Allianz" not in names


@pytest.mark.django_db
def test_server_filter_nonexistent_league_returns_empty(client, two_league_data):
    url = reverse("italiastadiaapp:stadiums_geojson")
    data = client.get(url + "?league=NonExistentLeague").json()
    assert data["type"] == "FeatureCollection"
    assert data["features"] == []


@pytest.mark.django_db
def test_server_filter_combined(client, two_league_data):
    """country + ownership together — only Italian public stadiums."""
    url = reverse("italiastadiaapp:stadiums_geojson")
    data = client.get(url + "?country=Italy&ownership=PUBLIC").json()
    assert len(data["features"]) == 1
    assert data["features"][0]["properties"]["name"] == "Olimpico"


@pytest.mark.django_db
def test_stadium_developments_geojson(client):

    StadiumDevelopment.objects.create(
        name="Test New Stadium",
        project_type="NEW",
        status="PLANNING",
        future_capacity=30000,
        estimated_opening=2028,
        latitude=45.0,
        longitude=9.0,
    )

    response = client.get(reverse("italiastadiaapp:stadium_developments_geojson"))

    assert response.status_code == 200

    data = response.json()

    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1