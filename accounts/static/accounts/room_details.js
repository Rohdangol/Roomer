"use strict";
(() => {
    const image = document.getElementById("gallery-main-photo");
    document.querySelectorAll("[data-gallery-photo]").forEach(link => {
        link.addEventListener("click", event => {
            if (!image || !image.isConnected) return; // Without JS, links still open authorized photos.
            event.preventDefault();
            image.src = link.href;
            image.alt = link.querySelector("img").alt;
        });
    });
    const container = document.getElementById("detail-location-map");
    if (!container) return;
    const status = document.getElementById("detail-map-status");
    const point = JSON.parse(document.getElementById("room-location-point").textContent);
    const fallback = `Coordinates: ${point.latitude}, ${point.longitude}.`;
    if (!window.L || !window.RoomerMaps) {
        status.textContent = `Map resources could not load. ${fallback}`;
        return;
    }
    try {
        const map = RoomerMaps.create(container, [point.latitude, point.longitude], 14, () => {
            status.textContent = `Map tiles could not load. ${fallback}`;
        });
        L.marker([point.latitude, point.longitude], {title: "Room location"}).addTo(map);
        status.textContent = fallback;
    } catch (error) {
        status.textContent = `Map could not start. ${fallback}`;
    }
})();
