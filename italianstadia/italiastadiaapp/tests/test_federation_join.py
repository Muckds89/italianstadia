"""
Which countries light up is decided by the club's FEDERATION, not by geography.

The spotlight used to ask which border polygon CONTAINED each ground — a spatial
join. That is the wrong question, because a federation is not a shape. AS Monaco
play in Ligue 1 from a ground in a different sovereign state, so containment lit up
Monaco and left France dark on a map of French clubs. The same applies to FC Andorra
in the Segunda, Vaduz in the Swiss league, Derry City in the League of Ireland, and
Cardiff, Swansea and Wrexham in the EFL.

It is now a field join on Team.league.country. Containment survives only as the
fallback for a ground with no federation recorded.
"""
import json
from pathlib import Path

from django.test import SimpleTestCase

from italiastadiaapp.views import _FEDERATION_POLYGON_ALIAS, _federation_of


class _Country:
    def __init__(self, name): self.name = name


class _League:
    def __init__(self, country): self.country = _Country(country)


class _Team:
    def __init__(self, country, is_national=False):
        self.league_id, self.league = 1, _League(country)
        self.is_national = is_national


class FederationOfTests(SimpleTestCase):

    def test_a_club_playing_abroad_reports_its_federation(self):
        """The whole point: the ground's own country is the misleading answer."""
        self.assertEqual(_federation_of([_Team("France")]), "France")

    def test_a_club_tenant_beats_a_national_side(self):
        """A ground hosting both should answer with the club's federation."""
        teams = [_Team("Wales", is_national=True), _Team("England")]
        self.assertEqual(_federation_of(teams), "England")

    def test_a_national_side_alone_still_answers(self):
        self.assertEqual(_federation_of([_Team("Wales", is_national=True)]), "Wales")

    def test_no_league_means_no_federation_rather_than_a_guess(self):
        """Empty falls back to containment; it must not invent a country."""
        self.assertEqual(_federation_of([]), "")


class FederationPolygonTests(SimpleTestCase):
    """A name join fails SILENTLY — the country just never lights up — so every
    federation the database can produce must resolve to a border polygon."""

    def _polygon_names(self):
        p = (Path(__file__).resolve().parent.parent
             / "static" / "data" / "countries_hires.geojson")
        data = json.loads(p.read_text(encoding="utf-8"))
        return {(f.get("properties", {}).get("name") or "").strip().lower()
                for f in data["features"]}

    # NOTE: "does every country in the DATABASE resolve to a polygon?" is NOT here.
    # pytest runs against an EMPTY test database, so that assertion would iterate
    # nothing and pass while the live data had unmatched federations — the exact
    # vacuous-test trap this repo has been bitten by before. It lives in
    # `manage.py check_map_integrity`, which runs against the real rows.

    def test_the_czechia_alias_is_present(self):
        """The one real mismatch: the model says Czechia, the border data says
        Czech Republic. Named explicitly so removing it fails loudly."""
        names = self._polygon_names()
        self.assertNotIn("czechia", names)
        self.assertIn(_FEDERATION_POLYGON_ALIAS["czechia"].lower(), names)
