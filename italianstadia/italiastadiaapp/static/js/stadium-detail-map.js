document.addEventListener("DOMContentLoaded", function () {
    const mapContainer = document.getElementById("stadium-detail-map");
    if (!mapContainer) return;

    const lat = parseFloat(mapContainer.dataset.lat);
    const lng = parseFloat(mapContainer.dataset.lng);
    const stadiumName = mapContainer.dataset.name;
    let logos = [];
    try { logos = JSON.parse(mapContainer.dataset.logos || "[]"); } catch (e) {}

    if (Number.isNaN(lat) || Number.isNaN(lng)) return;

    // ----------------------------------------------------------------
    // Shared helper: build the team logo marker element (satellite + 3D)
    // ----------------------------------------------------------------
    function buildLogoMarker() {
        const el = document.createElement("div");
        el.className = "stadium-logo-marker";
        if (logos.length === 0) {
            el.textContent = "⚽";
        } else if (logos.length === 1) {
            const img = document.createElement("img");
            img.src = logos[0].url;
            img.alt = logos[0].name;
            el.appendChild(img);
        } else {
            // Split badge for multi-tenant stadiums
            el.style.cssText = "display:flex; overflow:hidden; border-radius:50%; padding:0;";
            logos.slice(0, 2).forEach(function (l, i) {
                const half = document.createElement("img");
                half.src = l.url;
                half.alt = l.name;
                half.style.cssText =
                    "flex:1; min-width:0; height:100%; object-fit:cover; display:block;" +
                    (i === 0 ? "border-right:1.5px solid rgba(255,255,255,0.5);" : "");
                el.appendChild(half);
            });
        }
        return el;
    }

    // ----------------------------------------------------------------
    // SATELLITE MAP  (animated fly-in, ESRI World Imagery)
    // ----------------------------------------------------------------
    const ANIM_DURATION = 6500;
    const START = { zoom: 12, pitch: 35, bearing: -90 };
    const END   = { zoom: 16.5, pitch: 65, bearing: 0 };

    const map = new maplibregl.Map({
        container: "stadium-detail-map",
        style: {
            version: 8,
            sources: {
                esri: {
                    type: "raster",
                    tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
                    tileSize: 256,
                    attribution: "Tiles © Esri"
                }
            },
            layers: [{ id: "esri", type: "raster", source: "esri" }]
        },
        center: [lng, lat],
        zoom: START.zoom,
        pitch: START.pitch,
        bearing: START.bearing,
        maxZoom: 20
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");

    new maplibregl.Marker({ element: buildLogoMarker(), anchor: "center" })
        .setLngLat([lng, lat])
        .setPopup(new maplibregl.Popup().setText(stadiumName))
        .addTo(map);

    // --- Animation logic ---
    let mapLoaded = false;
    let inView = false;

    function runAnimation() {
        const start = performance.now();
        function animate(now) {
            const progress = Math.min((now - start) / ANIM_DURATION, 1);
            const eased = 1 - Math.pow(1 - progress, 3);
            map.jumpTo({
                center: [lng, lat],
                zoom:    START.zoom    + (END.zoom    - START.zoom)    * eased,
                pitch:   START.pitch   + (END.pitch   - START.pitch)   * eased,
                bearing: START.bearing + (END.bearing - START.bearing) * eased,
            });
            if (progress < 1) requestAnimationFrame(animate);
        }
        requestAnimationFrame(animate);
    }

    function tryAnimate() {
        if (mapLoaded && inView) runAnimation();
    }

    map.on("load", function () {
        mapLoaded = true;
        tryAnimate();
    });

    // One-shot IntersectionObserver — fires once when ≥ 40% of the map is visible
    const observer = new IntersectionObserver(function (entries, obs) {
        if (entries[0].isIntersecting) {
            inView = true;
            obs.disconnect();
            tryAnimate();
        }
    }, { threshold: 0.4 });
    observer.observe(mapContainer);

    // Replay button
    const replayBtn = document.getElementById("replay-animation");
    if (replayBtn) {
        replayBtn.addEventListener("click", function () {
            map.jumpTo({ center: [lng, lat], zoom: START.zoom, pitch: START.pitch, bearing: START.bearing });
            setTimeout(runAnimation, 150);
        });
    }

    // ----------------------------------------------------------------
    // 3D EXPLORER MAP  (vector tiles + building extrusions)
    // ----------------------------------------------------------------
    const map3dContainer = document.getElementById("stadium-3d-map");
    if (!map3dContainer) return;

    const INIT_3D = { zoom: 16, pitch: 60, bearing: -20 };

    const map3d = new maplibregl.Map({
        container: "stadium-3d-map",
        style: "https://tiles.openfreemap.org/styles/liberty",
        center: [lng, lat],
        zoom: INIT_3D.zoom,
        pitch: INIT_3D.pitch,
        bearing: INIT_3D.bearing,
        maxZoom: 20
    });

    map3d.addControl(new maplibregl.NavigationControl(), "top-right");

    map3d.on("load", function () {
        // Find first symbol layer so buildings render under text labels
        const styleLayer = map3d.getStyle().layers.find(function (l) {
            return l.type === "symbol";
        });
        const beforeLayer = styleLayer ? styleLayer.id : undefined;

        // Auto-detect vector tile source (usually "openmaptiles" in OFM styles)
        const sources = map3d.getStyle().sources;
        const vectorEntry = Object.entries(sources).find(function (entry) {
            return entry[1].type === "vector";
        });

        if (vectorEntry) {
            const sourceName = vectorEntry[0];

            map3d.addLayer({
                id: "3d-buildings",
                source: sourceName,
                "source-layer": "building",
                type: "fill-extrusion",
                minzoom: 14,
                paint: {
                    // Height-based colour: light blue (short) → vivid blue → navy (tall)
                    "fill-extrusion-color": [
                        "interpolate", ["linear"],
                        ["coalesce", ["get", "render_height"], 0],
                        0,   "#90caf9",
                        25,  "#42a5f5",
                        70,  "#1565c0"
                    ],
                    "fill-extrusion-height":  ["coalesce", ["get", "render_height"],     5],
                    "fill-extrusion-base":    ["coalesce", ["get", "render_min_height"], 0],
                    "fill-extrusion-opacity": 0.82
                }
            }, beforeLayer);
        }

        // Stadium logo marker on the 3D map
        new maplibregl.Marker({ element: buildLogoMarker(), anchor: "center" })
            .setLngLat([lng, lat])
            .setPopup(new maplibregl.Popup().setText(stadiumName))
            .addTo(map3d);
    });

    // Reset view button
    const reset3dBtn = document.getElementById("reset-3d-view");
    if (reset3dBtn) {
        reset3dBtn.addEventListener("click", function () {
            map3d.easeTo({
                center:  [lng, lat],
                zoom:    INIT_3D.zoom,
                pitch:   INIT_3D.pitch,
                bearing: INIT_3D.bearing,
                duration: 800
            });
        });
    }
});
