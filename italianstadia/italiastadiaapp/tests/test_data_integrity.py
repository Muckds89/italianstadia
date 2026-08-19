"""
Data invariants that fail SILENTLY in production.

Each of these has actually happened, and none of them raised anything: a stadium
with no coordinates is simply dropped from every map, so Kosovo rendered 8 of its
10 clubs and Wales 11 of its 12 with no error, no warning and no visual cue that
anything was missing.

These run against the FIXTURE, which is the data that reaches production, so a
regression is caught before deploy rather than by a Reddit commenter.
"""
from django.test import TestCase

from italiastadiaapp.models import League, Stadium, Team


class CoordinatesAreMandatoryTests(TestCase):
    """A ground with no coordinates cannot be drawn, so it is silently omitted."""

    def test_no_stadium_hosting_a_club_lacks_coordinates(self):
        bad = [
            f"{s.name} ({', '.join(t.name for t in s.teams.all())})"
            for s in Stadium.objects.prefetch_related("teams")
            if (s.latitude is None or s.longitude is None) and s.teams.exists()
        ]
        self.assertEqual(bad, [], f"{len(bad)} ground(s) would vanish from the map: {bad}")

    def test_every_club_in_a_visible_league_has_a_ground(self):
        bad = [
            f"{t.name} ({t.league.name})"
            for t in Team.objects.select_related("stadium", "league")
            .filter(is_national=False, league__hidden=False)
            .exclude(league__isnull=True)
            if t.stadium is None
        ]
        self.assertEqual(bad, [], f"{len(bad)} club(s) have no ground: {bad}")


class LeagueShapeTests(TestCase):

    def test_club_tier_matches_its_league_division_level(self):
        """`tier` and `division_level` are separate fields and nothing enforces
        agreement, so a club moved between tiers can keep a stale tier and drop
        out of tier-filtered views."""
        bad = [
            f"{t.name}: tier={t.tier} but {t.league.name} is level {t.league.division_level}"
            for t in Team.objects.select_related("league")
            .filter(is_national=False).exclude(league__isnull=True)
            if t.tier != t.league.division_level
        ]
        self.assertEqual(bad, [], f"{len(bad)} club(s) with a stale tier: {bad[:10]}")

    def test_a_league_holding_clubs_declares_a_season(self):
        bad = [
            lg.name for lg in League.objects.filter(division_level__gte=1)
            if lg.teams.exists() and not (lg.season or "").strip()
        ]
        self.assertEqual(bad, [], f"league(s) with clubs but no season tag: {bad}")
