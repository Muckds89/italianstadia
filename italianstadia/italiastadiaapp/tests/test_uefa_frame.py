"""
The three continental competitions share ONE fixed frame, and no club is ever lost.

They are published as a set, so a Champions League map that stops at Vienna beside a
Conference League map that reaches Baku does not read as a series. Before this, a UEFA
export fell into the "broad Europe" branch, which crops to fill the canvas — Barcelona,
Real Madrid, Roma and Galatasaray ended up outside the frame while the label engine
still drew them, pointing off-canvas at nothing.

The frame stays on Europe. A ground outside it — Kairat of Almaty at 76.9°E — gets its
own box rather than dragging the window east, which is how an atlas handles Madeira.
Widening for Almaty shrank Europe on all three maps AND buried Kairat's badge under the
label column, so it fixed nothing.
"""
from django.test import SimpleTestCase

from italiastadiaapp.views import (_UEFA_FRAME, _expand_bbox_to_aspect,
                                   _outside_frame_groups, _uefa_frame_bbox)

# Each pins an edge of the window, plus the two non-European associations whose clubs
# play in UEFA competitions. Coordinates are the stored ones.
EUROPEAN = [
    {"lon": -9.257, "lat": 38.567, "name": "Torreense (west)"},
    {"lon": 49.766, "lat": 40.435, "name": "Sabah, Baku (east)"},
    {"lon": 34.789, "lat": 31.273, "name": "Hapoel Be'er Sheva (south)"},
    {"lon": 14.383, "lat": 67.277, "name": "Bodo/Glimt (north)"},
    {"lon": 39.647, "lat": 41.003, "name": "Trabzonspor (Turkey)"},
]
ALMATY = {"lon": 76.924, "lat": 43.238, "name": "Kairat, Almaty"}
SIZES = [(1280, 720), (1920, 1080), (3840, 2160)]


class UefaFrameTests(SimpleTestCase):

    def test_the_window_holds_every_european_participant(self):
        lon0, lat0, lon1, lat1 = _UEFA_FRAME
        for s in EUROPEAN:
            self.assertTrue(lon0 <= s["lon"] <= lon1, f'{s["name"]} outside in longitude')
            self.assertTrue(lat0 <= s["lat"] <= lat1, f'{s["name"]} outside in latitude')

    def test_israel_and_turkey_are_in_shot(self):
        """Both were explicitly asked for: their clubs play in UEFA competitions."""
        lon0, lat0, lon1, lat1 = _UEFA_FRAME
        self.assertLess(lat0, 31.3, "southern edge cuts off Israel")
        self.assertGreater(lon1, 39.7, "eastern edge cuts off eastern Turkey")

    def test_almaty_is_boxed_rather_than_widening_the_window(self):
        """The whole point of the redesign. Widening to 76.9E shrank Europe on every
        map and still hid Kairat under the right-hand label column."""
        self.assertLess(_UEFA_FRAME[2], 76.9, "the window stretched to Kazakhstan")
        inside, groups = _outside_frame_groups(EUROPEAN + [ALMATY], _UEFA_FRAME)
        self.assertEqual([[s["name"] for s in g] for g in groups], [["Kairat, Almaty"]])
        self.assertNotIn(ALMATY, inside)

    def test_the_frame_does_not_move_when_an_outlier_is_added(self):
        """Adding Kazakhstan to the dataset must not reframe the other two maps."""
        without = _uefa_frame_bbox(EUROPEAN)
        inside, _ = _outside_frame_groups(EUROPEAN + [ALMATY], _UEFA_FRAME)
        self.assertEqual(_uefa_frame_bbox(inside), without)

    def test_frame_is_identical_at_every_canvas_size(self):
        """The HD preview and the 4K file someone paid for must show the same area."""
        frames = {tuple(round(v, 4) for v in
                        _expand_bbox_to_aspect(_uefa_frame_bbox(EUROPEAN), w, h))
                  for w, h in SIZES}
        self.assertEqual(len(frames), 1, f"frame varies by canvas size: {frames}")


class NothingIsEverLostTests(SimpleTestCase):
    """A club missing from a map of its own competition is the worst outcome here.
    _outside_frame_groups must return every input in exactly one place."""

    def _all_back(self, stadiums, **kw):
        inside, groups = _outside_frame_groups(stadiums, _UEFA_FRAME, **kw)
        seen = [s["name"] for s in inside] + [s["name"] for g in groups for s in g]
        self.assertCountEqual(seen, [s["name"] for s in stadiums])
        return inside, groups

    def test_every_ground_comes_back(self):
        self._all_back(EUROPEAN + [ALMATY])

    def test_nothing_outside_means_nothing_boxed(self):
        inside, groups = self._all_back(EUROPEAN)
        self.assertEqual(groups, [])

    def test_overflow_beyond_max_groups_returns_to_the_main_map(self):
        """More scattered outliers than there are boxes: the extras must come back
        so the caller's frame widens for them, never vanish."""
        far = [dict(ALMATY, name=f"far{i}", lon=60.0 + i * 20, lat=40.0 + i * 5)
               for i in range(5)]
        inside, groups = self._all_back(EUROPEAN + far, max_groups=2)
        self.assertEqual(len(groups), 2)
        self.assertGreater(len([s for s in inside if s["name"].startswith("far")]), 0)

    def test_neighbouring_outliers_share_one_box(self):
        """Two distant grounds near each other should not take two boxes."""
        pair = [dict(ALMATY, name="a"), dict(ALMATY, name="b", lon=77.5)]
        _, groups = self._all_back(EUROPEAN + pair)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)
