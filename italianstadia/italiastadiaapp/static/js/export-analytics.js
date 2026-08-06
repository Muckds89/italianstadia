/*
 * GA4 tracking for the paid-export funnel.
 *
 * Uses GA4's standard ecommerce event names (view_item → select_item →
 * begin_checkout → purchase) rather than custom ones, so the funnel shows up in
 * the built-in Monetisation reports and can be marked as key events without any
 * extra configuration. gtag() is injected site-wide by GoogleAnalyticsMiddleware, so it
 * exists on every page — but it is a no-op when GOOGLE_ANALYTICS_ID is unset
 * (local dev), hence the guard.
 *
 * The page templates own no analytics logic: export.html dispatches plain
 * CustomEvents on `document` and this file decides what to send.
 */
(function () {
    "use strict";

    var root = document.getElementById("exportAnalytics");
    if (!root) return;

    var PRICE = parseFloat(root.dataset.price || "0");   // euros, e.g. 0.50
    var CURRENCY = "EUR";

    // The single product this site sells.
    function item(extra) {
        var it = {
            item_id: "map_export_clean",
            item_name: "Stadium map, clean version",
            item_category: "map_export",
            price: PRICE,
            quantity: 1,
        };
        for (var k in (extra || {})) it[k] = extra[k];
        return it;
    }

    function send(name, params) {
        if (typeof window.gtag !== "function") return;
        window.gtag("event", name, params);
    }

    // Which filters the user actually configured — lets us see in GA whether
    // buyers differ from browsers in what they build (e.g. do payers pick 4K?).
    function variant(f) {
        f = f || {};
        return [f.league || f.country || "all", f.style_key || "?", f.size_key || "?"]
            .join(" / ");
    }

    // ── 1. View ───────────────────────────────────────────────────────────────
    // Fired on /export/ load. This is the top of the funnel: how many of the
    // people who reach the page ever configure anything.
    if (root.dataset.step === "view") {
        send("view_item", {
            currency: CURRENCY,
            value: PRICE,
            items: [item()],
        });
    }

    // ── 2. Configure ──────────────────────────────────────────────────────────
    // Fired the FIRST time a preview renders. Deliberately once per page: the
    // preview button gets hammered while people tweak, and 30 select_item events
    // from one session would make the funnel unreadable.
    var configured = false;
    document.addEventListener("export:preview", function (e) {
        if (configured) return;
        configured = true;
        send("select_item", {
            item_list_id: "map_export_config",
            item_list_name: "Export configurator",
            items: [item({ item_variant: variant(e.detail && e.detail.filters) })],
        });
    });

    // ── 3. Checkout ───────────────────────────────────────────────────────────
    // Fired only AFTER the confirm() dialog is accepted, so it counts real intent
    // to pay, not clicks on the button. The gap between this and `purchase` is
    // the Stripe drop-off.
    document.addEventListener("export:checkout", function (e) {
        send("begin_checkout", {
            currency: CURRENCY,
            value: PRICE,
            items: [item({ item_variant: variant(e.detail && e.detail.filters) })],
        });
    });

    // The free download competes directly with the paid one, so it needs to be
    // visible in the same report — otherwise a healthy funnel that simply loses
    // everyone to the free button looks like generic drop-off.
    document.addEventListener("export:free", function (e) {
        send("export_free_download", {
            item_variant: variant(e.detail && e.detail.filters),
        });
    });

    // ── 4. Purchase ───────────────────────────────────────────────────────────
    // Fired on the success page. transaction_id is the Stripe session id, which
    // makes GA4 de-duplicate refreshes of the success page automatically — without
    // it, one buyer hitting F5 would book multiple sales.
    if (root.dataset.step === "purchase") {
        send("purchase", {
            transaction_id: root.dataset.transactionId || "",
            currency: CURRENCY,
            value: PRICE,
            items: [item()],
        });
    }

    // Delivery is a separate step from payment: a purchase with no download means
    // the PNG render failed and the customer paid for nothing.
    var dl = document.getElementById("downloadBtn");
    if (dl) {
        dl.addEventListener("click", function () {
            send("file_download", {
                file_name: "stadiums-of-europe-map.png",
                file_extension: "png",
                link_url: dl.getAttribute("href") || "",
            });
        });
    }
})();
