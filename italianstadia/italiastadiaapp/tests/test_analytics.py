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
