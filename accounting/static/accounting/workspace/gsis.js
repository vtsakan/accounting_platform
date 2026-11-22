(() => {
  "use strict";
  const entry = "https://www1.gsis.gr/taxisnet/mytaxisnet";
  document.querySelectorAll("[data-gsis-panel]").forEach((panel) => {
    const dialog = panel.querySelector("[data-gsis-dialog]");
    const username = panel.querySelector("[data-gsis-username]");
    const password = panel.querySelector("[data-gsis-password]");
    const message = panel.querySelector("[data-gsis-message]");
    const status = panel.querySelector("[data-gsis-status]");
    let controller = null;
    let generation = 0;
    let expiry = null;
    const clear = () => {
      generation += 1;
      if (controller) controller.abort();
      controller = null;
      clearTimeout(expiry);
      username.value = "";
      password.value = "";
      panel.querySelectorAll("[data-gsis-copy]").forEach((button) => { button.disabled = true; });
    };
    const close = () => { clear(); if (dialog.open) dialog.close(); };
    panel.querySelector("[data-gsis-close]").addEventListener("click", close);
    dialog.addEventListener("close", () => { if (!dialog.open) clear(); });
    dialog.addEventListener("cancel", clear);
    window.addEventListener("pagehide", close);
    panel.querySelectorAll("[data-gsis-launch]").forEach((button) => {
      button.addEventListener("click", async () => {
        clear();
        const requestGeneration = generation;
        const form = button.closest("[data-gsis-form]");
        const subject = form.dataset.gsisSubject;
        const endpoint = new URL(form.action, location.origin);
        const expected = `/entity/${panel.dataset.entityId}/gsis/${subject}/credentials/`;
        if (!["MAIN", "SPOUSE"].includes(subject) || endpoint.origin !== location.origin ||
            endpoint.pathname !== expected || endpoint.search || endpoint.hash) return;
        // User gesture opens the official entry. No credential or copied SSO token is in its URL.
        window.open(entry, "_blank", "noopener,noreferrer,popup,width=1100,height=850");
        panel.querySelector("[data-gsis-title]").textContent = subject === "SPOUSE" ?
          "Κωδικοί GSIS — Σύζυγος" : "Κωδικοί GSIS — Πελάτης";
        message.textContent = "Ανάκτηση αποθηκευμένων κωδικών…";
        status.textContent = "Το GSIS ανοίγει σε νέο παράθυρο. Αν εμποδιστεί, χρησιμοποιήστε τον σύνδεσμο Άνοιγμα GSIS.";
        if (!dialog.open) dialog.showModal();
        controller = new AbortController();
        const activeController = controller;
        const requestTimeout = setTimeout(() => activeController.abort(), 15000);
        expiry = setTimeout(() => {
          clear(); message.textContent = "Ο χρόνος προβολής έληξε. Πατήστε ξανά το κουμπί σύνδεσης.";
        }, 90000);
        try {
          const response = await fetch(endpoint.href, {
            method: "POST", credentials: "same-origin", cache: "no-store", redirect: "error",
            headers: {"X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value,
              "Accept": "application/json"}, signal: activeController.signal
          });
          if (!response.ok || !response.headers.get("Content-Type")?.includes("application/json")) throw new Error();
          const data = await response.json();
          if (requestGeneration !== generation || !dialog.open) return;
          if (String(data.entity_id) !== panel.dataset.entityId || data.subject !== subject ||
              typeof data.username !== "string" || typeof data.password !== "string" ||
              data.username.length > 200 || data.password.length > 512 ||
              Boolean(data.username) !== Boolean(data.password)) throw new Error();
          username.value = data.username;
          password.value = data.password;
          data.username = ""; data.password = "";
          panel.querySelectorAll("[data-gsis-copy]").forEach((copy) => { copy.disabled = !username.value; });
          message.textContent = username.value ?
            "Αντιγράψτε κάθε πεδίο και επικολλήστε το στην αντίστοιχη θέση στο GSIS. Έπειτα πατήστε εκεί Σύνδεση." :
            "Δεν υπάρχουν αποθηκευμένοι κωδικοί για αυτή την επιλογή. Τα δύο πεδία παραμένουν κενά.";
        } catch (_) {
          if (requestGeneration !== generation) return;
          clear(); message.textContent = "Η ανάκτηση δεν ολοκληρώθηκε. Ελέγξτε τη σύνδεση και την πρόσβασή σας και δοκιμάστε ξανά.";
        } finally { clearTimeout(requestTimeout); }
      });
    });
    panel.querySelectorAll("[data-gsis-copy]").forEach((button) => {
      button.addEventListener("click", async () => {
        const field = button.dataset.gsisCopy === "password" ? password : username;
        if (!dialog.open || !field.value) return;
        const current = generation;
        try {
          await navigator.clipboard.writeText(field.value);
          if (current === generation) message.textContent = "Αντιγράφηκε. Επικολλήστε το στο αντίστοιχο πεδίο του GSIS.";
        } catch (_) {
          if (current !== generation) return;
          field.focus(); field.select();
          message.textContent = "Επιλέχθηκε το πεδίο. Χρησιμοποιήστε την εντολή Αντιγραφή του προγράμματος περιήγησης.";
        }
      });
    });
  });
})();
