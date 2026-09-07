/**
 * Drag editor for the MAIN map labels.
 *
 * The automatic layout pushes every label into the left or right margin and
 * stacks it in the same vertical order as its badge. That ordering is what keeps
 * leader lines from crossing, and it is worth keeping -- but it leaves only two
 * degrees of freedom, which margin and which slot. It cannot help a map whose
 * interesting clubs are all on one side, and it cannot know that one particular
 * label is the point of the picture.
 *
 * Positions are FRACTIONS OF THE WHOLE IMAGE, mirroring the inset editor's
 * fractions-of-the-box. The preview is always HD and the paid file may be 4K, so
 * storing pixels would land every dragged pill somewhere else on the download --
 * the one thing this renderer may never do.
 *
 * Geometry rides along on the preview response (X-Inset-Labels, which carries
 * both label sets) rather than coming from a second endpoint. A second full
 * compose per preview is exactly what the 512 MB dyno cannot afford.
 *
 * The server recomputes which SIDE each leader leaves from after a drag, so
 * moving a pill across its badge flips the leader to the near edge instead of
 * running it back across the map.
 */
(function () {
    "use strict";

    var wrap = document.getElementById("previewWrap");
    if (!wrap) { return; }

    var positions = {};     // key -> [x, y] fractions of the whole image
    var geometry = null;
    var layer = null;
    var enabled = false;

    function imgEl() { return wrap.querySelector("img.preview-img"); }

    /* object-fit:contain letterboxes the image inside its element, so the element
     * rect is NOT the image rect. Positioning against the element would drift
     * every pill by the size of the bars, and the drift changes with panel width. */
    function imageRect() {
        var img = imgEl();
        if (!img || !img.naturalWidth) { return null; }
        var box = img.getBoundingClientRect();
        // A zero-sized rect means the browser has the bytes but has not laid the
        // image out yet. Returning it anyway multiplies every fraction by zero,
        // so all 104 handles land on one spot in the corner -- a drag layer that
        // looks broken while the geometry behind it is perfectly correct.
        if (!box.width || !box.height) { return null; }
        var scale = Math.min(box.width / img.naturalWidth,
                             box.height / img.naturalHeight);
        var w = img.naturalWidth * scale, h = img.naturalHeight * scale;
        return {left: box.left + (box.width - w) / 2,
                top: box.top + (box.height - h) / 2, width: w, height: h};
    }

    /* Draw once the image has a SIZE, not merely once it has arrived.
     * `export:previewReady` fires as soon as the response is swapped in, which is
     * before layout, so rendering straight from the event measures a zero box. */
    function renderWhenReady(tries) {
        tries = tries || 0;
        if (!enabled) { clearLayer(); return; }
        if (imageRect()) { render(); return; }
        if (tries > 30) { return; }          // give up rather than spin forever
        var img = imgEl();
        if (img && !img.complete) {
            img.addEventListener("load", function once() {
                img.removeEventListener("load", once);
                renderWhenReady(tries + 1);
            });
            return;
        }
        window.requestAnimationFrame(function () { renderWhenReady(tries + 1); });
    }

    function clearLayer() {
        if (layer && layer.parentNode) { layer.parentNode.removeChild(layer); }
        layer = null;
    }

    function labels() {
        return (geometry && geometry.map_labels) || [];
    }

    function render() {
        clearLayer();
        var box = imageRect();
        if (!enabled || !box || !labels().length) { return; }
        var wrapBox = wrap.getBoundingClientRect();

        layer = document.createElement("div");
        layer.style.cssText = "position:absolute;inset:0;z-index:6;pointer-events:none";
        wrap.appendChild(layer);

        labels().forEach(function (L) {
            var pos = positions[L.key] || [L.x, L.y];
            var el = document.createElement("div");
            el.className = "map-label-handle";
            el.dataset.key = L.key;
            el.title = (L.team ? L.team + "\n" : "") + L.stadium +
                       "\n(drag to move, double-click to reset)";
            el.textContent = L.stadium || L.team;
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
                // Keep the pill inside the frame. The renderer clamps too, but
                // letting it be dragged somewhere it cannot be drawn makes the
                // preview disagree with the export.
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
        // Return ONE label to its automatic slot without disturbing the others.
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
        var st = document.getElementById("mapLabelStatus");
        if (st) {
            st.textContent = n
                ? n + " label" + (n === 1 ? "" : "s") + " moved — regenerate to apply"
                : "";
        }
    }

    /* A saved fraction is keyed to a specific ground in a specific frame. Change
     * the frame -- a different size, a spotlight, a different projection -- and a
     * stale fraction points somewhere meaningless. Because the PAID download
     * replays these same values, a stale one ships a file that does not match the
     * preview it was bought from, so treat those controls as invalidating. */
    function invalidate() {
        if (!Object.keys(positions).length) { return; }
        positions = {};
        announce();
        render();
    }

    // Real control ids only — a typo here fails SILENTLY, leaving stale positions
    // to ship on a paid download. The UEFA competition is chosen through
    // expTournament ("uefa:UCL"), and the layer switch is expDevLayer.
    ["expCountry", "expLeague", "expTournament", "expDevLayer",
     "expNational", "expSize", "expStyle", "expLabels"
    ].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) { el.addEventListener("change", invalidate); }
    });

    document.addEventListener("export:previewReady", function (ev) {
        geometry = (ev.detail && ev.detail.geometry) || null;
        // Drop positions for grounds no longer on the map, so a key from a
        // previous country cannot linger in the query string and reappear on a
        // later render.
        var live = {};
        labels().forEach(function (L) { live[L.key] = true; });
        Object.keys(positions).forEach(function (k) {
            if (!live[k]) { delete positions[k]; }
        });
        announce();
        renderWhenReady();
    });

    window.addEventListener("resize", function () { if (enabled) { render(); } });

    window.mapLabelEditor = {
        serialize: function () {
            return Object.keys(positions).map(function (k) {
                var p = positions[k];
                return k + ":" + p[0].toFixed(4) + "," + p[1].toFixed(4);
            }).join(";");
        },
        setEnabled: function (on) { enabled = !!on; renderWhenReady(); },
        reset: function () { positions = {}; announce(); render(); },
        count: function () { return Object.keys(positions).length; }
    };
})();
