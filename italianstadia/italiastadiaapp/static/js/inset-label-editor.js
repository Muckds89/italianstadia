/**
 * Drag editor for the detail-view (inset) labels.
 *
 * The inset label engine has only two degrees of freedom: which column a pill
 * goes in (decided purely by x-rank) and where it sits in that column's vertical
 * stack. The x position is pinned to the box margin, and placement never looks at
 * where the badges are -- when a dense metro like Istanbul does not fit, the only
 * lever is shrinking the font, and the renderer then draws badges back ON TOP of
 * the pills because a hidden ground is worse than clipped text. That is why a
 * congested inset cannot be tidied by regenerating: there is nothing left to vary.
 *
 * This lets the user place those pills by hand. Positions are stored as FRACTIONS
 * of the inset box, so a layout dragged on the HD preview reproduces exactly on a
 * 4K paid download -- the same reasoning behind the resolution-independent marker
 * and label sizing.
 *
 * Geometry arrives on the preview response itself (X-Inset-Labels), not from a
 * second endpoint: the free tier is memory-capped hard enough that FHD and 4K
 * previews are already downgraded to HD, and a second full compose per preview
 * is exactly the kind of thing that OOMs the dyno.
 */
(function () {
    "use strict";

    var wrap = document.getElementById("previewWrap");
    if (!wrap) { return; }

    var positions = {};     // key -> [x, y] fractions of the inset box
    var geometry = null;    // last geometry from the server
    var layer = null;       // overlay element holding the draggable pills
    var enabled = false;

    function imgEl() { return wrap.querySelector("img.preview-img"); }

    /* The image is object-fit:contain inside a flex box, so its rendered rect is
     * NOT the element rect: letterboxing puts bars on whichever axis has slack.
     * Positioning pills against the element box would drift them off the map by
     * the size of those bars, and the drift changes with the panel width. */
    function imageRect() {
        var img = imgEl();
        if (!img || !img.naturalWidth) { return null; }
        var box = img.getBoundingClientRect();
        var scale = Math.min(box.width / img.naturalWidth,
                             box.height / img.naturalHeight);
        var w = img.naturalWidth * scale, h = img.naturalHeight * scale;
        return {left: box.left + (box.width - w) / 2,
                top: box.top + (box.height - h) / 2, width: w, height: h};
    }

    function insetRect() {
        var r = imageRect();
        if (!r || !geometry || !geometry.inset) { return null; }
        var i = geometry.inset;
        return {left: r.left + i.x * r.width, top: r.top + i.y * r.height,
                width: i.w * r.width, height: i.h * r.height};
    }

    function clearLayer() {
        if (layer && layer.parentNode) { layer.parentNode.removeChild(layer); }
        layer = null;
    }

    function render() {
        clearLayer();
        var box = insetRect();
        if (!enabled || !box || !geometry.labels || !geometry.labels.length) { return; }
        var wrapBox = wrap.getBoundingClientRect();

        layer = document.createElement("div");
        layer.style.cssText = "position:absolute;inset:0;z-index:6;pointer-events:none";
        wrap.appendChild(layer);

        // Outline the inset so it is obvious where a pill may be dropped.
        var frame = document.createElement("div");
        frame.style.cssText = "position:absolute;border:1px dashed rgba(120,200,255,.7);" +
            "pointer-events:none;left:" + (box.left - wrapBox.left) + "px;top:" +
            (box.top - wrapBox.top) + "px;width:" + box.width + "px;height:" +
            box.height + "px";
        layer.appendChild(frame);

        geometry.labels.forEach(function (L) {
            var pos = positions[L.key] || [L.x, L.y];
            var el = document.createElement("div");
            el.className = "inset-label-handle";
            el.dataset.key = L.key;
            el.title = (L.team ? L.team + "\n" : "") + L.stadium + "\n(drag to move)";
            el.textContent = L.team || L.stadium;
            el.style.cssText =
                "position:absolute;box-sizing:border-box;pointer-events:auto;" +
                "cursor:grab;font-size:9px;line-height:1.1;overflow:hidden;" +
                "padding:2px 3px;border-radius:3px;color:#fff;" +
                "background:rgba(10,13,24,.86);border:1px solid " +
                (positions[L.key] ? "#00e5ff" : "rgba(120,200,255,.55)") + ";" +
                "left:" + (box.left - wrapBox.left + pos[0] * box.width) + "px;" +
                "top:"  + (box.top - wrapBox.top + pos[1] * box.height) + "px;" +
                "width:" + (L.w * box.width) + "px;" +
                "height:" + (L.h * box.height) + "px;";
            attachDrag(el, L, box, wrapBox);
            layer.appendChild(el);
        });
    }

    function attachDrag(el, L, box, wrapBox) {
        function down(ev) {
            ev.preventDefault();
            var start = pointOf(ev);
            var startLeft = parseFloat(el.style.left), startTop = parseFloat(el.style.top);
            el.style.cursor = "grabbing";
            el.style.zIndex = "7";

            function move(e2) {
                var p = pointOf(e2);
                var nx = startLeft + (p.x - start.x), ny = startTop + (p.y - start.y);
                // Keep the whole pill inside the box: a drop half outside would
                // render clipped by the inset border, or off the export entirely.
                var maxX = box.left - wrapBox.left + box.width - el.offsetWidth;
                var maxY = box.top - wrapBox.top + box.height - el.offsetHeight;
                nx = Math.max(box.left - wrapBox.left, Math.min(maxX, nx));
                ny = Math.max(box.top - wrapBox.top, Math.min(maxY, ny));
                el.style.left = nx + "px";
                el.style.top = ny + "px";
            }
            function up() {
                document.removeEventListener("mousemove", move);
                document.removeEventListener("mouseup", up);
                document.removeEventListener("touchmove", move);
                document.removeEventListener("touchend", up);
                el.style.cursor = "grab";
                el.style.zIndex = "";
                el.style.borderColor = "#00e5ff";
                positions[L.key] = [
                    (parseFloat(el.style.left) - (box.left - wrapBox.left)) / box.width,
                    (parseFloat(el.style.top) - (box.top - wrapBox.top)) / box.height];
                announce();
            }
            document.addEventListener("mousemove", move);
            document.addEventListener("mouseup", up);
            document.addEventListener("touchmove", move, {passive: false});
            document.addEventListener("touchend", up);
        }
        el.addEventListener("mousedown", down);
        el.addEventListener("touchstart", down, {passive: false});
        // Double-click returns one label to its automatic slot without disturbing
        // any of the others.
        el.addEventListener("dblclick", function (ev) {
            ev.preventDefault();
            delete positions[L.key];
            announce();
            render();
        });
    }

    function pointOf(ev) {
        var t = (ev.touches && ev.touches[0]) || (ev.changedTouches && ev.changedTouches[0]);
        return t ? {x: t.clientX, y: t.clientY} : {x: ev.clientX, y: ev.clientY};
    }

    function announce() {
        var n = Object.keys(positions).length;
        var st = document.getElementById("insetLabelStatus");
        if (st) {
            st.textContent = n
                ? n + " label" + (n === 1 ? "" : "s") + " moved — regenerate to apply"
                : "";
        }
        var reset = document.getElementById("insetLabelReset");
        if (reset) { reset.classList.toggle("d-none", !n); }
    }

    /* Positions are keyed to a specific set of grounds inside a specific box. If
     * the box moves or the stadium set changes, a saved fraction points somewhere
     * meaningless -- and because the paid download replays these same values, a
     * stale one would ship a file that does not match the preview the user paid
     * from. So any control that can change either is treated as invalidating. */
    function invalidate() {
        if (!Object.keys(positions).length) { return; }
        positions = {};
        announce();
        render();
    }

    ["expInsetCorner", "expInsetSize", "expInset", "expCountry", "expLeague",
     "expLabels", "expLabelSize", "expBadgeSize", "expSpotlight"].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) { el.addEventListener("change", invalidate); }
    });

    document.addEventListener("export:previewReady", function (ev) {
        geometry = (ev.detail && ev.detail.geometry) || null;
        var has = !!(geometry && geometry.inset && geometry.labels && geometry.labels.length);
        var btn = document.getElementById("insetLabelBtn");
        if (btn) { btn.classList.toggle("d-none", !has); }
        if (!has) { enabled = false; clearLayer(); return; }
        // Drop positions for grounds that are no longer in the inset, so a key
        // from a previous country cannot linger in the query string.
        var live = {};
        geometry.labels.forEach(function (L) { live[L.key] = true; });
        Object.keys(positions).forEach(function (k) {
            if (!live[k]) { delete positions[k]; }
        });
        announce();
        render();
    });

    window.addEventListener("resize", function () { if (enabled) { render(); } });

    document.addEventListener("click", function (ev) {
        var btn = ev.target.closest && ev.target.closest("#insetLabelBtn");
        if (btn) {
            enabled = !enabled;
            btn.classList.toggle("active", enabled);
            btn.textContent = enabled ? "Done moving labels" : "Move inset labels";
            render();
            return;
        }
        if (ev.target.closest && ev.target.closest("#insetLabelReset")) {
            positions = {};
            announce();
            render();
        }
    });

    window.insetLabelEditor = {
        serialize: function () {
            return Object.keys(positions).map(function (k) {
                var p = positions[k];
                return k + ":" + p[0].toFixed(4) + "," + p[1].toFixed(4);
            }).join(";");
        },
        reset: function () { positions = {}; announce(); render(); },
        count: function () { return Object.keys(positions).length; }
    };
})();
