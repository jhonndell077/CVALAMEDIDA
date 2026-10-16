(() => {
  'use strict';
  const dialog = document.querySelector('#profile-category-dialog');
  const content = document.querySelector('#profile-category-content');
  const search = document.querySelector('#profile-category-search');
  const results = document.querySelector('#profile-category-results');
  const title = document.querySelector('#profile-category-title');
  const footer = document.querySelector('#profile-category-actions');
  let activeKey = null, card = null, opener = null, moved = [], controls = [];
  const normalize = text => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase();
  function restoreContent() {
    if (card) { card.append(...moved); card.removeAttribute('open'); }
    moved = [];
  }
  function filter() {
    const terms = normalize(search.value).trim().split(/\s+/).filter(Boolean);
    const body = content.querySelector('.profile-node-body') || content.querySelector('.profile-fields');
    const rows = body ? [...body.children].filter(node => node.matches('.profile-entry, .profile-field')) : [];
    let count = 0;
    rows.forEach(row => {
      const text = normalize(row.textContent + ' ' + [...row.querySelectorAll('input,textarea,select')].map(input => input.value).join(' '));
      const match = terms.every(term => text.includes(term));
      row.hidden = !match;
      if (match) count++;
      if (terms.length && row.tagName === 'DETAILS') row.open = match;
    });
    results.textContent = rows.length ? `${count} de ${rows.length} registros` : 'Esta categoría todavía no tiene registros.';
    document.querySelector('#profile-category-empty').hidden = count > 0 || rows.length === 0;
  }
  function mount() {
    card = [...document.querySelectorAll('#profile-tree > .profile-node')].find(node => node.dataset.category === activeKey);
    if (!card) { dialog.close(); return; }
    title.textContent = card.querySelector('.profile-card-title').textContent;
    moved = [...card.children].filter(node => node.tagName !== 'SUMMARY');
    content.append(...moved);
    card.removeAttribute('open');
    filter();
  }
  document.querySelector('#profile-tree').addEventListener('click', event => {
    const summary = event.target.closest('summary');
    const next = summary?.parentElement;
    if (!next?.matches('#profile-tree > .profile-node')) return;
    event.preventDefault();
    opener = summary;
    activeKey = next.dataset.category;
    search.value = '';
    controls = ['profile-status','profile-error','save-profile','discard-profile'].map(id => {
      const node = document.getElementById(id), marker = document.createComment(id);
      node.before(marker); footer.append(node); return {node,marker};
    });
    mount(); dialog.showModal(); search.focus();
  });
  search.addEventListener('input', filter);
  document.querySelector('#profile-category-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    restoreContent();
    controls.forEach(({node,marker}) => { marker.replaceWith(node); }); controls = [];
    activeKey = null;
    const next = card?.querySelector('summary');
    (opener?.isConnected ? opener : next)?.focus(); card = null;
  });
  window.cvProfileDialog = {
    reset() {
      restoreContent();
      controls.forEach(({node,marker}) => { marker.replaceWith(node); }); controls = [];
      activeKey = null; card = null; opener = null;
      content.replaceChildren(); search.value = ''; title.textContent = ''; results.textContent = '';
      if (dialog.open) dialog.close();
    },
    beforeRender() { if (activeKey) restoreContent(); },
    afterRender(revealPath) {
      if (!activeKey) return;
      if (revealPath) search.value = '';
      mount();
      if (revealPath) {
        const entry = [...content.querySelectorAll('[data-profile-path]')].find(node => node.dataset.profilePath === JSON.stringify(revealPath));
        entry?.querySelector('input,textarea')?.focus();
      }
    },
  };
})();
