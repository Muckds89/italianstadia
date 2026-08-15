"""GoogleAnalyticsMiddleware: GA4 tag injected on every HTML page when the id is set."""
from django.test import TestCase, override_settings
from django.utils.html import escape
from django.urls import reverse

GID = "G-TEST123456"


class GoogleAnalyticsMiddlewareTests(TestCase):
    @override_settings(GOOGLE_ANALYTICS_ID=GID)
    def test_tag_injected_when_id_set(self):
        resp = self.client.get(reverse("italiastadiaapp:home"))
        body = resp.content.decode()
        self.assertIn(f"gtag/js?id={GID}", body)
        self.assertIn(f"gtag('config','{GID}')", body)
        # Consent Mode v2: defaults to denied (cookieless) until the banner grants it,
        # or until the head snippet restores a previously stored "accepted" choice.
        self.assertIn("gtag('consent','default'", body)
        self.assertIn("'analytics_storage':_cs", body)
        self.assertIn("'granted':'denied'", body)
        # injected inside <head>, and exactly once
        self.assertEqual(body.count("googletagmanager.com/gtag/js"), 1)
        self.assertLess(body.index("gtag/js"), body.index("</head>"))

    @override_settings(GOOGLE_ANALYTICS_ID=GID)
    def test_stored_consent_is_restored_before_config_fires(self):
        """A returning visitor who already accepted must have consent restored in the
        head snippet, BEFORE gtag('config') sends page_view. consent.js updates from a
        DOMContentLoaded handler at the end of the body, by which point page_view and
        the export funnel's view_item have already gone out tagged gcs=G100 (denied) --
        GA4 keeps those out of Realtime and out of the cookie-based reports."""
        body = self.client.get(reverse("italiastadiaapp:home")).content.decode()
        self.assertIn("localStorage.getItem('cookie_consent')", body)
        self.assertIn("_cc==='accepted'?'granted':'denied'", body)
        # the restore must precede BOTH the consent default and the config call
        self.assertLess(body.index("getItem('cookie_consent')"),
                        body.index("gtag('consent','default'"))
        self.assertLess(body.index("gtag('consent','default'"),
                        body.index(f"gtag('config','{GID}')"))

    @override_settings(GOOGLE_ANALYTICS_ID=GID)
    def test_default_is_still_denied_for_a_first_time_visitor(self):
        """No stored choice must stay denied -- the restore is an upgrade path for
        people who already opted in, never a way to assume consent."""
        body = self.client.get(reverse("italiastadiaapp:home")).content.decode()
        self.assertIn("?'granted':'denied'", body)
        self.assertNotIn("'analytics_storage':'granted'", body)

    @override_settings(GOOGLE_ANALYTICS_ID="")
    def test_no_tag_when_id_unset(self):
        resp = self.client.get(reverse("italiastadiaapp:home"))
        self.assertNotIn("googletagmanager.com/gtag/js", resp.content.decode())

    @override_settings(GOOGLE_ANALYTICS_ID=GID)
    def test_not_injected_into_json(self):
        resp = self.client.get(reverse("italiastadiaapp:stadiums_geojson"))
        self.assertNotIn(b"googletagmanager.com/gtag/js", resp.content)


class CanonicalHostMiddlewareTests(TestCase):
    @override_settings(CANONICAL_HOST="www.stadiumsofeurope.com",
                       ALLOWED_HOSTS=["*"])
    def test_offhost_redirects_permanently(self):
        resp = self.client.get("/stadiums/?page=2",
                               HTTP_HOST="italianstadia-2.onrender.com")
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"],
                         "https://www.stadiumsofeurope.com/stadiums/?page=2")

    @override_settings(CANONICAL_HOST="www.stadiumsofeurope.com",
                       ALLOWED_HOSTS=["*"])
    def test_canonical_host_not_redirected(self):
        resp = self.client.get(reverse("italiastadiaapp:privacy"),
                               HTTP_HOST="www.stadiumsofeurope.com")
        self.assertEqual(resp.status_code, 200)

    @override_settings(CANONICAL_HOST="")
    def test_disabled_when_unset(self):
        resp = self.client.get(reverse("italiastadiaapp:privacy"))
        self.assertEqual(resp.status_code, 200)


class SeoTagTests(TestCase):
    def test_list_pages_have_canonical(self):
        for name in ("stadium_list", "team_list", "city_list", "home"):
            resp = self.client.get(reverse(f"italiastadiaapp:{name}"))
            self.assertContains(resp, 'rel="canonical"', msg_prefix=name)

    def test_city_list_query_variant_canonicalises_to_clean_url(self):
        resp = self.client.get(reverse("italiastadiaapp:city_list") + "?country=Italy")
        body = resp.content.decode()
        i = body.find('rel="canonical"')
        self.assertNotEqual(i, -1)
        self.assertNotIn("country=", body[i:i + 200])

    def test_sitemap_has_no_query_urls(self):
        resp = self.client.get("/sitemap.xml")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b"?country=", resp.content)


class LegacySlugRedirectTests(TestCase):
    def test_legacy_stadium_slug_redirects_permanently(self):
        from italiastadiaapp.models import City, Stadium
        city = City.objects.create(name="Reykjavik", country="Iceland")
        Stadium.objects.create(name="Lambhagavollurinn", slug="lambhagavollurinn",
                               city=city, latitude=64.1, longitude=-21.9)
        resp = self.client.get("/stadium/lambhagavollur/")
        self.assertEqual(resp.status_code, 301)
        self.assertTrue(resp["Location"].endswith("/stadium/lambhagavollurinn/"))

    def test_unknown_slug_still_404s(self):
        resp = self.client.get("/stadium/definitely-not-a-stadium/")
        self.assertEqual(resp.status_code, 404)


