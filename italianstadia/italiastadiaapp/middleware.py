"""Site-wide middleware."""
import re

from django.conf import settings

# Match the first opening <head ...> tag.
_HEAD_RE = re.compile(rb"(<head[^>]*>)", re.IGNORECASE)


class GoogleAnalyticsMiddleware:
    """Inject the GA4 gtag.js snippet into the <head> of every HTML response.

    Single source of truth: the site has ~15 templates with their own <head> (not all
    extend one base), so a per-template include would silently miss pages and every new
    one. Injecting here guarantees the tag is on EVERY page. No-ops when
    GOOGLE_ANALYTICS_ID is unset (local dev) or the response isn't HTML.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _build(gid):
        # Consent Mode v2: default everything to DENIED so GA runs cookieless until the
        # visitor clicks "Accept all" (consent.js then calls gtag('consent','update',…)).
        # This keeps the tag site-wide while honouring the cookie banner's opt-in promise.
        return (
            f'<script async src="https://www.googletagmanager.com/gtag/js?id={gid}"></script>'
            f'<script>window.dataLayer=window.dataLayer||[];'
            f'function gtag(){{dataLayer.push(arguments);}}'
            f"gtag('consent','default',{{'ad_storage':'denied','analytics_storage':'denied',"
            f"'ad_user_data':'denied','ad_personalization':'denied'}});"
            f"gtag('js',new Date());gtag('config','{gid}');</script>"
        ).encode("utf-8")

    def __call__(self, request):
        response = self.get_response(request)
        gid = getattr(settings, "GOOGLE_ANALYTICS_ID", "")
        if not gid or getattr(response, "streaming", False):
            return response
        if "text/html" not in response.get("Content-Type", ""):
            return response
        content = response.content
        # Idempotent: never inject twice.
        if b"googletagmanager.com/gtag/js" in content:
            return response
        new, n = _HEAD_RE.subn(rb"\1" + self._build(gid), content, count=1)
        if n:
            response.content = new
            if response.has_header("Content-Length"):
                response["Content-Length"] = str(len(new))
        return response
