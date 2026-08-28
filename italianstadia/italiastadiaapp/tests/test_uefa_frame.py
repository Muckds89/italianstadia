"""
The three continental competitions share ONE fixed frame.

They are published as a set, so a Champions League map that stops at Vienna beside
a Conference League map that reaches Baku does not read as a series. Before this,
a UEFA export fell into the "broad Europe" branch, which crops to fill the canvas —
Barcelona, Real Madrid, Roma and Galatasaray ended up outside the frame while the
label engine still drew them, pointing off-canvas at nothing.
"""
from django.test import SimpleTestCase

from italiastadiaapp.views import (_UEFA_FRAME, _expand_bbox_to_aspect,
                                   _uefa_frame_bbox)

# Every participant that pins an edge, plus the two non-European associations whose
# clubs play in UEFA competitions. Coordinates are the stored ones.
EDGE_CASES = [
    {"lon": -9.257, "lat": 38.567, "n": "Torreense (west)"},
    {"lon": 49.766, "lat": 40.435, "n": "Sabah, Baku (east)"},
    {"lon": 34.789, "lat": 31.273, "n": "Hapoel Be'er Sheva (south)"},
    {"lon": 14.383, "lat": 67.277, "n": "Bodo/Glimt (north)"},
    {"lon": 39.647, "lat": 41.003, "n": "Trabzonspor (Turkey)"},
]
SIZES = [(1280, 720), (1920, 1080), (3840, 2160)]


class UefaFrameTests(SimpleTestCase):

    def test_constant_already_contains_every_participant(self):
        """If the constant needed widening the frame would MOVE between maps."""
        lon0, lat0, lon1, lat1 = _UEFA_FRAME
        for s in EDGE_CASES:
            self.assertTrue(lon0 <= s["lon"] <= lon1, f'{s["n"]} outside in longitude')
            self.assertTrue(lat0 <= s["lat"] <= lat1, f'{s["n"]} outside in latitude')

    def test_frame_is_identical_for_every_competition(self):
        """UCL, UEL and UECL have different club sets and must still frame alike."""
        subsets = [EDGE_CASES, EDGE_CASES[:3], EDGE_CASES[1:], []]
        frames = {_uefa_frame_bbox(s) for s in subsets}
        self.assertEqual(len(frames), 1, f"frame varies by club set: {frames}")

    def test_frame_is_identical_at_every_canvas_size(self):
        """The HD preview and the 4K file someone paid for must show the same area."""
        frames = {tuple(round(v, 4) for v in
                        _expand_bbox_to_aspect(_uefa_frame_bbox(EDGE_CASES), w, h))
                  for w, h in SIZES}
        self.assertEqual(len(frames), 1, f"frame varies by canvas size: {frames}")

    def test_nothing_is_cropped_out(self):
        bb = _expand_bbox_to_aspect(_uefa_frame_bbox(EDGE_CASES), 1280, 720)
        for s in EDGE_CASES:
            self.assertTrue(bb[0] <= s["lon"] <= bb[2], f'{s["n"]} cropped in longitude')
            self.assertTrue(bb[1] <= s["lat"] <= bb[3], f'{s["n"]} cropped in latitude')

    def test_an_outlier_widens_rather_than_being_cut(self):
        """A fixed frame that silently crops is worse than none: the label is drawn
        either way, so a cropped club becomes a label pointing at empty margin."""
        far = EDGE_CASES + [{"lon": 60.0, "lat": 55.0, "n": "hypothetical Ural club"}]
        self.assertGreaterEqual(_uefa_frame_bbox(far)[2], 60.0)

    def test_israel_and_turkey_are_in_shot(self):
        """Both were explicitly asked for: their clubs play in UEFA competitions."""
        lon0, lat0, lon1, lat1 = _UEFA_FRAME
        self.assertLess(lat0, 31.3, "southern edge cuts off Israel")
        self.assertGreater(lon1, 39.7, "eastern edge cuts off eastern Turkey")
