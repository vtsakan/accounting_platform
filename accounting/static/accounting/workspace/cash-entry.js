/* Party-scoped agreement choices. Server validation owns all financial writes. */
document.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('[data-cash-entry]');
  if (!form) return;
  const party = form.querySelector('[name="entity"]');
  const agreement = form.querySelector('[name="agreement"]');
  const enabled = form.querySelector('[name="settle_agreement"]');
  const description = form.querySelector('[name="description"]');
  const status = form.querySelector('[data-agreement-status]');
  if (!party || !agreement || !enabled || !description || !status) return;
  let sequence = 0;
  let controller;
  let pending = false;

  const blank = (text) => {
    agreement.replaceChildren(new Option(text, ''));
  };
  const state = () => {
    agreement.required = enabled.checked;
    description.required = !enabled.checked;
    description.placeholder = enabled.checked ? 'Συμπληρώνεται από τη συμφωνία' : '';
    agreement.disabled = !enabled.checked || !party.value || pending;
    if (!enabled.checked) agreement.value = '';
  };
  const load = async (preserve) => {
    const selected = preserve ? agreement.value : '';
    const current = ++sequence;
    if (controller) controller.abort();
    blank(party.value ? 'Επιλέξτε συμφωνία' : 'Επιλέξτε πρώτα συναλλασσόμενο');
    status.textContent = '';
    if (!party.value || !enabled.checked) {
      pending = false;
      state();
      return;
    }
    controller = new AbortController();
    pending = true;
    state();
    status.textContent = 'Φόρτωση συμφωνιών…';
    const params = new URLSearchParams({entity_id: party.value, direction: form.dataset.direction});
    try {
      const response = await fetch(form.dataset.agreementUrl + '?' + params.toString(),
        {credentials: 'same-origin', signal: controller.signal, headers: {Accept: 'application/json'}});
      if (!response.ok) throw new Error('unavailable');
      const data = await response.json();
      if (current !== sequence) return;
      if (!Array.isArray(data.options)) throw new Error('invalid');
      for (const row of data.options) agreement.add(new Option(row.label, row.value));
      if (selected && data.options.some(row => row.value === selected)) agreement.value = selected;
      status.textContent = data.options.length ? '' : 'Δεν υπάρχουν διαθέσιμες συμφωνίες για τον συναλλασσόμενο.';
    } catch (error) {
      if (current !== sequence || error.name === 'AbortError') return;
      blank('Οι συμφωνίες δεν φορτώθηκαν');
      status.textContent = 'Οι συμφωνίες δεν φορτώθηκαν. Επιλέξτε ξανά τον συναλλασσόμενο ή ανανεώστε τη σελίδα.';
    } finally {
      if (current === sequence) {
        pending = false;
        state();
      }
    }
  };
  if (agreement.value) enabled.checked = true;
  party.addEventListener('change', () => load(false));
  enabled.addEventListener('change', () => load(true));
  form.addEventListener('submit', event => {
    if (enabled.checked && (pending || !agreement.value)) {
      event.preventDefault();
      status.textContent = pending ? 'Περιμένετε να φορτωθούν οι συμφωνίες.' : 'Επιλέξτε συμφωνία ή καταργήστε την επιλογή «Αφορά συμφωνία».';
      agreement.focus();
    }
  });
  // Retain server-rendered choices, including an exact replay of an old receipt.
  state();
});