class BasemapAttributionTests(TestCase):
    """Tile providers require visible attribution on every rendered map."""

    def _text(self, **params):
        from italiastadiaapp.views import _source_text
        base = {"tiles": True, "style_key": "satellite"}
        base.update(params)
        return _source_text(base)

    def test_satellite_credits_esri(self):
        self.assertIn("Esri", self._text(style_key="satellite"))

    def test_dark_and_light_credit_osm_and_carto(self):
        for style in ("dark", "light"):
            txt = self._text(style_key=style)
            self.assertIn("OpenStreetMap", txt, style)
            self.assertIn("CARTO", txt, style)

    def test_topo_credits_osm(self):
        self.assertIn("OpenStreetMap", self._text(style_key="topo"))

    def test_always_credits_our_data_sources(self):
        self.assertIn("Wikipedia & Transfermarkt", self._text())

    def test_credits_wikimedia_for_crests(self):
        """Crests are sourced from Wikipedia/Commons and served from our own
        domain; Transfermarkt stays credited for the stadium and club data."""
        self.assertIn("Crests: Wikipedia & Wikimedia Commons", self._text())

    def test_no_tile_attribution_when_tiles_off(self):
        # solid background => no provider imagery shown => no provider credit
        txt = self._text(tiles=False)
        self.assertNotIn("Esri", txt)
        self.assertIn("Wikipedia & Transfermarkt", txt)
        txt2 = self._text(bg_color=(10, 10, 40, 255))
        self.assertNotIn("Esri", txt2)


class HiddenLeagueTests(TestCase):
    """A league whose coverage is partial is suppressed from site-facing lists,
    but its clubs and stadiums stay visible."""

    def setUp(self):
        from italiastadiaapp.models import City, Country, League, Stadium, Team
        self.country = Country.objects.create(name="Testland", code="TL")
        self.city = City.objects.create(name="Testville", country="Testland")
        self.top = League.objects.create(name="Test Prem", country=self.country,
                                         division_level=1)
        self.low = League.objects.create(name="Test Second", country=self.country,
                                         division_level=2, hidden=True)
        self.stadium = Stadium.objects.create(
            name="Relegated Park", city=self.city, capacity=9000,
            latitude=52.0, longitude=1.0)
        self.team = Team.objects.create(name="Dropped FC", league=self.low,
                                        stadium=self.stadium, city=self.city)

    def test_hidden_league_absent_from_country_hub(self):
        resp = self.client.get(
            reverse("italiastadiaapp:country_stats", args=["Testland"]))
        self.assertNotContains(resp, "Test Second")

    def test_visible_league_still_listed(self):
        from italiastadiaapp.models import Stadium, Team
        s = Stadium.objects.create(name="Top Park", city=self.city, capacity=20000,
                                   latitude=52.1, longitude=1.1)
        Team.objects.create(name="Top FC", league=self.top, stadium=s, city=self.city)
        resp = self.client.get(
            reverse("italiastadiaapp:country_stats", args=["Testland"]))
        self.assertContains(resp, "Test Prem")

    def test_clubs_of_hidden_league_are_not_deleted(self):
        from italiastadiaapp.models import Team
        self.assertTrue(Team.objects.filter(name="Dropped FC").exists())

    def test_hidden_league_absent_from_export_options(self):
        resp = self.client.get(reverse("italiastadiaapp:export_options"))
        self.assertNotIn(b"Test Second", resp.content)


class ExportCountryFilterTests(TestCase):
    """A country filter means that country's LEAGUE SYSTEM, not just its borders.

    FC Vaduz play in the Swiss Super League but their ground is in Liechtenstein,
    so filtering an export on the stadium's geographic country silently produced a
    'Switzerland' map missing one of the league's twelve clubs.
    """

    def setUp(self):
        from italiastadiaapp.models import City, Country, League, Stadium, Team
        swiss = Country.objects.create(name="Helvetia", code="HV")
        lg = League.objects.create(name="Helvetia Super League", country=swiss,
                                   division_level=1)
        home = City.objects.create(name="Berncity", country="Helvetia")
        abroad = City.objects.create(name="Smallstate", country="Microlandia")
        s1 = Stadium.objects.create(name="Home Park", city=home, capacity=30000,
                                    latitude=46.9, longitude=7.4)
        s2 = Stadium.objects.create(name="Abroad Park", city=abroad, capacity=6000,
                                    latitude=47.1, longitude=9.5)
        Team.objects.create(name="Home FC", league=lg, stadium=s1, city=home)
        Team.objects.create(name="Abroad FC", league=lg, stadium=s2, city=abroad)

    def _export(self, country):
        from italiastadiaapp.views import _get_export_stadiums
        return _get_export_stadiums({
            "country": country, "league": "", "ownership": "", "surface": "",
            "stadium_type": "", "tournament": "", "layer": "", "national": False,
            "national_only": False, "dev_status": "", "bid": "", "min_capacity": 0,
            "max_capacity": 0, "era": "", "color_by": "single", "tstatus": set(),
        })

    def test_country_export_includes_foreign_ground_in_that_league(self):
        names = {s["name"] for s in self._export("Helvetia")}
        self.assertIn("Home Park", names)
        self.assertIn("Abroad Park", names)      # the Vaduz case

    def test_country_export_excludes_unrelated_countries(self):
        self.assertEqual(self._export("Microlandia") and
                         {s["name"] for s in self._export("Microlandia")},
                         {"Abroad Park"})        # geographic match still works

    def test_no_duplicate_rows_from_the_join(self):
        rows = self._export("Helvetia")
        self.assertEqual(len(rows), len({s["name"] for s in rows}))


