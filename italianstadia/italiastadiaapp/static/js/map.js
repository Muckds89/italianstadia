// INIT MAP
const map = L.map('map', {
    zoomControl: false
}).setView([42.5, 12.5], 6);

// DARK BASEMAP
L.tileLayer(
    'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    {
        attribution: '&copy; OpenStreetMap & CARTO'
    }
).addTo(map);

// MOVE ZOOM BUTTON
L.control.zoom({
    position: 'bottomright'
}).addTo(map);

// STORE MARKERS
let markers = [];

// LOAD DATA FROM DJANGO API
fetch("/api/stadiums/")
    .then(res => res.json())
    .then(data => {

        data.features.forEach(feature => {

            const coords = feature.geometry.coordinates;
            const props = feature.properties;

            const marker = L.marker([coords[1], coords[0]])
                .bindPopup(`
                    <b>${props.name}</b><br>
                    ${props.city}<br>
                    <a href="/stadium/${props.id}/">View details</a>
                `);

            marker.city = props.city;

            marker.addTo(map);
            markers.push(marker);
        });
    });

// FILTER
document.getElementById("cityFilter").addEventListener("change", function () {
    const selected = this.value;

    markers.forEach(marker => {
        if (!selected || marker.city === selected) {
            marker.addTo(map);
        } else {
            map.removeLayer(marker);
        }
    });
});