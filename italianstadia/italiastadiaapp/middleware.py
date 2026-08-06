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
        # A thin bar at the foot of the page was being ignored, and an ignored banner
        # means consent stays DENIED: those visitors are invisible in GA4 and AdSense
        # never loads for them. The dimmed backdrop makes it a deliberate choice
        # instead of page furniture.
        #
        # Both buttons are the SAME size, weight and visual prominence on purpose.
        # Nudging people toward "Accept" would raise the consent rate, but the EDPB
        # requires refusing to be as easy as accepting and this audience is almost
        # entirely EU. Make the choice unmissable, not lopsided.
        # The CSS ships WITH the banner rather than living in styles.css, because the
        # export funnel templates never load styles.css — the banner would have been
        # injected there unstyled, which is the same coverage gap that hid it in the
        # first place. Linking styles.css into those pages instead would restyle them
        # (they are dark, standalone documents). Everything here is scoped to
        # #cookie-banner and uses no Bootstrap classes, so it is safe on every page.
        return (
            '<style>'
            '#cookie-banner.d-none{display:none!important}'
            '#cookie-banner{position:fixed;inset:0;z-index:100000;display:flex;'
            'align-items:center;justify-content:center;padding:16px}'
            '#cookie-banner .cookie-backdrop{position:absolute;inset:0;'
            'background:rgba(8,10,16,.62)}'
            '#cookie-banner .cookie-card{position:relative;max-width:520px;width:100%%;'
            'background:#fff;color:#1c2029;border-radius:14px;padding:24px 26px;'
            'box-shadow:0 18px 48px rgba(0,0,0,.45);'
            'font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}'
            '#cookie-banner .cookie-title{font-size:1.15rem;font-weight:700;margin:0 0 8px}'
            '#cookie-banner .cookie-text{font-size:.92rem;line-height:1.5;margin:0 0 18px;'
            'color:#414958}'
            '#cookie-banner .cookie-text a{color:#0b5ed7}'
            '#cookie-banner .cookie-actions{display:flex;gap:10px}'
            # Equal weight by design: refusing must be as easy as accepting (EDPB).
            '#cookie-banner .cookie-btn{flex:1 1 0;padding:11px 14px;font-size:.92rem;'
            'font-weight:600;border-radius:9px;cursor:pointer;border:1px solid #c8cdd8}'
            '#cookie-banner .cookie-btn:focus-visible{outline:3px solid #0b5ed7;'
            'outline-offset:2px}'
            '#cookie-banner .cookie-btn-reject{background:#f1f3f7;color:#1c2029}'
            '#cookie-banner .cookie-btn-accept{background:#1c2029;color:#fff;'
            'border-color:#1c2029}'
            '@media(max-width:420px){#cookie-banner .cookie-actions'
            '{flex-direction:column-reverse}}'
            '</style>'
            '<script src="%s"></script>'
            '<div id="cookie-banner" class="d-none" role="dialog" aria-modal="true"'
            ' aria-labelledby="cookie-banner-title">'
            '<div class="cookie-backdrop"></div>'
            '<div class="cookie-card" role="document">'
            '<h2 id="cookie-banner-title" class="cookie-title">Before you continue</h2>'
            '<p class="cookie-text">We use cookies to measure traffic and to show ads, '
            'which is what keeps this site free. You can refuse and carry on using '
            'everything as normal. See our <a href="%s">Privacy Policy</a>.</p>'
            '<div class="cookie-actions">'
            '<button id="cookie-reject" type="button" class="cookie-btn cookie-btn-reject">'
            'Reject non-essential</button>'
            '<button id="cookie-accept" type="button" class="cookie-btn cookie-btn-accept">'
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