class IslandInsetTests(TestCase):
    """Far-flung island groups get their own inset instead of stretching the frame."""

    def _groups(self, pts, country="Portugal", **kw):
        """Helper points share one country: an outlier only counts as an island if
        it belongs to the SAME country as the main body (see the Turkey case below)."""
        from italiastadiaapp.views import _outlier_island_groups
        stadiums = [{"lat": la, "lon": lo, "name": n, "country": country}
                    for n, la, lo in pts]
        return _outlier_island_groups(stadiums, **kw)

    def test_portugal_islands_are_split_out(self):
        pts = [("Luz", 38.75, -9.18), ("Alvalade", 38.76, -9.16),
               ("Dragao", 41.16, -8.58), ("Braga", 41.56, -8.43),
               ("Madeira", 32.65, -16.91), ("Maritimo", 32.65, -16.93),
               ("Sao Miguel", 37.74, -25.66)]
        main, groups = self._groups(pts)
        self.assertEqual(len(main), 4)                      # mainland only
        self.assertEqual(len(groups), 2)                    # Madeira + Azores
        sizes = sorted(len(g) for g in groups)
        self.assertEqual(sizes, [1, 2])

    def test_spread_out_mainland_is_not_split(self):
        """A merely wide country must NOT be broken up - Barcelona is not an island."""
        pts = [("Madrid", 40.45, -3.68), ("Valencia", 39.47, -0.35),
               ("Barcelona", 41.38, 2.12), ("Sevilla", 37.38, -5.98),
               ("Bilbao", 43.26, -2.94)]
        main, groups = self._groups(pts)
        self.assertEqual(groups, [])
        self.assertEqual(len(main), 5)

    def test_too_few_stadiums_is_left_alone(self):
        main, groups = self._groups([("A", 40.0, -3.0), ("B", 32.0, -16.0)])
        self.assertEqual(groups, [])

    def test_group_cap_keeps_extras_on_the_main_map(self):
        pts = [("m1", 40.0, -3.0), ("m2", 40.1, -3.1), ("m3", 40.2, -3.2),
               ("i1", 32.0, -16.0), ("i2", 37.7, -25.6), ("i3", 28.1, -15.4)]
        main, groups = self._groups(pts, max_groups=2)
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(main) + sum(len(g) for g in groups), len(pts))

    def test_a_different_country_is_not_an_island(self):
        """Distance alone must not trigger an island box. On the Euro 2032 map
        Turkey sits ~10 degrees from Italy and was wrongly boxed as an island."""
        from italiastadiaapp.views import _outlier_island_groups
        pts = [{"lat": 45.5, "lon": 9.1, "name": "Meazza", "country": "Italy"},
               {"lat": 45.1, "lon": 7.6, "name": "Allianz", "country": "Italy"},
               {"lat": 41.9, "lon": 12.5, "name": "Olimpico", "country": "Italy"},
               {"lat": 41.0, "lon": 28.8, "name": "Ataturk", "country": "Turkey"},
               {"lat": 41.0, "lon": 29.0, "name": "RAMS", "country": "Turkey"},
               {"lat": 39.9, "lon": 32.8, "name": "Ankara", "country": "Turkey"}]
        main, groups = _outlier_island_groups(pts)
        self.assertEqual(groups, [])
        self.assertEqual(len(main), 6)


class ExportFunnelTrackingTests(TestCase):
    """The export funnel is the only thing on the site that takes money, so the
    GA4 wiring that measures it is guarded: a silent regression here means we go
    back to flying blind on whether anyone ever starts checkout."""

    def test_export_page_carries_the_analytics_config(self):
        resp = self.client.get(reverse("italiastadiaapp:export_page"))
        body = resp.content.decode()
        self.assertIn('id="exportAnalytics"', body)
        self.assertIn('data-step="view"', body)
        self.assertIn("js/export-analytics.js", body)

    def test_price_is_sent_in_euros_not_cents(self):
        """GA4 ecommerce `value` is in major units. Passing the Stripe cents
        amount would report every 50-cent sale as a 50-euro one."""
        from italiastadiaapp.views import EXPORT_PRICE_EUR
        body = self.client.get(reverse("italiastadiaapp:export_page")).content.decode()
        self.assertIn(f'data-price="{EXPORT_PRICE_EUR / 100:.2f}"', body)
        self.assertNotIn(f'data-price="{EXPORT_PRICE_EUR}"', body)

    def test_each_funnel_step_is_dispatched(self):
        """The template owns no analytics logic, it only dispatches these events.
        Renaming one without updating export-analytics.js breaks the funnel
        silently — nothing errors, the events just stop arriving."""
        body = self.client.get(reverse("italiastadiaapp:export_page")).content.decode()
        for event in ("export:preview", "export:checkout", "export:free"):
            self.assertIn(event, body)


class InsightsIndexTests(TestCase):
    def test_every_card_has_a_hero(self):
        """Cards without a rendered map used to collapse to a bare title block
        next to full-bleed image cards, which made the grid look broken."""
        from italiastadiaapp.views import _INSIGHTS
        body = self.client.get(reverse("italiastadiaapp:insights_index")).content.decode()
        with_image = [i for i in _INSIGHTS if i.get("image")]
        without = [i for i in _INSIGHTS if not i.get("image")]
        self.assertTrue(without, "test is meaningless if every insight has a map")
        # one gradient tile per image-less insight (+1 for the CSS rule itself)
        self.assertEqual(body.count("insight-hero-fallback"), len(without) + 1)
        self.assertEqual(body.count('class="insight-hero" loading'), len(with_image))
        for i in _INSIGHTS:
            self.assertIn(escape(i["title"]), body)  # titles carry & and '

    def test_card_heroes_are_thumbnails_not_the_full_maps(self):
        """The full hero PNGs are 1920x1080 / ~3 MB each and were being shipped
        into a ~300px card, which is what made /insights/ heavy enough to bounce."""
        from italiastadiaapp.views import _INSIGHTS
        for i in _INSIGHTS:
            if i.get("image"):
                self.assertTrue(i["image"].endswith("_card.jpg"), i["image"])


class ConsentBannerCoverageTests(TestCase):
    """Consent Mode defaults to denied, so a page without the banner can never be
    upgraded to cookie-based analytics. The banner used to live only in
    base_detail.html, which silently excluded the home page and the whole export
    funnel — i.e. every page that matters for revenue."""

    def test_banner_on_pages_that_do_not_extend_base_detail(self):
        for name in ("home", "export_page"):
            body = self.client.get(reverse(f"italiastadiaapp:{name}")).content.decode()
            self.assertIn('id="cookie-banner"', body, name)
            self.assertIn("js/consent.js", body, name)
            self.assertIn("cookie-accept", body, name)

    def test_banner_on_pages_that_do_extend_base_detail(self):
        body = self.client.get(reverse("italiastadiaapp:insights_index")).content.decode()
        self.assertIn('id="cookie-banner"', body)

    def test_never_injected_twice(self):
        """base_detail.html already renders one; a second would stack two fixed
        bars over each other and only the top one's buttons would work."""
        for name in ("home", "insights_index", "export_page", "privacy"):
            body = self.client.get(reverse(f"italiastadiaapp:{name}")).content.decode()
            self.assertEqual(body.count('id="cookie-banner"'), 1, name)
            self.assertEqual(body.count("js/consent.js"), 1, name)

    def test_not_injected_into_the_embeddable_map(self):
        """/embed/ is iframed into other people's pages, where consent is the host
        page's responsibility — our widget must not paint a banner over their site."""
        body = self.client.get(reverse("italiastadiaapp:embed_map")).content.decode()
        self.assertNotIn('id="cookie-banner"', body)

    def test_not_injected_into_json(self):
        resp = self.client.get(reverse("italiastadiaapp:stadiums_geojson"))
        self.assertNotIn(b"cookie-banner", resp.content)


