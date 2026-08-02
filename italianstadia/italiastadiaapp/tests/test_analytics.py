"""GoogleAnalyticsMiddleware: GA4 tag injected on every HTML page when the id is set."""
from django.test import TestCase, override_settings
from django.urls import reverse

GID = "G-TEST123456"


class GoogleAnalyticsMiddlewareTests(TestCase):
    @override_settings(GOOGLE_ANALYTICS_ID=GID)
    def test_tag_injected_when_id_set(self):
        resp = self.client.get(reverse("italiastadiaapp:home"))
        body = resp.content.decode()
        self.assertIn(f"gtag/js?id={GID}", body)
        self.assertIn(f"gtag('config','{GID}')", body)
        # Consent Mode v2: defaults to denied (cookieless) until the banner grants it
        self.assertIn("gtag('consent','default'", body)
        self.assertIn("'analytics_storage':'denied'", body)
        # injected inside <head>, and exactly once
        self.assertEqual(body.count("googletagmanager.com/gtag/js"), 1)
        self.assertLess(body.index("gtag/js"), body.index("</head>"))

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
