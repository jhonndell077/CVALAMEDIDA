const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const {parseHTML} = require('linkedom');
test('manual index resolves all nine chapters and preserves diagrams and send guidance', () => {
  const {document} = parseHTML(fs.readFileSync('static/manual.html', 'utf8'));
  const links = [...document.querySelectorAll('.index nav a')];
  assert.equal(links.length, 9);
  links.forEach(link => assert.ok(document.querySelector(link.getAttribute('href'))));
  assert.equal(document.querySelectorAll('h1').length, 1);
  assert.equal(document.querySelectorAll('figure img[alt]').length, 2);
  assert.match(document.querySelector('#cv').textContent, /puede enviar el mensaje/);
  assert.doesNotMatch(document.querySelector('#telegram').textContent, /Ya pulsé Iniciar|Confirmar esta cuenta/);
});
test('PDF control opens printing and restores initially closed help after printing', () => {
  const {document} = parseHTML(fs.readFileSync('static/manual.html', 'utf8'));
  const events = {}; let printed = 0;
  const entries = [...document.querySelectorAll('details')];
  entries[0].open = true; entries[0].setAttribute('open','');
  const window = {addEventListener: (name, fn) => events[name] = fn, print: () => printed++};
  vm.runInNewContext(fs.readFileSync('static/manual.js', 'utf8'), {document, window});
  document.getElementById('manual-print').click(); assert.equal(printed, 1);
  events.beforeprint(); assert.ok(entries.every(entry => entry.open));
  events.afterprint(); assert.equal(entries[0].open, true);
  assert.ok(entries.slice(1).every(entry => !entry.open));
});