class ConsentBannerProminenceTests(TestCase):
    def test_banner_styles_ship_with_the_banner(self):
        """The export funnel templates never load styles.css, so banner CSS kept in
        that file would arrive unstyled exactly where it matters most."""
        for name in ("export_page", "home", "insights_index"):
            body = self.client.get(reverse(f"italiastadiaapp:{name}")).content.decode()
            self.assertIn("#cookie-banner .cookie-card", body, name)
            self.assertIn("cookie-backdrop", body, name)

    def test_reject_is_as_prominent_as_accept(self):
        """EDPB: refusing must be as easy as accepting. Both buttons share the same
        class and flex basis, so neither can be quietly demoted to a faint link."""
        body = self.client.get(reverse("italiastadiaapp:home")).content.decode()
        self.assertIn('class="cookie-btn cookie-btn-reject"', body)
        self.assertIn('class="cookie-btn cookie-btn-accept"', body)
        self.assertIn(".cookie-btn{flex:1 1 0", body)

    def test_base_detail_no_longer_ships_its_own_copy(self):
        """One source of truth: the template copy was removed when the middleware
        took over, so the two can never drift apart."""
        from pathlib import Path
        from django.conf import settings
        tpl = (Path(settings.BASE_DIR) / "italiastadiaapp" / "templates"
               / "base_detail.html").read_text(encoding="utf-8")
        self.assertNotIn("cookie-banner", tpl)


class ExportDrawOrderTests(TestCase):
    """Where two grounds overlap on a map, the crest drawn LAST sits on top. That
    used to be raw insertion order: in Rotterdam it put Sparta over Feyenoord purely
    because Sparta's row was created later."""

    def setUp(self):
        from italiastadiaapp.models import City, Country, League, Stadium, Team
        c = Country.objects.create(name="Orderland", code="OL")
        self.lg = League.objects.create(name="Order League", country=c, division_level=1)
        self.city = City.objects.create(name="Ordertown", country="Orderland")
        # created small-first so insertion order is the OPPOSITE of the wanted order
        for name, cap, lat in [("Tiny Park", 4000, 50.0),
                               ("Huge Arena", 60000, 50.1),
                               ("Mid Stadium", 20000, 50.2)]:
            s = Stadium.objects.create(name=name, capacity=cap, city=self.city,
                                       latitude=lat, longitude=5.0)
            Team.objects.create(name=f"{name} FC", stadium=s, city=self.city, league=self.lg)

    def _order(self):
        from italiastadiaapp.views import _get_export_stadiums, _parse_export_params
        from django.test import RequestFactory
        params = _parse_export_params(RequestFactory().get("/", {"league": "Order League"}))
        return [s["name"] for s in _get_export_stadiums(params)]

    def test_biggest_ground_is_drawn_last_when_no_club_has_titles(self):
        self.assertEqual(self._order()[-1], "Huge Arena")

    def test_capacity_breaks_the_tie_at_zero_titles(self):
        self.assertEqual(self._order(), ["Tiny Park", "Mid Stadium", "Huge Arena"])

    def test_titles_outrank_capacity(self):
        """A decorated club at a small ground beats a bigger, title-less one."""
        from italiastadiaapp.models import Team
        t = Team.objects.get(name="Tiny Park FC")
        t.num_of_titles = 12
        t.save(update_fields=["num_of_titles"])
        self.assertEqual(self._order()[-1], "Tiny Park")

    def test_capacity_breaks_the_tie_between_equal_title_counts(self):
        from italiastadiaapp.models import Team
        for n in ("Tiny Park FC", "Huge Arena FC"):
            t = Team.objects.get(name=n)
            t.num_of_titles = 5
            t.save(update_fields=["num_of_titles"])
        order = self._order()
        self.assertEqual(order[-1], "Huge Arena")
        self.assertLess(order.index("Tiny Park"), order.index("Huge Arena"))

    def test_national_side_does_not_drag_a_clubs_ground_down(self):
        """National teams share grounds and carry no domestic league count, so
        counting them would rank a major club's stadium as title-less."""
        from italiastadiaapp.models import Stadium, Team
        s = Stadium.objects.get(name="Tiny Park")
        Team.objects.get(name="Tiny Park FC").__class__.objects.filter(
            name="Tiny Park FC").update(num_of_titles=12)
        Team.objects.create(name="Orderland NT", stadium=s, city=self.city,
                            league=self.lg, is_national=True, num_of_titles=0)
        self.assertEqual(self._order()[-1], "Tiny Park")

    def test_order_does_not_depend_on_insertion_order(self):
        """Re-saving a row must not change which crest wins the overlap."""
        from italiastadiaapp.models import Stadium
        before = self._order()
        s = Stadium.objects.get(name="Tiny Park")
        s.save()
        self.assertEqual(self._order(), before)


