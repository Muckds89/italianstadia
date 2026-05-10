document.addEventListener("DOMContentLoaded", function () {
    const mapContainer = document.getElementById("stadium-detail-map");
    if (!mapContainer) return;

    const lat = parseFloat(mapContainer.dataset.lat);
    const lng = parseFloat(mapContainer.dataset.lng);
    const logo = mapContainer.dataset.logo;

    console.log("logo:", logo);
    const stadiumName = mapContainer.dataset.name;

    if (Number.isNaN(lat) || Number.isNaN(lng)) return;

    const map = new maplibregl.Map({
        container: "stadium-detail-map",
        style: {
            version: 8,
            sources: {
                esri: {
                    type: "raster",
                    tiles: [
                        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                    ],
                    tileSize: 256,
                    attribution: "Tiles © Esri"
                }
            },
            layers: [
                {
                    id: "esri",
                    type: "raster",
                    source: "esri"
                }
            ]
        },
        center: [lng, lat],
        zoom: 12,
        pitch: 60,
        bearing: -25,
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

    new maplibregl.Marker({
        element: markerEl,
        anchor: "center"
    })
        .setLngLat([lng, lat])
        .setPopup(new maplibregl.Popup().setText(stadiumName))
        .addTo(map);

        map.on("load", function () {
            const start = performance.now();
            const duration = 6500;

            const startZoom = 12;
            const endZoom = 16.5;

            const startPitch = 35;
            const endPitch = 65;

            const startBearing = -90;
            const endBearing = 0;

            function animate(now) {
                const progress = Math.min((now - start) / duration, 1);

                // smooth easing
                const eased = 1 - Math.pow(1 - progress, 3);

                const zoom = startZoom + (endZoom - startZoom) * eased;
                const pitch = startPitch + (endPitch - startPitch) * eased;
                const bearing = startBearing + (endBearing - startBearing) * eased;

                map.jumpTo({
                    center: [lng, lat],
                    zoom: zoom,
                    pitch: pitch,
                    bearing: bearing
                });

                if (progress < 1) {
                    requestAnimationFrame(animate);
                }
            }

            requestAnimationFrame(animate);
    });
});