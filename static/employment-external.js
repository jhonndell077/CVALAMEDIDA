(function (root) {
  'use strict';
  const sources = Object.freeze({
    aldaba: ['Aldaba', 'https://www.aldaba.com/'],
    tuempleord: ['TuEmpleoRD', 'https://tuempleord.do/'],
    tuvacanterd: ['TuVacanteRD', 'https://tuvacanterd.com/'],
    computrabajo: ['Computrabajo RD', 'https://do.computrabajo.com/'],
    rdtrabaja: ['RD Trabaja', 'https://rdtrabaja.mt.gob.do/'],
    chiripas: ['Chiripas', 'https://chiripas.com/'],
  });
  function vacancy(source, url, title, description) {
    if (!Object.hasOwn(sources, source)) throw new Error('Selecciona una fuente.');
    const parsed = new URL(url), portal = new URL(sources[source][1]);
    if (parsed.protocol !== 'https:' || parsed.hostname !== portal.hostname || parsed.username || parsed.password || parsed.port) {
      throw new Error('Usa el enlace HTTPS original de la fuente seleccionada.');
    }
    if (!title.trim() || !description.trim() || title.length > 160 || description.length > 40000) throw new Error('Indica cargo y descripción dentro de los límites.');
    const text = `${title.trim()}\n\n${description.trim()}`;
    if (text.length > 40000) throw new Error('Cargo y descripción deben sumar como máximo 40000 caracteres.');
    return {url: parsed.href, text};
  }
  if (typeof module !== 'undefined') module.exports = {sources, vacancy};
  if (!root.document) return;
  const form = root.document.querySelector('#employment-external-form');
  if (!form) return;
  const field = name => form.elements.namedItem(name);
  const status = root.document.querySelector('#employment-external-status');
  for (const [id, [name]] of Object.entries(sources)) {
    const option = root.document.createElement('option'); option.value = id; option.textContent = name; field('source').append(option);
  }
  const original = root.document.querySelector('#employment-external-original');
  root.addEventListener('cv-employment-session', () => {
    for (const name of ['url', 'title', 'description']) field(name).value = '';
    original.hidden = true; original.removeAttribute('href');
    status.textContent = 'Sesión actualizada. Introduce una vacante para adaptar tu CV.';
  });
  form.addEventListener('input', () => {original.hidden = true; original.removeAttribute('href'); status.textContent = 'Vacante modificada: vuelve a preparar el CV.';});
  form.addEventListener('submit', event => {
    event.preventDefault();
    try {
      const selected = vacancy(field('source').value, field('url').value, field('title').value, field('description').value);
      root.dispatchEvent(new root.CustomEvent('cv-employment-vacancy', {detail: {text: selected.text}, cancelable: true}));
      original.href = selected.url; original.hidden = false;
      status.textContent = 'Descripción preparada en el generador. Genera y revisa el CV antes de abrir la vacante. Distancia sin verificar; país y requisitos deben revisarse en el portal. No se ha enviado una candidatura.';
    } catch (error) {status.textContent = error.message;}
  });
  original.addEventListener('click', () => {status.textContent = 'Apertura solicitada al navegador. Completa la solicitud en el portal; el envío no está confirmado.';});
})(typeof window !== 'undefined' ? window : globalThis);
