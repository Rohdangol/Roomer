"use strict";
(() => {
    const dialog = document.querySelector(".preference-onboarding");
    if (!dialog) return;
    // Upgrade the server-visible fallback to a native modal with browser focus containment.
    dialog.close();
    dialog.showModal();
    dialog.querySelector("input:not([type=hidden])")?.focus();
    function close() { dialog.close(); document.getElementById("location-query")?.focus(); }
    dialog.querySelector("[data-close-preferences]").addEventListener("click", event => { event.preventDefault(); close(); });
    dialog.addEventListener("cancel", event => { event.preventDefault(); close(); });
})();