class BadgeFittingTests(TestCase):
    """Crests are pasted through a CIRCULAR mask. The old code took the top square
    of any taller-than-wide image, so the bottom of every shield crest was thrown
    away before the mask even ran -- a Reddit reader spotted it on the Eredivisie
    map. Nothing may be clipped now, whatever the source aspect ratio."""

    SIZE = 40

    @staticmethod
    def _furthest_opaque(im):
        """Distance from centre to the outermost opaque pixel."""
        import math
        a = im.getchannel("A")
        w, h = im.size
        px = a.load()
        cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
        return max((math.hypot(x - cx, y - cy)
                    for y in range(h) for x in range(w) if px[x, y] > 24),
                   default=0.0)

    def _fit(self, im):
        from italiastadiaapp.views import _fit_badge_in_circle
        return _fit_badge_in_circle(im, self.SIZE)

    def _assert_inside_circle(self, im, label):
        self.assertLessEqual(self._furthest_opaque(im), self.SIZE / 2.0, label)

    def test_tall_shield_is_not_beheaded(self):
        from PIL import Image, ImageDraw
        im = Image.new("RGBA", (100, 160), (0, 0, 0, 0))
        ImageDraw.Draw(im).polygon([(50, 0), (100, 30), (50, 159), (0, 30)],
                                   fill=(200, 30, 30, 255))
        out = self._fit(im)
        self._assert_inside_circle(out, "tall shield")
        # the tip must survive: bottom half of the badge cannot be empty
        bottom = out.crop((0, self.SIZE // 2, self.SIZE, self.SIZE)).getchannel("A")
        self.assertGreater(max(bottom.getdata()), 24, "shield tip was cropped away")

    def test_round_crest_fills_the_circle_without_being_trimmed(self):
        """The reader's specific complaint: even already-circular logos lost an edge."""
        from PIL import Image, ImageDraw
        im = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse([0, 0, 119, 119], fill=(30, 80, 200, 255))
        out = self._fit(im)
        self._assert_inside_circle(out, "round crest")
        # and it should still nearly fill the badge, not be shrunk to a dot
        self.assertGreater(self._furthest_opaque(out), self.SIZE / 2.0 - 2.0)

    def test_wide_wordmark_keeps_its_aspect_ratio(self):
        from PIL import Image, ImageDraw
        im = Image.new("RGBA", (200, 60), (0, 0, 0, 0))
        ImageDraw.Draw(im).rectangle([0, 0, 199, 59], fill=(20, 160, 90, 255))
        out = self._fit(im)
        self._assert_inside_circle(out, "wide wordmark")
        bbox = out.getchannel("A").getbbox()
        ratio = (bbox[2] - bbox[0]) / (bbox[3] - bbox[1])
        self.assertGreater(ratio, 2.0, "wide crest was squashed to square")

    def test_transparent_padding_does_not_shrink_the_crest(self):
        """A crest centred in a large transparent canvas must not be scaled down to
        fit that empty margin."""
        from PIL import Image, ImageDraw
        small = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        ImageDraw.Draw(small).ellipse([80, 80, 119, 119], fill=(200, 30, 30, 255))
        out = self._fit(small)
        self.assertGreater(self._furthest_opaque(out), self.SIZE / 2.0 - 2.0)

    def test_cache_key_changed_with_the_fitting_algorithm(self):
        """Stale disk-cached badges cropped under the old rules must not be reused."""
        import inspect
        from italiastadiaapp import views
        self.assertIn("_v2", inspect.getsource(views._fetch_badge_image))


class InsetSizeTests(TestCase):
    """The detail inset was a fixed 24% of map width. Everything inside it -- badge
    radius, both fonts -- is derived from that width, so the Istanbul cluster's
    labels were unreadably cramped. Size is now user-selectable."""

    def _frac(self, **q):
        from django.test import RequestFactory
        from italiastadiaapp.views import _parse_export_params
        return _parse_export_params(RequestFactory().get("/", q))["inset_frac"]

    def test_default_is_medium_not_the_old_fixed_value(self):
        self.assertEqual(self._frac(), 0.30)

    def test_sizes_map_to_increasing_fractions(self):
        s, m, l = self._frac(inset_size="s"), self._frac(inset_size="m"), self._frac(inset_size="l")
        self.assertLess(s, m)
        self.assertLess(m, l)

    def test_unknown_value_falls_back_to_medium(self):
        self.assertEqual(self._frac(inset_size="enormous"), 0.30)
        self.assertEqual(self._frac(inset_size=""), 0.30)

    def test_case_and_whitespace_tolerant(self):
        self.assertEqual(self._frac(inset_size=" L "), self._frac(inset_size="l"))

    def test_survives_the_paid_checkout_allowlist(self):
        """Filters are re-read from the stored JSON at download time; a key missing
        from the allowlist would silently reset to default on the paid export."""
        import inspect
        from italiastadiaapp import views
        self.assertIn('"inset_size"', inspect.getsource(views.export_checkout))


class InsetLabelLayoutTests(TestCase):
    """Inset labels used to run into each other: width was guessed from character
    count, nothing wrapped, and a full column clamped every remaining pill to the
    same y. The Istanbul box (6 grounds, names like 'Turka Araç Muayene Kocaeli
    Stadyumu') collided every time."""

    def _draw(self):
        from PIL import Image, ImageDraw
        return ImageDraw.Draw(Image.new("RGBA", (400, 400)))

    def _font(self, size=14):
        from PIL import ImageFont
        try:
            return ImageFont.truetype("arialbd.ttf", size)
        except Exception:
            self.skipTest("Arial not available on this platform")

    def test_wrap_never_exceeds_the_limit(self):
        from italiastadiaapp.views import _wrap_text
        d, f = self._draw(), self._font()
        rows = _wrap_text(d, "Chobani Stadyumu FB Şükrü Saracoğlu Spor Kompleksi", f, 120)
        self.assertGreater(len(rows), 1, "long name was not wrapped at all")
        for _line, w, _h in rows:
            self.assertLessEqual(w, 120)

    def test_wrap_keeps_every_word(self):
        from italiastadiaapp.views import _wrap_text
        text = "Turka Araç Muayene Kocaeli Stadyumu"
        rows = _wrap_text(self._draw(), text, self._font(), 100)
        self.assertEqual(" ".join(r[0] for r in rows).split(), text.split())

    def test_single_unbreakable_word_still_returned(self):
        """A word wider than the limit must not vanish."""
        from italiastadiaapp.views import _wrap_text
        rows = _wrap_text(self._draw(), "Başakşehiristanbulspor", self._font(), 10)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0][0])

    def test_measure_uses_real_metrics_not_character_count(self):
        from italiastadiaapp.views import _measure_text
        d, f = self._draw(), self._font()
        narrow, _ = _measure_text(d, "lllll", f)
        wide, _ = _measure_text(d, "WWWWW", f)
        self.assertLess(narrow, wide,
                        "same length, different width — char-count estimates cannot see this")

    def test_main_engine_and_inset_share_one_implementation(self):
        """The helpers were closures inside the main label engine, which is why the
        inset had its own (worse) copy."""
        import inspect
        from italiastadiaapp import views
        # both label layouts call the module-level helpers ...
        self.assertIn("_wrap_text(", inspect.getsource(views._draw_inset))
        self.assertIn("_wrap_text(", inspect.getsource(views._draw_dots_and_labels))
        # ... and the inset no longer estimates width from character count
        self.assertNotIn("len(label2) * font_s.size", inspect.getsource(views._draw_inset))


