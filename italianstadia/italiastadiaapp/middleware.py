"""Site-wide middleware."""
import re

from django.conf import settings
from django.http import HttpResponsePermanentRedirect

# Match the first opening <head ...> tag.
_HEAD_RE = re.compile(rb"(<head[^>]*>)", re.IGNORECASE)
# Match the LAST closing </body> tag.
_BODY_RE = re.compile(rb"(</body>)(?!.*</body>)", re.IGNORECASE | re.DOTALL)


class CanonicalHostMiddleware:
    """301-redirect every request on a non-canonical host to CANONICAL_HOST.

    The Render fallback domain (italianstadia-2.onrender.com) serves the site as a
    full 200 duplicate — Google crawled it and filed hundreds of pages as
    duplicates/alternates of stadiumsofeurope.com. A permanent redirect consolidates
    all hosts onto the canonical one. No-ops when CANONICAL_HOST is unset (local dev)
    or the request is already on it.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        canonical = getattr(settings, "CANONICAL_HOST", "")
        if canonical:
            host = request.get_host().partition(":")[0]
            if host not in (canonical, "localhost", "127.0.0.1", "testserver"):
                return HttpResponsePermanentRedirect(
                    f"https://{canonical}{request.get_full_path()}")
        return self.get_response(request)


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
        #
        # A RETURNING visitor's stored choice must be restored HERE, synchronously,
        # before gtag('config') fires page_view. consent.js runs its update from a
        # DOMContentLoaded handler at the end of the body, which is far too late: the
        # page_view (and the export funnel's view_item) had already gone out tagged
        # gcs=G100 (denied), and GA4 keeps denied hits out of Realtime and out of the
        # cookie-based reports. The effect was that someone who accepted cookies months
        # ago still had every page load counted as consent-denied. Nothing loaded at the
        # bottom of the page can beat a config call in the head, so the restore lives in
        # the snippet itself. consent.js still owns first-time choices and the banner.
        return (
            f'<script async src="https://www.googletagmanager.com/gtag/js?id={gid}"></script>'
            f'<script>window.dataLayer=window.dataLayer||[];'
            f'function gtag(){{dataLayer.push(arguments);}}'
            f"var _cc=null;try{{_cc=localStorage.getItem('cookie_consent');}}catch(e){{}}"
            f"var _cs=_cc==='accepted'?'granted':'denied';"
            f"gtag('consent','default',{{'ad_storage':_cs,'analytics_storage':_cs,"
            f"'ad_user_data':_cs,'ad_personalization':_cs}});"
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


class ConsentBannerMiddleware:
    """Inject the cookie-consent banner + consent.js into every HTML page.

    Same problem, same fix as GoogleAnalyticsMiddleware: the banner lived only in
    base_detail.html, so every template with its own <body> silently had none —
    including the HOME PAGE and /export/, the two pages that matter most. With
    Consent Mode defaulting to 'denied', a page with no banner gives the visitor no
    way to grant consent, so those sessions stayed permanently cookieless and AdSense
    never loaded there.

    Skipped for /embed/ — that view is designed to be iframed into other people's
    sites, where a consent banner belongs to the host page, not to our widget.

    Idempotent: pages that already render the banner (base_detail.html children) are
    left untouched, so there is never a second one.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _build():
        from django.templatetags.static import static
        from django.urls import reverse
        return (
            '<script src="%s"></script>'
            '<div id="cookie-banner" class="d-none position-fixed bottom-0 start-0 '
            'end-0 bg-dark text-white p-3 shadow-lg" style="z-index:9999">'
            '<div class="container d-flex flex-column flex-md-row align-items-md-center '
            'justify-content-between gap-2">'
            '<p class="mb-0 small">We use cookies to serve ads and analyse traffic. '
            'See our <a href="%s" class="text-warning">Privacy Policy</a>.</p>'
            '<div class="d-flex gap-2 flex-shrink-0">'
            '<button id="cookie-reject" class="btn btn-outline-light btn-sm">'
            'Reject non-essential</button>'
            '<button id="cookie-accept" class="btn btn-warning btn-sm fw-semibold">'
            'Accept all</button>'
            '</div></div></div>'
        ) % (static("js/consent.js"), reverse("italiastadiaapp:privacy"))

    def __call__(self, request):
        response = self.get_response(request)
        if getattr(response, "streaming", False):
            return response
        if "text/html" not in response.get("Content-Type", ""):
            return response
        if request.path.startswith("/embed/"):
            return response
        content = response.content
        if b'id="cookie-banner"' in content:   # template already renders it
            return response
        new, n = _BODY_RE.subn(self._build().encode("utf-8") + rb"\1", content, count=1)
        if n:
            response.content = new
            if response.has_header("Content-Length"):
                response["Content-Length"] = str(len(new))
        return response
