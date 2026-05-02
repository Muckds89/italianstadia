const map = L.map('map', {
    zoomControl: false
}).setView([42.5, 12.5], 5);

L.tileLayer(
    'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    {
        attribution: '&copy; OpenStreetMap & CARTO'
    }
).addTo(map);

L.control.zoom({
    position: 'bottomright'
}).addTo(map);

let markers = [];
let activeMarker = null;
let activePopup = null;

fetch("/api/stadiums/")
    .then(res => res.json())
    .then(data => {
        data.features.forEach(feature => {
            const coords = feature.geometry.coordinates;
            const props = feature.properties;

            const marker = L.circleMarker([coords[1], coords[0]], {
                radius: 7,
                fillColor: "#00e5ff",
                color: "#ffffff",
                weight: 1,
                opacity: 1,
                fillOpacity: 0.9
            });

            marker.tier = String(props.tier);

            marker.on("click", function () {
                if (activeMarker === marker && activePopup) {
                    map.closePopup(activePopup);
                    activeMarker = null;
                    activePopup = null;
                    return;
                }

                if (activePopup) {
                    map.closePopup(activePopup);
                }

                activePopup = L.popup()
                    .setLatLng([coords[1], coords[0]])
                    .setContent(`
                        <div style="min-width:180px">
                            <strong>${props.name}</strong><br>
                            ${props.city}<br>
                            ${props.team ? `<strong>Team:</strong> ${props.team}<br>` : ""}
                            ${props.tier_name ? `<strong>League:</strong> ${props.tier_name}<br>` : ""}
                            <strong>Capacity:</strong> ${props.capacity}<br><br>
                            <a href="/stadium/${props.id}/">View details</a>
                            ${props.wikipedia_url ? `<br><a href="${props.wikipedia_url}" target="_blank">Wikipedia</a>` : ""}
                            ${props.transfermarkt_url ? `<br><a href="${props.transfermarkt_url}" target="_blank">Transfermarkt</a>` : ""}
                        </div>
                    `)
                    .openOn(map);

                activeMarker = marker;
            });

            marker.on("mouseover", function () {
                this.setStyle({
                    radius: 9,
                    fillColor: "#ff5722"
                });
            });

            marker.on("mouseout", function () {
                this.setStyle({
                    radius: 7,
                    fillColor: "#00e5ff"
                });
            });

            marker.addTo(map);
            markers.push(marker);
        });
    });

document.getElementById("tierFilter").addEventListener("change", function () {
    const selectedTier = this.value;

    markers.forEach(marker => {
        if (!selectedTier || marker.tier === selectedTier) {
            marker.addTo(map);
        } else {
            map.removeLayer(marker);
        }
    });

    if (activePopup) {
        map.closePopup(activePopup);
        activeMarker = null;
        activePopup = null;
    }
});