class AutoInsetClusterTests(TestCase):
    """The magnifier picks the knot of grounds whose badges overlap. Severity is
    scored as (-closest_squared_px, overlapping_pairs), so a real cluster always
    scores NEGATIVE -- an isolated ground returning (0, 0) beat every cluster in
    max(), the function bailed, and no inset was ever drawn."""

    W = H = 1000
    BBOX = (0.0, 50.0, 10.0, 55.0)      # lon0, lat0, lon1, lat1

    def _s(self, name, lon, lat):
        return {"name": name, "team_name": name, "lon": lon, "lat": lat}

    def _cluster(self, stadiums, badge_r=13):
        from italiastadiaapp.views import _auto_inset_cluster
        return _auto_inset_cluster(stadiums, bbox=self.BBOX, W=self.W, H=self.H,
                                   badge_r=badge_r)

    def _spread(self):
        """Four grounds far enough apart that none of their badges touch."""
        return [self._s("A", 0.5, 50.3), self._s("B", 4.0, 51.5),
                self._s("C", 8.0, 53.0), self._s("D", 9.5, 54.5)]

    def test_a_tight_pair_is_found_among_isolated_grounds(self):
        got = self._cluster(self._spread() + [self._s("X", 2.0, 52.0),
                                              self._s("Y", 2.01, 52.005)])
        self.assertEqual({s["name"] for s in got}, {"X", "Y"})

    def test_no_overlap_means_no_inset(self):
        self.assertEqual(self._cluster(self._spread()), [])

    def test_the_tighter_knot_wins_over_the_looser_one(self):
        """Tightness leads: a pair drawn exactly on top of each other needs the
        magnifier more than a looser group whose badges are still readable."""
        loose = [self._s("L1", 6.00, 52.0), self._s("L2", 6.13, 52.0),
                 self._s("L3", 6.26, 52.0)]
        tight = [self._s("T1", 2.00, 53.0), self._s("T2", 2.002, 53.0)]
        got = self._cluster(self._spread() + loose + tight)
        self.assertEqual({s["name"] for s in got}, {"T1", "T2"})

    def test_a_distant_city_is_not_dragged_in(self):
        """Kocaelispor sits ~80 km from Istanbul: far enough that its badge never
        touches, so the inset must stay at metropolitan scale."""
        metro = [self._s("M1", 2.00, 52.00), self._s("M2", 2.02, 52.01),
                 self._s("M3", 2.03, 51.99)]
        far = self._s("Far", 3.2, 52.0)
        got = self._cluster(self._spread() + metro + [far])
        self.assertEqual({s["name"] for s in got}, {"M1", "M2", "M3"})


class FontFallbackTests(TestCase):
    """Turkish/Romanian diacritics rendered as mojibake in the inset on production
    while the main map was fine. The inset called ImageFont.truetype("arialbd.ttf")
    directly -- a Windows-only filename. On Render that raises and drops to PIL's
    default bitmap font, which has no glyphs for s-cedilla or dotted-I. The bug is
    INVISIBLE on Windows, where Arial exists, so it needs a static guard."""

    def test_no_render_code_names_a_windows_only_font(self):
        import re
        from pathlib import Path
        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "italiastadiaapp" / "views.py").read_text(
            encoding="utf-8")
        # strip comments so the explanatory note about the old bug doesn't match
        code = "\n".join(l.split("#")[0] for l in src.splitlines())
        bad = re.findall(r'ImageFont\.truetype\(\s*["\']([Aa]rial[^"\']*)["\']', code)
        self.assertEqual(bad, [], f"use _load_font() instead of bare Arial: {bad}")

    def test_load_font_offers_linux_fallbacks(self):
        """_load_font is the only path with DejaVu/Liberation fallbacks, which is
        why the main map's labels survived and the inset's did not."""
        import inspect
        from italiastadiaapp import views
        src = inspect.getsource(views._load_font)
        self.assertIn("DejaVuSans", src)
        self.assertIn("Liberation", src)

    def test_turkish_and_romanian_glyphs_are_present(self):
        """Guards the actual symptom. Comparing rendered WIDTHS proves nothing --
        s-cedilla and plain s share an advance width in Arial -- so this compares
        each glyph against a codepoint no font defines (private-use U+E000). A
        character the font lacks falls back to .notdef and renders identically to
        it; a character it has does not."""
        from PIL import Image, ImageDraw
        from italiastadiaapp.views import _load_font
        font = _load_font(bold=True, size=28)

        def pixels(ch):
            img = Image.new("L", (60, 50), 0)
            ImageDraw.Draw(img).text((4, 4), ch, font=font, fill=255)
            return img.tobytes()

        notdef = pixels("")
        for ch in "şğİıŞĞ" + "țțăîâȚĂÎÂ":
            self.assertNotEqual(pixels(ch), notdef,
                                f"font has no glyph for {ch!r} - it will render as a box")


class BadgeFetchRetryTests(TestCase):
    """Transfermarkt's CDN 503s individual crests at random. Without a retry, one
    unlucky request drops that club's badge and the map draws a bare dot — which
    is only ever spotted by eye, after publishing. Petrolul Ploiesti disappeared
    from a Romania map exactly this way while the URL served fine seconds later."""

    def setUp(self):
        import shutil, os
        from italiastadiaapp import views
        # a warm disk cache would satisfy the fetch before any HTTP happens
        shutil.rmtree(views._BADGE_DISK_CACHE, ignore_errors=True)
        os.makedirs(views._BADGE_DISK_CACHE, exist_ok=True)

    @staticmethod
    def _png_bytes():
        """Must exceed the 100-byte floor that marks a soft-blocked empty 200.
        An 8x8 PNG is only 79 bytes and would itself be read as blocked."""
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGBA", (48, 48), (255, 0, 0, 255)).save(buf, format="PNG")
        assert len(buf.getvalue()) >= 100
        return buf.getvalue()

    def _run(self, statuses):
        """Serve `statuses` in order; returns (image_or_None, attempts_made)."""
        from unittest import mock
        from italiastadiaapp import views
        calls = {"n": 0}

        class Resp:
            def __init__(self, code, body):
                self.status_code, self.content = code, body

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise Exception(f"HTTP {self.status_code}")

        def fake_get(url, **kw):
            code = statuses[min(calls["n"], len(statuses) - 1)]
            calls["n"] += 1
            return Resp(code, self._png_bytes() if code == 200 else b"")

        with mock.patch.object(views._requests, "get", side_effect=fake_get), \
                mock.patch.object(views._time, "sleep", lambda *_: None):
            img = views._fetch_badge_image("https://tmssl.example/x.png", 26)
        return img, calls["n"]

    def test_transient_503_then_success_still_yields_a_badge(self):
        img, attempts = self._run([503, 200])
        self.assertIsNotNone(img, "a retryable 503 must not lose the badge")
        self.assertEqual(attempts, 2)

    def test_rate_limit_is_retried_too(self):
        img, attempts = self._run([429, 200])
        self.assertIsNotNone(img)
        self.assertEqual(attempts, 2)

    def test_persistent_503_gives_up_without_hanging_the_render(self):
        img, attempts = self._run([503])
        self.assertIsNone(img)
        self.assertEqual(attempts, 3, "must stop at 3 attempts, not loop")

    def test_404_is_not_retried(self):
        """A missing file will never appear; retrying only burns the badge budget."""
        img, attempts = self._run([404])
        self.assertIsNone(img)
        self.assertEqual(attempts, 1)

    def test_empty_200_is_treated_as_failure_and_retried(self):
        """Transfermarkt soft-blocks with 200 + zero bytes rather than an error
        status, so status alone says healthy while the badge silently vanishes."""
        from unittest import mock
        from italiastadiaapp import views
        calls = {"n": 0}

        class Resp:
            def __init__(self, body):
                self.status_code, self.content = 200, body

            def raise_for_status(self):
                pass

        bodies = [b"", self._png_bytes()]

        def fake_get(url, **kw):
            b = bodies[min(calls["n"], len(bodies) - 1)]
            calls["n"] += 1
            return Resp(b)

        with mock.patch.object(views._requests, "get", side_effect=fake_get),                 mock.patch.object(views._time, "sleep", lambda *_: None):
            img = views._fetch_badge_image("https://tmssl.example/x.png", 26)
        self.assertIsNotNone(img, "empty 200 must be retried, not accepted")
        self.assertEqual(calls["n"], 2)

    def test_persistent_empty_200_returns_none_not_a_broken_image(self):
        from unittest import mock
        from italiastadiaapp import views

        class Resp:
            status_code, content = 200, b""

            def raise_for_status(self):
                pass

        with mock.patch.object(views._requests, "get", side_effect=lambda *a, **k: Resp()),                 mock.patch.object(views._time, "sleep", lambda *_: None):
            self.assertIsNone(views._fetch_badge_image("https://tmssl.example/x.png", 26))

    def test_transfermarkt_host_is_capped_to_one_concurrent_fetch(self):
        """8 parallel workers against TM's CDN returned one badge out of twelve."""
        from italiastadiaapp import views
        tm = views._badge_host_semaphore("https://tmssl.akamaized.net/a.png")
        wm = views._badge_host_semaphore("https://upload.wikimedia.org/b.svg")
        self.assertEqual(tm._value, 1)
        self.assertGreater(wm._value, 1)


