"use strict";
(() => {
    const trigger = document.querySelector("[data-request-modal-trigger]");
    const dialog = document.getElementById("rental-request-modal");
    if (!trigger || !dialog || typeof dialog.showModal !== "function") return;
    const content = dialog.querySelector(".request-modal-content");
    const status = dialog.querySelector(".request-modal-status");
    let loading = false;
    let submitting = false;
    function focusContent() {
        const error = content.querySelector(".errorlist");
        if (error) { error.tabIndex = -1; error.focus(); }
        else content.querySelector("input:not([type=hidden]), textarea")?.focus();
    }
    function close() { dialog.close(); }
    dialog.querySelector("[data-request-close]").addEventListener("click", close);
    dialog.addEventListener("close", () => {
        document.documentElement.classList.remove("request-modal-open");
        trigger.focus();
    });
    // Native dialog provides focus containment and Escape dismissal.
    trigger.addEventListener("click", async event => {
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        if (!dialog.open) dialog.showModal();
        document.documentElement.classList.add("request-modal-open");
        if (content.querySelector("form")) { focusContent(); return; }
        if (loading) return;
        loading = true;
        status.textContent = "Loading request form?";
        try {
            const response = await fetch(trigger.href, {headers: {"X-Requested-With": "XMLHttpRequest"}});
            if (!response.ok || response.redirected) throw new Error("unavailable");
            content.innerHTML = await response.text();
            status.textContent = "";
            if (dialog.open) focusContent();
        } catch (error) {
            status.textContent = "The form could not load. Open the request page to continue.";
            const link = document.createElement("a");
            link.href = trigger.href;
            link.textContent = "Open request page";
            content.replaceChildren(link);
        } finally { loading = false; }
    });
    content.addEventListener("click", event => {
        if (event.target.closest("[data-request-cancel]")) { event.preventDefault(); close(); }
    });
    content.addEventListener("submit", async event => {
        const form = event.target;
        if (!form.matches(".request-submission-form")) return;
        event.preventDefault();
        if (submitting) return;
        submitting = true;
        const button = form.querySelector("button[type=submit]");
        button.disabled = true;
        form.setAttribute("aria-busy", "true");
        status.textContent = "Sending request?";
        try {
            // FormData includes Django's CSRF token; the existing service owns all checks.
            const response = await fetch(form.action, {method: "POST", body: new FormData(form), headers: {"X-Requested-With": "XMLHttpRequest"}});
            if (response.redirected) { window.location.assign(response.url); return; }
            if (!response.ok) throw new Error("submission failed");
            content.innerHTML = await response.text();
            status.textContent = "Please correct the errors below.";
            if (dialog.open) focusContent();
        } catch (error) {
            status.textContent = "Delivery could not be confirmed. Check My Requests before retrying. Your entered values are retained.";
        } finally {
            submitting = false;
            button.disabled = false;
            form.removeAttribute("aria-busy");
        }
    });
})();
