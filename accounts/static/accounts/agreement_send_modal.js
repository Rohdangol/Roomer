"use strict";
(() => {
    const trigger = document.querySelector("[data-open-agreement-consent]");
    const dialog = document.querySelector(".owner-agreement-consent-dialog");
    const form = document.querySelector("[data-agreement-consent-form]");
    if (!trigger || !dialog || !form || typeof dialog.showModal !== "function") return;
    // Move, rather than copy, the real form so CSRF and exact-version consent remain intact.
    dialog.querySelector("[data-agreement-consent-content]").append(form);
    const cancel = form.querySelector("[data-close-agreement-consent]");
    const consent = form.querySelector("input[name=confirm]");
    trigger.hidden = false;
    cancel.hidden = false;
    let submitting = false;
    trigger.addEventListener("click", () => {
        consent.checked = false;
        dialog.showModal();
        document.documentElement.classList.add("agreement-consent-open");
        consent.focus();
    });
    cancel.addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => {
        document.documentElement.classList.remove("agreement-consent-open");
        trigger.focus();
    });
    form.addEventListener("submit", event => {
        if (submitting) { event.preventDefault(); return; }
        if (!form.reportValidity()) { event.preventDefault(); return; }
        submitting = true;
        form.querySelector("button[type=submit]").disabled = true;
        form.setAttribute("aria-busy", "true");
    });
})();
