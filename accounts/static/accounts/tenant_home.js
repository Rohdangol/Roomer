"use strict";

document.querySelectorAll("[data-listing-photo]").forEach((image) => {
    function showUnavailablePhoto() {
        // A removed/unavailable file must not leave a broken-image icon in the card.
        const label = document.createElement("span");
        label.textContent = "Photo unavailable";
        image.replaceWith(label);
    }
    image.addEventListener("error", showUnavailablePhoto, { once: true });
    if (image.complete && image.naturalWidth === 0) showUnavailablePhoto();
});
