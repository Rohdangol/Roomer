"use strict";
(() => {
    const dialog = document.querySelector(".neighbourhood-modal");
    const trigger = document.querySelector("[data-open-neighbourhoods]");
    if (!dialog || !trigger || !dialog.showModal) return;
    let previousFocus, previousOverflow;
    function open() {
        previousFocus = document.activeElement;
        previousOverflow = document.body.style.overflow;
        if (dialog.open) return;
        dialog.showModal();
        document.body.style.overflow = "hidden";
        dialog.querySelector("[data-close-neighbourhoods]").focus();
    }
    trigger.addEventListener("click", event => { event.preventDefault(); open(); });
    dialog.querySelector("[data-close-neighbourhoods]").addEventListener("click", event => {
        event.preventDefault(); dialog.close();
    });
    dialog.addEventListener("close", () => {
        document.body.style.overflow = previousOverflow || "";
        (previousFocus?.isConnected ? previousFocus : trigger).focus({preventScroll:true});
    });
    // Native dialog supplies focus containment and Escape dismissal.
    if (dialog.open) { dialog.removeAttribute("open"); open(); }
})();
