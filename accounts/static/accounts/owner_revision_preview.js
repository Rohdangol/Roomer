"use strict";
(() => {
    const dialog = document.getElementById("revision-preview");
    const open = document.getElementById("open-revision-preview");
    if (!dialog || !open || open.disabled) return;
    open.addEventListener("click", () => {
        dialog.showModal();
        document.getElementById("revision-preview-title").focus();
    });
    document.getElementById("close-revision-preview").addEventListener("click", () => dialog.close());
    // Native modal dialogs trap focus and close with Escape; restore the initiating control.
    dialog.addEventListener("close", () => open.focus());
})();