class CrestFileTypeTests(TestCase):
    """A club article is full of files named after the club that are not crests.
    An earlier crest migration wrote a golf-tournament photo as Eintracht
    Frankfurt's badge, graffiti as Gornik Zabrze's, a 1960 team photo as
    Newcastle's, and a pronunciation recording as Augsburg's -- 109 clubs got
    photographs. Only svg/png may be stored as a crest."""

    ALLOWED = (".svg", ".png")

    def test_no_stored_crest_is_a_photo_or_audio_file(self):
        from italiastadiaapp.models import Team
        bad = []
        for t in Team.objects.exclude(image_url="").exclude(image_url__isnull=True):
            u = t.image_url.split("?")[0].lower()
            if not u.endswith(self.ALLOWED):
                bad.append((t.name, u.rsplit("/", 1)[-1]))
        self.assertEqual(bad, [], f"non-crest files stored as crests: {bad[:8]}")

    def test_picker_rejects_a_photo_named_after_the_club(self):
        from italiastadiaapp.management.commands.refresh_dead_crests import Command
        pick = Command._pick_article_image
        club = "Eintracht Frankfurt"
        self.assertIsNone(pick(["File:Eintracht Frankfurt Golf Open 8875.jpg"], club))
        self.assertIsNone(pick(["File:De-Eintracht Frankfurt.ogg"], club))
        self.assertIsNone(pick(["File:Eintracht Frankfurt 1960.jpg"], club))

    def test_picker_accepts_a_real_logo(self):
        from italiastadiaapp.management.commands.refresh_dead_crests import Command
        pick = Command._pick_article_image
        self.assertEqual(pick(["File:Eintracht Frankfurt Logo.svg"], "Eintracht Frankfurt"),
                         "File:Eintracht Frankfurt Logo.svg")
        # club-named SVG with no keyword: the Corvinul case
        self.assertEqual(pick(["File:FC Corvinul Hunedoara.svg"], "FC Corvinul Hunedoara"),
                         "File:FC Corvinul Hunedoara.svg")

    def test_keyword_logo_beats_a_club_named_svg(self):
        from italiastadiaapp.management.commands.refresh_dead_crests import Command
        got = Command._pick_article_image(
            ["File:FC Example.svg", "File:FC Example logo.svg"], "FC Example")
        self.assertEqual(got, "File:FC Example logo.svg")


