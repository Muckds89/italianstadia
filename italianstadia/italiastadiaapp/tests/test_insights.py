import json

import pytest
from django.urls import reverse

from italiastadiaapp.models import City, Country, League, Stadium, Team


@pytest.fixture
def insight_data(db):
    """A national-only ground, a club ground with a surface, and a populated country."""
    country = Country.objects.create(name="Testland", code="TL", population=2_000_000)
    league = League.objects.create(name="Test League", country=country, division_level=1)
    city = City.objects.create(name="Testville", country="Testland")

    nat_stad = Stadium.objects.create(name="National Arena TL", city=city,
                                      latitude=45.0, longitude=9.0, surface="GRASS")
    nat_team = Team.objects.create(name="Testland NT", stadium=nat_stad, city=city,
                                   league=league, is_national=True)

    club_stad = Stadium.objects.create(name="Club Park TL", city=city,
                                       latitude=45.1, longitude=9.1, surface="ARTIFICIAL")
    Team.objects.create(name="Test FC", stadium=club_stad, city=city,
                        league=league, tier=1, is_national=False)
    return {"country": country, "nat_stad": nat_stad, "club_stad": club_stad}


@pytest.mark.django_db
def test_insights_index(client):
    r = client.get(reverse("italiastadiaapp:insights_index"))
    assert r.status_code == 200
    assert b"Stadium Insights" in r.content


@pytest.mark.django_db
def test_insight_national_page(client, insight_data):
    r = client.get(reverse("italiastadiaapp:insight_national"))
    assert r.status_code == 200
    assert b"National Arena TL" in r.content
    # a club-only ground must NOT appear on the national-only page
    assert b"Club Park TL" not in r.content


@pytest.mark.django_db
def test_insight_surface_page(client, insight_data):
    r = client.get(reverse("italiastadiaapp:insight_surface"))
    assert r.status_code == 200
    assert b"natural grass" in r.content.lower()


@pytest.mark.django_db
def test_insight_density_page(client, insight_data):
    r = client.get(reverse("italiastadiaapp:insight_density"))
    assert r.status_code == 200
    assert b"Testland" in r.content


@pytest.mark.django_db
def test_geojson_view_national(client, insight_data):
    url = reverse("italiastadiaapp:stadiums_geojson") + "?view=national"
    r = client.get(url)
    assert r.status_code == 200
    names = {f["properties"]["name"] for f in json.loads(r.content)["features"]}
    assert "National Arena TL" in names
    assert "Club Park TL" not in names


@pytest.mark.django_db
def test_insight_biggest_page(client, insight_data):
    r = client.get(reverse("italiastadiaapp:insight_biggest"))
    assert r.status_code == 200
    assert b"biggest stadiums by capacity" in r.content.lower()


@pytest.mark.django_db
def test_geojson_view_capacity(client, insight_data):
    # insight_data stadiums have no capacity, so add one with capacity
    from italiastadiaapp.models import City, Stadium
    city = City.objects.create(name="Capville", country="Testland")
    Stadium.objects.create(name="Big Bowl", city=city, latitude=1.0, longitude=2.0, capacity=50000)
    url = reverse("italiastadiaapp:stadiums_geojson") + "?view=capacity"
    r = client.get(url)
    assert r.status_code == 200
    feats = json.loads(r.content)["features"]
    assert feats and all(f["properties"]["capacity"] for f in feats)


@pytest.mark.django_db
def test_geojson_view_surface(client, insight_data):
    url = reverse("italiastadiaapp:stadiums_geojson") + "?view=surface"
    r = client.get(url)
    assert r.status_code == 200
    feats = json.loads(r.content)["features"]
    names = {f["properties"]["name"] for f in feats}
    # both seeded stadiums have a surface set
    assert {"National Arena TL", "Club Park TL"} <= names
    assert all(f["properties"]["surface"] for f in feats)
