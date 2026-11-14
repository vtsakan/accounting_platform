/* Presentation only: no credentials, requests, financial math or form interception. */
(() => {
    "use strict";
    const root = document.documentElement;
    const button = document.querySelector("[data-theme-toggle]");
    const preference = window.matchMedia("(prefers-color-scheme: dark)");
    let selected = null;
    try { selected = window.localStorage.getItem("accounting-color-mode"); } catch (_) { /* Storage may be disabled. */ }
    function theme(mode) {
        const dark = mode === "dark";
        root.dataset.theme = dark ? "dark" : "light";
        if (button) {
            button.hidden = false;
            button.setAttribute("aria-pressed", String(dark));
            button.setAttribute("aria-label", dark ? "Ενεργοποίηση φωτεινού θέματος" : "Ενεργοποίηση σκούρου θέματος");
        }
    }
    theme(selected === "dark" || selected === "light" ? selected : (preference.matches ? "dark" : "light"));
    if (button) button.addEventListener("click", () => {
        selected = root.dataset.theme === "dark" ? "light" : "dark";
        theme(selected);
        try { window.localStorage.setItem("accounting-color-mode", selected); } catch (_) { /* Current page still works. */ }
    });
    preference.addEventListener("change", event => {
        if (selected !== "dark" && selected !== "light") theme(event.matches ? "dark" : "light");
    });

    const navigation = document.getElementById("workspace-navigation");
    const compact = window.matchMedia("(max-width: 1023px)");
    function fitNavigation() { if (navigation) navigation.open = !compact.matches; }
    fitNavigation();
    compact.addEventListener("change", fitNavigation);
    if (navigation) navigation.addEventListener("keydown", event => {
        if (event.key === "Escape" && compact.matches && navigation.open) {
            navigation.open = false;
            navigation.querySelector("summary").focus();
        }
    });

    // Scrollable data tables remain keyboard-reachable without changing them.
    document.querySelectorAll(".table-responsive").forEach(region => {
        if (!region.hasAttribute("tabindex")) region.tabIndex = 0;
        if (!region.hasAttribute("role")) region.setAttribute("role", "region");
        if (!region.hasAttribute("aria-label") && !region.hasAttribute("aria-labelledby")) {
            const caption = region.querySelector("caption");
            region.setAttribute("aria-label", caption ? caption.textContent.trim() : "Πίνακας δεδομένων · κύλιση οριζόντια");
        }
    });
})();
