document.addEventListener("DOMContentLoaded", function () {
    const mapContainer = document.getElementById("stadium-detail-map");
    if (!mapContainer) return;

    const lat = parseFloat(mapContainer.dataset.lat);
    const lng = parseFloat(mapContainer.dataset.lng);
    const logo = mapContainer.dataset.logo;
    const stadiumName = mapContainer.dataset.name;

    if (Number.isNaN(lat) || Number.isNaN(lng)) return;

    // Animation parameters
    const ANIM_DURATION = 6500;
    const START = { zoom: 12, pitch: 35, bearing: -90 };
    const END   = { zoom: 16.5, pitch: 65, bearing: 0 };

    // Init map at animation start values so there is no visual jump
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

    const markerEl = document.createElement("div");
    markerEl.className = "stadium-logo-marker";
    if (logo) {
        const img = document.createElement("img");
        img.src = logo;
        img.alt = stadiumName;
        markerEl.appendChild(img);
    } else {
        markerEl.textContent = "⚽";
    }
    new maplibregl.Marker({ element: markerEl, anchor: "center" })
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

    // Fire when map tiles are ready
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

    // Replay button — resets map to start state then re-runs animation
    const replayBtn = document.getElementById("replay-animation");
    if (replayBtn) {
        replayBtn.addEventListener("click", function () {
            map.jumpTo({
                center: [lng, lat],
                zoom: START.zoom,
                pitch: START.pitch,
                bearing: START.bearing,
            });
            // Small delay so the reset is visible before the fly-in starts
            setTimeout(runAnimation, 150);
        });
    }
});
