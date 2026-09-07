"""
Leader-line colour and thickness, and the hand-placed main-map labels.

Both leader controls existed only as constants before: the colour was borrowed
from the label text, and the width was a literal `width=1`. That literal is the
absolute-pixel trap this renderer keeps falling into -- one pixel is one pixel at
1280 and still one pixel at 3840, so a paid 4K download drew its leaders three
times finer, relative to its own labels and badges, than the HD preview the buyer
chose from. `line_width` is therefore in REFERENCE pixels and scaled at draw time,
exactly like label_size and badge_size.

`line_color` defaults to EMPTY rather than to a colour, and empty means "follow
the label colour". That is not a nicety: every saved link and every paid token
already in circulation was rendered with leaders that matched the label colour,
and defaulting to #ffffff would repaint all of them.
"""
from django.test import SimpleTestCase

from italiastadiaapp.views import (
    _REFERENCE_W, _leader_rgb, _leader_width, _parse_label_overrides,
)


class LeaderColourTests(SimpleTestCase):

    def test_empty_follows_the_label_colour(self):
        """The default. Anything else repaints every existing saved map."""
        self.assertEqual(_leader_rgb({}, (200, 30, 40)), (200, 30, 40))
        self.assertEqual(_leader_rgb({"line_color": ""}, (1, 2, 3)), (1, 2, 3))
        self.assertEqual(_leader_rgb({"line_color": "   "}, (1, 2, 3)), (1, 2, 3))

    def test_an_explicit_colour_wins(self):
        self.assertEqual(_leader_rgb({"line_color": "#00e5ff"}, (255, 255, 255)),
                         (0, 229, 255))

    def test_the_hash_is_optional(self):
        self.assertEqual(_leader_rgb({"line_color": "00e5ff"}, (0, 0, 0)),
                         (0, 229, 255))

    def test_junk_falls_back_instead_of_raising(self):
        """This arrives from a query string; one bad value must not cost the map."""
        for bad in ("#12345", "nonsense", "#zzzzzz", "#1234567", None, 42):
            self.assertEqual(_leader_rgb({"line_color": bad}, (9, 8, 7)), (9, 8, 7))


class LeaderWidthTests(SimpleTestCase):

    def test_one_reference_pixel_is_one_pixel_at_preview_size(self):
        self.assertEqual(_leader_width({"line_width": 1}, _REFERENCE_W), 1)

    def test_the_width_scales_with_the_canvas(self):
        """The whole point: the paid file must look like the preview.

        At a flat width=1 these three were all 1px, so the leaders got relatively
        finer the more the buyer paid.
        """
        self.assertEqual(_leader_width({"line_width": 1}, 1280), 1)
        self.assertEqual(_leader_width({"line_width": 1}, 1920), 2)
        self.assertEqual(_leader_width({"line_width": 1}, 3840), 3)

    def test_a_thicker_setting_scales_too(self):
        self.assertEqual(_leader_width({"line_width": 2}, 1280), 2)
        self.assertEqual(_leader_width({"line_width": 2}, 3840), 6)

    def test_it_never_disappears(self):
        """A sub-pixel result must still draw; 0 would be an invisible leader."""
        self.assertEqual(_leader_width({"line_width": 0.5}, 640), 1)
        self.assertGreaterEqual(_leader_width({"line_width": 0.5}, 1280), 1)

    def test_missing_or_junk_behaves_like_the_default(self):
        for params in ({}, {"line_width": None}, {"line_width": "wide"},
                       {"line_width": ""}):
            self.assertEqual(_leader_width(params, _REFERENCE_W), 1)

    def test_the_ratio_to_the_canvas_is_what_stays_constant(self):
        """CLAUDE.md's rule: compare the FRACTION at HD, FHD and 4K."""
        fracs = [_leader_width({"line_width": 2}, w) / float(w)
                 for w in (1280, 1920, 3840)]
        self.assertLess(max(fracs) - min(fracs), 1e-4)


class MapLabelOverrideParsingTests(SimpleTestCase):
    """The main-map overrides reuse the inset's grammar, deliberately.

    One parser means one set of corruption rules. These assert the properties the
    renderer depends on rather than re-testing the parser's internals.
    """

    def test_positions_are_fractions_not_pixels(self):
        got = _parse_label_overrides("san-siro:0.5,0.25")
        self.assertEqual(got, {"san-siro": (0.5, 0.25)})

    def test_one_corrupt_entry_never_costs_the_others(self):
        got = _parse_label_overrides("a:0.1,0.1;garbage;b:0.9,0.9")
        self.assertEqual(got, {"a": (0.1, 0.1), "b": (0.9, 0.9)})

    def test_absent_input_means_no_overrides_not_an_error(self):
        self.assertEqual(_parse_label_overrides(""), {})
        self.assertEqual(_parse_label_overrides(None), {})
