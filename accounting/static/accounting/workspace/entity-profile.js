(() => {
  'use strict';
  const form = document.querySelector('[data-profile-editor]');
  if (!form) return;
  const tabs = Array.from(form.querySelectorAll('[data-profile-tab]'));
  const panels = Array.from(form.querySelectorAll('[data-profile-panel]'));
  const activate = (key, focus = false) => {
    panels.forEach(panel => { panel.hidden = panel.dataset.profilePanel !== key; });
    tabs.forEach(tab => { const on = tab.dataset.profileTab === key; tab.setAttribute('aria-selected', String(on)); tab.tabIndex = on ? 0 : -1; if (on && focus) tab.focus(); });
  };
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activate(tab.dataset.profileTab));
    tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      if (next !== undefined) { event.preventDefault(); activate(tabs[next].dataset.profileTab, true); }
    });
  });
  const firstError = panels.find(panel => panel.querySelector('.errorlist'));
  activate(firstError ? firstError.dataset.profilePanel : 'basic');
  form.addEventListener('invalid', event => { const panel = event.target.closest('[data-profile-panel]'); if (panel) activate(panel.dataset.profilePanel); }, true);
  const shared = form.elements.namedItem('spouse_inherit_contacts');
  const updateContacts = () => {
    if (!shared) return;
    form.querySelectorAll('[data-spouse-contact]').forEach(wrapper => {
      const field = wrapper.querySelector('input');
      const source = form.elements.namedItem(wrapper.dataset.spouseContact.slice(7));
      if (!field || !source) return;
      if (shared.checked) field.value = source.value;
      field.readOnly = shared.checked;
      wrapper.dataset.inherited = String(shared.checked);
    });
  };
  if (shared) { shared.addEventListener('change', updateContacts); updateContacts(); }
  ['address', 'city', 'postal_code', 'phone_number', 'email'].forEach(name => { const field = form.elements.namedItem(name); if (field) field.addEventListener('input', updateContacts); });
  const tagInput = form.elements.namedItem('tags');
  const preview = form.querySelector('[data-tag-preview]');
  if (tagInput && preview) {
    const updateTags = () => { preview.replaceChildren(); Array.from(new Set(tagInput.value.split(/[,;\n]/).map(tag => tag.trim()).filter(Boolean))).slice(0, 25).forEach(tag => { const span = document.createElement('span'); span.className = 'profile-tag'; span.textContent = tag; preview.appendChild(span); }); };
    tagInput.addEventListener('input', updateTags); updateTags();
  }
})();
