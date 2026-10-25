"use strict";
(() => {
    const form = document.getElementById("request-cancel-form");
    const dialog = document.querySelector(".request-cancel-dialog");
    if (!form || !dialog || typeof dialog.showModal !== "function") return;
    const trigger = document.getElementById("request-cancel-trigger");
    let confirmed = false;
    let submitting = false;
    form.addEventListener("submit", event => {
        if (submitting) { event.preventDefault(); return; }
        if (!confirmed) {
            event.preventDefault();
            dialog.showModal();
            document.documentElement.classList.add("request-cancel-open");
            return;
        }
        submitting = true;
        trigger.disabled = true;
    });
    dialog.querySelector("[data-keep-request]").addEventListener("click", () => dialog.close());
    dialog.querySelector("[data-confirm-cancel]").addEventListener("click", () => {
        // The existing POST endpoint still checks ownership and pending status.
        confirmed = true;
        dialog.close();
        form.requestSubmit();
    });
    dialog.addEventListener("close", () => {
        document.documentElement.classList.remove("request-cancel-open");
        trigger.focus();
    });
})();
