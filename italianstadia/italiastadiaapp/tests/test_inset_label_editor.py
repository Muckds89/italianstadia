"""
Hand-placed inset labels.

The inset label engine has two degrees of freedom -- which column (by x-rank) and
the vertical slot in that column -- and it never looks at where the badges are.
When a dense metro does not fit, the only lever is shrinking the font, and the
renderer then draws badges back over the pills because losing a ground is worse
than clipping text. A congested inset therefore cannot be improved by
regenerating, which is what the drag editor exists to solve.

Positions are FRACTIONS of the inset box, not pixels, so a layout dragged on the
HD preview lands identically on a 4K paid download.
"""
from django.test import SimpleTestCase

from italiastadiaapp.views import _parse_label_overrides, _label_key


class ParseLabelOverridesTests(SimpleTestCase):

    def test_parses_multiple_pairs(self):
        self.assertEqual(
            _parse_label_overrides("a-ground:0.1,0.2;b-ground:0.75,0.5"),
            {"a-ground": (0.1, 0.2), "b-ground": (0.75, 0.5)})

    def test_blank_input_yields_nothing(self):
        for raw in ("", None, "   ", ";;"):
            self.assertEqual(_parse_label_overrides(raw), {})

    def test_a_corrupt_pair_never_costs_the_whole_map(self):
        # this arrives from a query string; one bad entry must not raise
        got = _parse_label_overrides("good:0.2,0.3;broken;alsobad:x,y;third:0.4,0.4")
        self.assertEqual(got, {"good": (0.2, 0.3), "third": (0.4, 0.4)})

    def test_wildly_out_of_range_values_are_dropped_as_corrupt(self):
        self.assertEqual(_parse_label_overrides("k:9,9"), {})
        self.assertEqual(_parse_label_overrides("k:-40,0.5"), {})

    def test_slightly_negative_is_kept_because_a_pill_may_overhang(self):
        self.assertEqual(_parse_label_overrides("k:-0.02,0.5"), {"k": (-0.02, 0.5)})


class LabelKeyTests(SimpleTestCase):
    """The key must survive a re-render, or saved positions reattach to the wrong
    ground the moment a filter changes the stadium set."""

    def test_prefers_the_stadium_slug(self):
        self.assertEqual(_label_key({"slug": "besiktas-park", "name": "Tüpraş Stadyumu"}),
                         "besiktas-park")

    def test_falls_back_to_a_slugified_name(self):
        # tournament and development venues carry no slug
        self.assertEqual(_label_key({"name": "Estadio Municipal de Anduva"}),
                         "estadio-municipal-de-anduva")

    def test_is_stable_for_the_same_input(self):
        s = {"name": "Çaykur Didi Stadyumu"}
        self.assertEqual(_label_key(s), _label_key(s))


class ResolutionParityTests(SimpleTestCase):
    """A layout dragged on the HD preview must reproduce on the paid download.

    The preview is always rendered at HD (the paid file may be FHD or 4K), so if
    the inset's internal metrics are absolute pixels the same fraction lands in a
    different place and the customer gets a file that does not match what they
    bought. `PAD`, the pill row gap and the font-shrink step were all fixed pixel
    counts, and the "Detail view" header reserved `int(IW*0.03) + 16` -- 16.9% of
    the box at HD but 13.8% at FHD.
    """

    def _place(self, W, H, drop):
        from PIL import Image
        from italiastadiaapp.views import _draw_inset, _inset_layout
        grounds = [
            {"name": "Chobani Stadyumu FB Sukru Saracoglu Kompleksi",
             "slug": "fener", "team_name": "Fenerbahce SK",
             "lat": 40.9878, "lon": 29.0370, "image_url": ""},
            {"name": "Tupras Stadyumu", "slug": "besiktas",
             "team_name": "Besiktas JK", "lat": 41.0392, "lon": 29.0060,
             "image_url": ""},
            {"name": "Ali Sami Yen Spor Kompleksi RAMS Park", "slug": "gala",
             "team_name": "Galatasaray SK", "lat": 41.1036, "lon": 28.9906,
             "image_url": ""},
        ]
        params = {"tiles": False, "bg_color": (20, 24, 34), "badge_size": 13,
                  "label_size": 22, "style_key": "dark", "no_badges": True,
                  "color_by": "single", "single_color": (245, 197, 66),
                  "label_pos": {"fener": drop}}
        layout = _inset_layout(grounds, W, H)
        sink = []
        _draw_inset(Image.new("RGBA", (W, H)), grounds, params, W, H, {}, "dark",
                    layout=layout, show_source=False,
                    label_overrides=params["label_pos"], geometry_sink=sink)
        got = [L for L in sink if L["key"] == "fener"][0]
        return got["x"], got["y"]

    def test_same_fraction_at_hd_fhd_and_4k(self):
        for drop in ((0.30, 0.55), (0.05, 0.30), (0.55, 0.60)):
            hd = self._place(1280, 720, drop)
            fhd = self._place(1920, 1080, drop)
            uhd = self._place(3840, 2160, drop)
            for other, name in ((fhd, "FHD"), (uhd, "4K")):
                self.assertAlmostEqual(hd[0], other[0], delta=0.008,
                                       msg=f"x drifted at {name} for {drop}")
                self.assertAlmostEqual(hd[1], other[1], delta=0.008,
                                       msg=f"y drifted at {name} for {drop}")

    def test_header_strip_is_a_constant_fraction_of_the_box(self):
        # dropping into the header must clamp to the same place at every size
        hd = self._place(1280, 720, (0.4, 0.0))
        fhd = self._place(1920, 1080, (0.4, 0.0))
        self.assertAlmostEqual(hd[1], fhd[1], delta=0.008)

    def test_an_untouched_label_is_not_disturbed(self):
        from PIL import Image
        from italiastadiaapp.views import _draw_inset, _inset_layout
        grounds = [
            {"name": "A Park", "slug": "a", "team_name": "A FC",
             "lat": 41.00, "lon": 29.00, "image_url": ""},
            {"name": "B Park", "slug": "b", "team_name": "B FC",
             "lat": 41.05, "lon": 29.05, "image_url": ""},
        ]
        base = {"tiles": False, "bg_color": (20, 24, 34), "badge_size": 13,
                "label_size": 22, "style_key": "dark", "no_badges": True,
                "color_by": "single", "single_color": (245, 197, 66)}
        layout = _inset_layout(grounds, 1280, 720)

        def run(overrides):
            sink = []
            _draw_inset(Image.new("RGBA", (1280, 720)), grounds, dict(base),
                        1280, 720, {}, "dark", layout=layout, show_source=False,
                        label_overrides=overrides, geometry_sink=sink)
            return {L["key"]: (L["x"], L["y"], L["moved"]) for L in sink}

        before = run({})
        after = run({"a": (0.4, 0.6)})
        self.assertEqual(before["b"][:2], after["b"][:2])
        self.assertTrue(after["a"][2])
        self.assertFalse(after["b"][2])
