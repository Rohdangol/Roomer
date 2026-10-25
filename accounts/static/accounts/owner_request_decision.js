"use strict";
(() => {
    const dialog = document.querySelector(".owner-decision-dialog");
    if (!dialog || typeof dialog.showModal !== "function") return;
    const forms = document.querySelectorAll("[data-owner-decision]");
    let activeForm = null;
    let trigger = null;
    let confirmed = false;
    let submitting = false;
    forms.forEach(form => form.addEventListener("submit", event => {
        if (submitting) { event.preventDefault(); return; }
        if (confirmed && form === activeForm) {
            submitting = true;
            forms.forEach(item => { item.querySelector("button[type=submit]").disabled = true; });
            return;
        }
        event.preventDefault();
        activeForm = form;
        trigger = form.querySelector("button[type=submit]");
        const accepting = form.dataset.ownerDecision === "accept";
        dialog.querySelector("h2").textContent = accepting ? "Accept this request?" : "Reject this request?";
        dialog.querySelector("p").textContent = accepting
            ? "This will accept the rental request. Agreement preparation remains a separate step."
            : "This will reject the rental request.";
        confirmed = false;
        dialog.showModal();
        document.documentElement.classList.add("request-cancel-open");
    }));
    dialog.querySelector("[data-decision-dismiss]").addEventListener("click", () => dialog.close());
    dialog.querySelector("[data-decision-confirm]").addEventListener("click", () => {
        // Keep the existing POST endpoint responsible for permissions and valid transitions.
        confirmed = true;
        dialog.close();
        activeForm.requestSubmit();
    });
    dialog.addEventListener("close", () => {
        document.documentElement.classList.remove("request-cancel-open");
        trigger?.focus();
    });
})();
