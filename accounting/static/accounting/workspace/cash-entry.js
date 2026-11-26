/* Dependent, dated choices; authority and capacity remain on the server. */
document.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('[data-cash-entry]');
  if (!form) return;
  const party = form.querySelector('[name="entity"]');
  const agreement = form.querySelector('[name="agreement"]');
  const charge = form.querySelector('[name="charge"]');
  const enabled = form.querySelector('[name="settle_agreement"]');
  const description = form.querySelector('[name="description"]');
  const day = form.querySelector('[name="transaction_date"]');
  const status = form.querySelector('[data-agreement-status]');
  if (!party || !agreement || !charge || !enabled || !description || !day || !status) return;
  let sequence = 0;
  let controller;
  let pending = false;
  const blank = (select, text) => select.replaceChildren(new Option(text, ''));
  const state = () => {
    agreement.required = enabled.checked;
    charge.required = enabled.checked;
    description.required = !enabled.checked;
    description.placeholder = enabled.checked ? 'Συμπληρώνεται από την επιλεγμένη χρέωση' : '';
    agreement.disabled = !enabled.checked || !party.value || pending;
    charge.disabled = !enabled.checked || !party.value || !agreement.value || pending;
    if (!enabled.checked) { agreement.value = ''; charge.value = ''; }
  };
  const getOptions = async (url, params, current) => {
    const response = await fetch(url + '?' + params.toString(), {
      credentials: 'same-origin', signal: controller.signal, headers: {Accept: 'application/json'}
    });
    if (!response.ok) throw new Error('unavailable');
    const data = await response.json();
    if (current !== sequence) return null;
    if (!Array.isArray(data.options)) throw new Error('invalid');
    return data;
  };
  const load = async (loadAgreements, preserve = false) => {
    const selectedAgreement = preserve ? agreement.value : '';
    const selectedCharge = preserve ? charge.value : '';
    const current = ++sequence;
    if (controller) controller.abort();
    if (loadAgreements) blank(agreement, party.value ? 'Επιλέξτε συμφωνία' : 'Επιλέξτε πρώτα συναλλασσόμενο');
    blank(charge, 'Επιλέξτε πρώτα συμφωνία');
    status.textContent = '';
    if (!party.value || !enabled.checked) { pending = false; state(); return; }
    controller = new AbortController(); pending = true; state();
    status.textContent = 'Φόρτωση επιλογών…';
    const params = new URLSearchParams({entity_id: party.value, direction: form.dataset.direction});
    try {
      if (loadAgreements) {
        const data = await getOptions(form.dataset.agreementUrl, params, current);
        if (!data) return;
        for (const row of data.options) agreement.add(new Option(row.label, row.value));
        if (selectedAgreement && data.options.some(row => row.value === selectedAgreement)) agreement.value = selectedAgreement;
      }
      if (!agreement.value) { status.textContent = 'Επιλέξτε συμφωνία για να εμφανιστούν οι χρεώσεις της.'; return; }
      params.set('agreement_id', agreement.value);
      if (day.value) params.set('transaction_date', day.value);
      const data = await getOptions(form.dataset.chargeUrl, params, current);
      if (!data) return;
      blank(charge, 'Επιλέξτε χρέωση');
      for (const row of data.options) charge.add(new Option(row.label, row.value));
      if (selectedCharge && data.options.some(row => row.value === selectedCharge)) charge.value = selectedCharge;
      status.textContent = data.options.length ? '' : 'Δεν υπάρχουν ανεξόφλητες χρεώσεις για αυτή τη συμφωνία και ημερομηνία.';
    } catch (error) {
      if (current !== sequence || error.name === 'AbortError') return;
      blank(charge, 'Οι χρεώσεις δεν φορτώθηκαν');
      status.textContent = 'Οι επιλογές δεν φορτώθηκαν. Επιλέξτε ξανά συναλλασσόμενο ή συμφωνία.';
    } finally {
      if (current === sequence) { pending = false; state(); }
    }
  };
  if (agreement.value || charge.value) enabled.checked = true;
  party.addEventListener('change', () => load(true));
  enabled.addEventListener('change', () => load(true, true));
  agreement.addEventListener('change', () => load(false));
  day.addEventListener('change', () => load(false, true));
  form.addEventListener('submit', event => {
    if (enabled.checked && (pending || !agreement.value || !charge.value)) {
      event.preventDefault();
      status.textContent = pending ? 'Περιμένετε να φορτωθούν οι επιλογές.' : 'Επιλέξτε συμφωνία και συγκεκριμένη χρέωση ή καταργήστε την αντιστοίχιση.';
      if (!pending) (agreement.value ? charge : agreement).focus();
    }
  });
  state();
});
