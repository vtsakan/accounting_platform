(() => {
  "use strict";
  document.querySelectorAll("[data-task-switch]").forEach((switcher) => {
    const form = switcher.closest("form");
    const fields = form && form.querySelector("[data-task-fields]");
    if (!fields) return;
    const update = () => {
      fields.hidden = !switcher.checked;
      switcher.setAttribute("aria-expanded", String(switcher.checked));
      fields.querySelectorAll("input:not([readonly]),select").forEach((field) => {
        if (field.name === "recorded_on") return;
        field.disabled = !switcher.checked;
        field.required = switcher.checked;
      });
    };
    switcher.addEventListener("change", update);
    update();
  });
})();
