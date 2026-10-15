const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
async function main() {
  let focused = 0;
  const focus = {isConnected: true, disabled: false, focus() {focused++;}};
  const overlay = {hidden: true, focus() {}};
  const label = {};
  const control = {addEventListener(){}};
  const background = [{inert: false}, {inert: true}];
  const classes = new Set();
  const document = {
    activeElement: focus,
    body: {classList: {add: key => classes.add(key), remove: key => classes.delete(key)}},
    querySelector: key => key === '#loading-overlay' ? overlay : key === '#loading-label' ? label : control,
    querySelectorAll: () => background,
  };
  const window = {};
  vm.runInNewContext(fs.readFileSync('static/loading.js', 'utf8'), {window, document, performance:{now:()=>0}, requestAnimationFrame:fn=>setImmediate(()=>fn(1000)), cancelAnimationFrame:clearImmediate});
  const loading = window.cvLoading;
  const finishAnalysis = loading.start('Analizando');
  const finishSync = loading.start('Sincronizando banco');
  assert.equal(label.textContent, 'Sincronizando banco', 'Nested work describes the current operation');
  assert.equal(overlay.hidden, false);
  assert.ok(background.every(element => element.inert));
  finishAnalysis();
  finishAnalysis();
  assert.equal(overlay.hidden, false, 'Completing one request never hides another pending request');
  assert.equal(label.textContent, 'Sincronizando banco');
  await finishSync();
  assert.equal(overlay.hidden, true);
  assert.deepEqual(background.map(element => element.inert), [false, true]);
  assert.equal(classes.size, 0);
  assert.equal(focused, 1);
  const result = await loading.run('Generando Hoja de vida', async () => {
    assert.equal(label.textContent, 'Generando Hoja de vida');
    return 'generated';
  });
  assert.equal(result, 'generated');
  await assert.rejects(loading.run('Guardando PDF', async () => {throw new Error('Network error');}), /Network error/);
  assert.equal(overlay.hidden, true, 'Errors also release the loading window');
  assert.equal(classes.size, 0);
  console.log('Ventana de carga: concurrencia, mensajes, foco y cierre tras errores verificados.');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