class LocalCrestTests(TestCase):
    """Crests are committed to static/crests/ so a render makes no network call
    for badges. Transfermarkt soft-blocked us and Wikimedia throttled the
    replacement; both turned badges into bare dots on already-published maps."""

    def setUp(self):
        from italiastadiaapp.models import City, Country, League, Stadium, Team
        c = Country.objects.create(name="Crestland", code="CL")
        self.lg = League.objects.create(name="Crest League", country=c,
                                        division_level=1)
        self.city = City.objects.create(name="Cresttown", country="Crestland")
        self.stadium = Stadium.objects.create(name="Crest Park", city=self.city,
                                              capacity=1000, latitude=50.0,
                                              longitude=5.0)
        self.team = Team.objects.create(name="Crest FC", stadium=self.stadium,
                                        city=self.city, league=self.lg,
                                        image_url="https://example.invalid/x.png")

    def _write_crest(self, fname):
        import os
        from PIL import Image
        from italiastadiaapp.views import _CREST_DIR, _BADGE_FETCH_SIZE
        os.makedirs(_CREST_DIR, exist_ok=True)
        path = os.path.join(_CREST_DIR, fname)
        Image.new("RGBA", (_BADGE_FETCH_SIZE, _BADGE_FETCH_SIZE),
                  (10, 200, 90, 255)).save(path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def _prefetch(self, size=26):
        from italiastadiaapp.views import _prefetch_badges
        return _prefetch_badges([{
            "name": self.stadium.name,
            "teams": [{"name": self.team.name, "image_url": self.team.image_url,
                       "crest_file": self.team.crest_file}],
        }], size=size)

    def test_render_needs_no_network_when_the_crest_is_local(self):
        from unittest import mock
        from italiastadiaapp import views
        self._write_crest("crest-fc-test.png")
        self.team.crest_file = "crest-fc-test.png"
        self.team.save(update_fields=["crest_file"])
        with mock.patch.object(views._requests, "get",
                               side_effect=AssertionError("network was used")):
            got = self._prefetch()
        self.assertIn(self.stadium.name, got)
        self.assertEqual(got[self.stadium.name].size, (26, 26))

    def test_falls_back_to_the_url_when_no_local_file(self):
        """Mid-migration a club may have image_url but no crest_file yet."""
        from unittest import mock
        from italiastadiaapp import views
        calls = {"n": 0}

        def fake(*a, **k):
            calls["n"] += 1
            raise RuntimeError("offline")

        with mock.patch.object(views._requests, "get", side_effect=fake):
            self._prefetch()
        self.assertGreater(calls["n"], 0, "must still try the remote URL")

    def test_a_missing_local_file_does_not_break_the_render(self):
        """crest_file pointing at a deleted file must fall back, not crash."""
        from unittest import mock
        from italiastadiaapp import views
        self.team.crest_file = "definitely-not-there.png"
        self.team.save(update_fields=["crest_file"])
        with mock.patch.object(views._requests, "get",
                               side_effect=RuntimeError("offline")):
            self.assertEqual(self._prefetch(), {})

    def test_local_crest_is_scaled_to_the_caller_size(self):
        """The map and the inset ask for different sizes off ONE stored file."""
        self._write_crest("crest-fc-test2.png")
        self.team.crest_file = "crest-fc-test2.png"
        self.team.save(update_fields=["crest_file"])
        self.assertEqual(self._prefetch(26)[self.stadium.name].size, (26, 26))
        self.assertEqual(self._prefetch(40)[self.stadium.name].size, (40, 40))

    def test_basename_only_no_path_traversal(self):
        """crest_file is a filename, not a path; a traversal attempt resolves
        inside the crest directory and simply misses."""
        from italiastadiaapp.views import _local_crest
        self.assertIsNone(_local_crest("../../settings.py"))


class ExportSizeConsistencyTests(TestCase):
    """The paid download must differ from the free one ONLY by the logo and the
    watermark. It did not: map_export caps fhd to 1280x720 while the paid path
    renders the full 1920x1080, and label/badge sizes were absolute pixels, so a
    16 px label was a third smaller on the file people had paid for."""

    def _params(self, size_key, **over):
        from django.test import RequestFactory
        from italiastadiaapp.views import _parse_export_params
        q = {"league": "X", "label_size": "16", "badge_size": "13",
             "size_key": size_key}
        q.update(over)
        return _parse_export_params(RequestFactory().get("/", q))

    def _scaled(self, p):
        """What _compose_export_image derives for this canvas."""
        from italiastadiaapp.views import _REFERENCE_W
        k = p["W"] / float(_REFERENCE_W)
        return (max(8, round(p["label_size"] * k)), max(6, round(p["badge_size"] * k)))

    def _assert_consistent(self, values, what):
        """Within 5%. Sizes are rounded to whole pixels -- 13 * 1.5 = 19.5 becomes
        20 -- so exact equality is not achievable and not the point; the point is
        that nothing is a THIRD smaller, which is what the bug produced."""
        lo, hi = min(values), max(values)
        self.assertLessEqual((hi - lo) / hi, 0.05,
                             f"{what} varies too much across sizes: {values}")

    def test_label_is_the_same_fraction_of_the_canvas_at_every_size(self):
        rel = [self._scaled(self._params(k))[0] / self._params(k)["H"]
               for k in ("hd", "fhd", "4k")]
        self._assert_consistent(rel, "label/height")

    def test_badge_is_the_same_fraction_of_the_canvas_at_every_size(self):
        rel = [self._scaled(self._params(k))[1] / self._params(k)["H"]
               for k in ("hd", "fhd", "4k")]
        self._assert_consistent(rel, "badge/height")

    def test_the_old_bug_would_fail_these_assertions(self):
        """Guard the guard: without scaling, a 16 px label on 720 vs 1080 is a 33%
        difference, so the tolerance above is not so loose it accepts the bug."""
        unscaled = [16 / 720, 16 / 1080]
        with self.assertRaises(AssertionError):
            self._assert_consistent(unscaled, "unscaled label/height")

    def test_free_cap_and_paid_full_size_match_proportionally(self):
        """map_export caps fhd to HD; the paid path keeps fhd. Same map either way."""
        free = self._params("fhd")
        free["W"], free["H"] = 1280, 720          # the cap map_export applies
        paid = self._params("fhd")
        self.assertNotEqual(free["W"], paid["W"], "test assumes the sizes differ")
        self.assertAlmostEqual(self._scaled(free)[0] / free["H"],
                               self._scaled(paid)[0] / paid["H"], places=3)
        self.assertAlmostEqual(self._scaled(free)[1] / free["H"],
                               self._scaled(paid)[1] / paid["H"], places=3)

    def test_reference_width_is_the_authoring_size(self):
        from italiastadiaapp.views import _REFERENCE_W, _EXPORT_SIZES
        self.assertEqual(_REFERENCE_W, _EXPORT_SIZES["hd"][0])


class InsetGeometryScalesTests(TestCase):
    """The inset must occupy the same fraction of the canvas at any resolution.
    Absolute margins and floors made it proportionally bigger on a small canvas,
    which shifted the corner scoring and put the detail box in a DIFFERENT CORNER
    on the free and paid exports of one configuration."""

    def _layout(self, W, H):
        from italiastadiaapp.views import _inset_layout
        pts = [{"name": "a", "lat": 41.40, "lon": 2.15},
               {"name": "b", "lat": 41.44, "lon": 2.19},
               {"name": "c", "lat": 41.36, "lon": 2.11}]
        return _inset_layout(pts, W, H, main_bbox=(-9.0, 36.0, 4.0, 44.0))

    def test_inset_occupies_the_same_fraction_at_hd_and_fhd(self):
        hd, fhd = self._layout(1280, 720), self._layout(1920, 1080)
        for key, div_w in (("IW", True), ("IH", False)):
            a = hd[key] / (1280 if div_w else 720)
            b = fhd[key] / (1920 if div_w else 1080)
            self.assertAlmostEqual(a, b, places=2, msg=key)

    def test_inset_lands_in_the_same_corner_at_hd_and_fhd(self):
        hd, fhd = self._layout(1280, 720), self._layout(1920, 1080)
        self.assertAlmostEqual(hd["ix0"] / 1280, fhd["ix0"] / 1920, places=2)
        self.assertAlmostEqual(hd["iy0"] / 720, fhd["iy0"] / 1080, places=2)
