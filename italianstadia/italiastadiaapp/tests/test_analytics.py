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
