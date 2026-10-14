/* Each repeated value stays a separate record from input through storage. */
window.cvRepeaters = (() => {
  const definitions = {
    phones: ['teléfono', [['value', 'Teléfono', 'tel', 100]]],
    skills: ['habilidad', [['value', 'Habilidad', 'text', 300]]],
    responsibilities: ['función', [['value', 'Función realizada', 'text', 1500]]],
    technologies: ['herramienta', [['value', 'Herramienta o tecnología', 'text', 200]]],
    education: ['estudio', [['title', 'Título o nivel', 'text', 200, true], ['institution', 'Institución'], ['date', 'Fecha o período']]],
    courses: ['curso', [['title', 'Nombre del curso', 'text', 200, true], ['institution', 'Institución'], ['date', 'Fecha o período']]],
    experiences: ['experiencia', [['title', 'Puesto', 'text', 200, true], ['employer', 'Empresa o empleador'], ['category', 'Área o sector'], ['start_date', 'Fecha de inicio'], ['end_date', 'Fecha de finalización']]],
    projects: ['proyecto', [['title', 'Nombre del proyecto', 'text', 200, true], ['description', 'Descripción', 'textarea', 2000, true], ['url', 'Enlace · opcional', 'url', 1000]]],
    references: ['referencia', [['name', 'Nombre', 'text', 200, true], ['role', 'Cargo o relación', 'text', 200, true], ['phone', 'Teléfono', 'tel', 100, true]]],
  };
  function mount(host) {
    if (host.repeater) return host.repeater;
    const kind = host.dataset.repeater, [singular, fields] = definitions[kind];
    const rows = document.createElement('div'); rows.className = 'repeat-rows'; host.append(rows);
    const add = document.createElement('button'); add.type = 'button'; add.className = 'button button-secondary repeat-add';
    add.textContent = `＋ Añadir ${singular}`; host.append(add);
    const limit = kind === 'phones' ? 10 : 40;
    function addRow(value = {}, focus = false) {
      if (rows.children.length >= limit) return;
      if (typeof value === 'string') value = {value};
      const row = document.createElement('div'); row.className = 'repeat-row';
      const heading = document.createElement('div'); heading.className = 'repeat-heading';
      const title = document.createElement('strong'); title.textContent = singular[0].toUpperCase() + singular.slice(1); heading.append(title);
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'profile-remove';
      remove.textContent = 'Quitar'; remove.setAttribute('aria-label', `Quitar ${singular}`);
      remove.addEventListener('click', () => { row.remove(); add.disabled = false; add.focus(); }); heading.append(remove); row.append(heading);
      for (const [key, labelText, type = 'text', max = 200, required = false] of fields) {
        const label = document.createElement('label'); label.textContent = labelText;
        const input = document.createElement(type === 'textarea' ? 'textarea' : 'input');
        if (type !== 'textarea') input.type = type;
        input.dataset.field = key; input.maxLength = max; input.required = required;
        input.value = value[key] || ''; label.append(input); row.append(label);
      }
      const nested = kind === 'experiences' ? 'responsibilities' : kind === 'projects' ? 'technologies' : null;
      if (nested) { const group = document.createElement('div'); group.dataset.repeater = nested; row.append(group); mount(group).set(value[nested] || []); }
      rows.append(row); add.disabled = rows.children.length >= limit;
      if (focus) row.querySelector('input,textarea').focus();
    }
    add.addEventListener('click', () => addRow({}, true));
    host.repeater = {
      get() { return [...rows.children].map(row => {
        const value = {};
        for (const input of row.querySelectorAll(':scope > label > [data-field]')) value[input.dataset.field] = input.value.trim();
        for (const nested of row.querySelectorAll(':scope > [data-repeater]')) value[nested.dataset.repeater] = nested.repeater.get();
        return Object.hasOwn(value, 'value') ? value.value : value;
      }).filter(value => typeof value === 'string' ? Boolean(value) : Object.values(value).some(v => Array.isArray(v) ? v.length : v)); },
      set(values) { rows.replaceChildren(); add.disabled = false; values.forEach(value => addRow(value)); },
    };
    return host.repeater;
  }
  function roots(parent) { return [...parent.querySelectorAll('[data-repeater]')].filter(host => !host.parentElement.closest('[data-repeater]')); }
  function collect(parent) { return Object.fromEntries(roots(parent).filter(host => !host.closest('[hidden]')).map(host => [host.dataset.repeater, mount(host).get()])); }
  function reset(parent) { roots(parent).forEach(host => mount(host).set([])); }
  document.querySelectorAll('[data-repeater]').forEach(mount);
  return {mount, collect, reset};
})();
