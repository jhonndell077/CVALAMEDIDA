const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const displayed = [];
const elements = new Map();
function element(selector) {
  if (!elements.has(selector)) {
    const node = {hidden: true, focus() {}, addEventListener() {}};
    Object.defineProperty(node, 'textContent', {set(value) {
      this.text = value;
      if (selector === '#loading-percent') displayed.push(Number(value.replace('%', '')));
    }, get() {return this.text;}});
    elements.set(selector, node);
  }
  return elements.get(selector);
}
let clock = 0, sequence = 0;
const frames = new Map();
const context = {window: {}, performance: {now: () => clock},
  document: {querySelector: element, querySelectorAll: () => [], activeElement: null,
    body: {classList: {add() {}, remove() {}}}},
  requestAnimationFrame: callback => {frames.set(++sequence, callback); return sequence;},
  cancelAnimationFrame: id => frames.delete(id)};
vm.runInNewContext(fs.readFileSync('static/loading.js', 'utf8'), context);
function frame(timestamp) {
  clock = timestamp;
  const callbacks = [...frames.values()]; frames.clear();
  callbacks.forEach(callback => callback(timestamp));
}
(async () => {
  const loader = context.window.cvLoading;
  const finish = loader.start('Sincronizando');
  clock = 100; finish.update(40, 'Etapa confirmada'); frame(200);
  assert.equal(element('#loading-percent').text, '40%');
  assert.deepEqual([...new Set(displayed)], Array.from({length: 40}, (_, i) => i + 1));
  frame(20000); assert.equal(element('#loading-percent').text, '40%');
  finish.update(3, 'Reconsulta'); assert.equal(element('#loading-percent').text, '40%');
  const nested = loader.start('Conectando'); nested();
  assert.equal(element('#loading-percent').text, '40%');
  finish.update(100, 'Respuesta'); frame(21000);
  assert.equal(element('#loading-percent').text, '99%');
  const confirmation = finish.complete();
  assert.equal(element('#loading-percent').text, '100%');
  frame(21016); frame(21032); await confirmation; finish();
  assert.equal(element('#loading-overlay').hidden, true);
  displayed.length = 0;
  await assert.rejects(loader.run('Error', async update => {update(60, 'Procesando'); throw Error('fallo');}));
  assert.equal(displayed.includes(100), false);
  assert.equal(frames.size, 0);
  console.log('Loading: consecutive confirmed percentages, no autonomous advancement, nested state, success and failure verified.');
})().catch(error => {console.error(error); process.exitCode = 1;});
