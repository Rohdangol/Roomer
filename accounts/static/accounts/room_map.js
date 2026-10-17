"use strict";
// Both tenant maps share provider attribution, referrer handling and clean tile failures.
window.RoomerMaps = {
    create(container, point, zoom, onFailure) {
        const map = L.map(container, {scrollWheelZoom: false}).setView(point, zoom);
        const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
            referrerPolicy: "strict-origin-when-cross-origin",
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        }).addTo(map);
        tiles.on("tileerror", () => {
            if (map.hasLayer(tiles)) map.removeLayer(tiles);
            onFailure();
        });
        new ResizeObserver(() => map.invalidateSize()).observe(container);
        return map;
    }
};
