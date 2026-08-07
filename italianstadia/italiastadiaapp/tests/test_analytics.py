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

    def test_biggest_ground_is_drawn_last(self):
        self.assertEqual(self._order()[-1], "Huge Arena")

    def test_order_is_ascending_by_capacity(self):
        self.assertEqual(self._order(), ["Tiny Park", "Mid Stadium", "Huge Arena"])

    def test_order_does_not_depend_on_insertion_order(self):
        """Re-saving a row must not change which crest wins the overlap."""
        from italiastadiaapp.models import Stadium
        before = self._order()
        s = Stadium.objects.get(name="Tiny Park")
        s.save()
        self.assertEqual(self._order(), before)
