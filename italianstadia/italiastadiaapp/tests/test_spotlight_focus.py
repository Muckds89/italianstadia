"""
Spotlight country selection.

The bundled border data used to carry ONE "United Kingdom" polygon, so England,
Scotland, Wales and Northern Ireland could not be distinguished at all -- the
spotlight code said as much ("works even for England -> the UK polygon"). It now
carries the four home nations as separate Natural Earth map units.

That split alone is not enough, because an English league is not confined to
England: Cardiff, Swansea and Wrexham play in the EFL. Letting the grounds pick
the highlight by containment lights up Wales too, so the highlight follows the
country the map was FILTERED on, and the Welsh clubs stay visible as markers
outside the lit area -- which is the accurate picture.
"""
from django.test import SimpleTestCase

from italiastadiaapp.views import _load_countries_hi


class HomeNationGeometryTests(SimpleTestCase):

    def setUp(self):
        self.names = {(f.get("properties") or {}).get("name")
                      for f in _load_countries_hi()}

    def test_four_home_nations_are_separate_polygons(self):
        for n in ("England", "Scotland", "Wales", "Northern Ireland"):
            self.assertIn(n, self.names, f"{n} missing from the border data")

    def test_merged_united_kingdom_polygon_is_gone(self):
        # leaving it in would double-light England, since both contain the grounds
        self.assertNotIn("United Kingdom", self.names)

    def test_ireland_is_untouched(self):
        # Northern Ireland is a UK map unit; the Republic must remain its own country
        self.assertIn("Ireland", self.names)


class SpotlightFocusTests(SimpleTestCase):
    """A named focus must win over where the grounds actually are."""

    def _lit(self, focus, grounds):
        from PIL import Image
        from italiastadiaapp.views import _spotlight_country
        W, H = 200, 200
        bbox = (-8.0, 49.5, 2.0, 56.0)          # Great Britain
        img = Image.new("RGBA", (W, H), (255, 255, 255, 255))
        out = _spotlight_country(img, grounds, bbox, W, H, focus=focus)
        # a dimmed pixel is darkened; count what stayed bright
        px = out.convert("RGB").load()
        return sum(1 for x in range(0, W, 2) for y in range(0, H, 2)
                   if sum(px[x, y]) > 600)

    def test_welsh_ground_does_not_light_wales_when_england_is_the_focus(self):
        cardiff = [{"lon": -3.2030, "lat": 51.4728}]
        england_only = self._lit("England", cardiff)
        both = self._lit(None, cardiff)     # containment: lights Wales instead
        self.assertGreater(england_only, 0, "England should still be lit")
        self.assertNotEqual(england_only, both)

    def test_unknown_focus_falls_back_to_containment(self):
        # a country we hold no polygon for must not blank the map
        cardiff = [{"lon": -3.2030, "lat": 51.4728}]
        self.assertGreater(self._lit("Atlantis", cardiff), 0)

    def test_no_grounds_leaves_the_map_untouched(self):
        from PIL import Image
        from italiastadiaapp.views import _spotlight_country
        img = Image.new("RGBA", (50, 50), (255, 255, 255, 255))
        out = _spotlight_country(img, [], (-8.0, 49.5, 2.0, 56.0), 50, 50,
                                 focus="England")
        self.assertEqual(out.convert("RGB").getpixel((25, 25)), (255, 255, 255))
