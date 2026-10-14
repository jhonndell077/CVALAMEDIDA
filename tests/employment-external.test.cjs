const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {parseHTML} = require('linkedom');
const {sources, vacancy} = require('../static/employment-external.js');

test('seis portales externos; rechaza destinos ajenos y credenciales', () => {
  assert.equal(Object.keys(sources).length, 6);
  for (const [id, [, url]] of Object.entries(sources)) assert.equal(vacancy(id, url, 'Cargo', 'Datos').url, url);
  for (const url of ['https://chiripas.com.evil.invalid/', 'javascript:alert(1)', 'https://user:pass@chiripas.com/', 'http://chiripas.com/']) {
    assert.throws(() => vacancy('chiripas', url, 'Cargo', 'Datos'));
  }
  assert.throws(() => vacancy('unknown', 'https://chiripas.com/', 'Cargo', 'Datos'));
  assert.throws(() => vacancy('chiripas', 'https://chiripas.com/', '', 'Datos'));
});

test('interfaz etiquetada transfiere texto al generador sin consultar portales ni declarar envío', () => {
  const {window} = parseHTML(fs.readFileSync('static/index.html', 'utf8'));
  const form = window.document.querySelector('#employment-external-form');
  const fields = Object.fromEntries([...form.querySelectorAll('[name]')].map(element => [element.name, element]));
  Object.defineProperty(form, 'elements', {value: {namedItem: name => fields[name]}});
  let detail;
  window.addEventListener('cv-employment-vacancy', event => {detail = event.detail;});
  window.fetch = () => {throw new Error('No debe consultar portales');};
  vm.runInNewContext(fs.readFileSync('static/employment-external.js', 'utf8'), {window, URL, Object, Error});
  assert.equal(window.document.querySelectorAll('#employment-external-portals a').length, 6);
  for (const element of Object.values(fields)) assert.ok(element.closest('label'));
  fields.source.querySelector('[value="chiripas"]').setAttribute('selected', ''); fields.url.value = 'https://chiripas.com/empleo';
  fields.title.value = 'Chef'; fields.description.value = '<script>datos de vacante</script>';
  form.dispatchEvent(new window.Event('submit', {cancelable: true}));
  assert.match(detail.text, /Chef/);
  assert.match(detail.text, /<script>/); // Texto, nunca HTML ejecutado.
  const original = window.document.querySelector('#employment-external-original');
  assert.equal(original.hidden, false);
  assert.equal(original.rel, 'noopener noreferrer');
  assert.match(window.document.querySelector('#employment-external-status').textContent, /Distancia sin verificar/);
  form.dispatchEvent(new window.Event('input'));
  assert.equal(original.hidden, true);
  assert.equal(original.hasAttribute('href'), false);
  window.dispatchEvent(new window.CustomEvent('cv-employment-session'));
  for (const name of ['url', 'title', 'description']) assert.equal(fields[name].value, '');
});
