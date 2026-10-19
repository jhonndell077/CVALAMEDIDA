const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const {parseHTML} = require('linkedom');
function setup() {
  const {document} = parseHTML(fs.readFileSync('static/index.html', 'utf8'));
  let gmail = false, drive = false, timer, grantFailure = false, driveFailure = false, release, saveFailure = false, syncFailure = false;
  const calls = [];
  const window = {cvGmail: {isConnected: () => gmail, connect: async () => {gmail = true; drive = true;}},
    cvDrive: {isConnected: () => drive, connect: async () => {drive = true;}, verify: async () => {if (driveFailure) throw new Error('Drive no disponible');}},
    setInterval: fn => {timer = fn;}};
  vm.runInNewContext(fs.readFileSync('static/required-sync.js', 'utf8'), {window, document});
  window.cvRequiredSync.configure({required: true, verifySession: async () => {
    if (release) await new Promise(resolve => {release.resolve = resolve;});
    if (grantFailure) throw new Error('Permiso revocado');
  }, synchronize: async () => {calls.push('sync'); if (syncFailure) throw new Error('Falló la sincronización');},
  persist: async () => {calls.push('save'); if (saveFailure) throw new Error('Falló el guardado'); return {completed:true};}});
  return {document, calls, gate: window.cvRequiredSync, timer: () => timer(), expire: () => {gmail = false;},
    failSave: value => {saveFailure = value;}, failSync: value => {syncFailure = value;},
    failGrant: value => {grantFailure = value;}, failDrive: value => {driveFailure = value;},
    defer: () => {release = {}; return release;}};
}
const settle = () => new Promise(resolve => setImmediate(resolve));
test('verifica una vez, sincroniza y guarda antes de ocultar; caducidad posterior usa el flotante', async () => {
  const s = setup(), button = id => s.document.querySelector(id);
  assert.equal(s.gate.ready(), false);
  s.gate.session({uid:'a'});
  s.gate.account({initial_sync_completed:false});
  assert.equal(button('#verify-drive').disabled, true);
  button('#verify-session-gmail').click(); await settle();
  assert.equal(s.gate.ready(), false);
  assert.equal(button('#verify-drive').disabled, false);
  button('#verify-drive').click(); await settle();
  assert.equal(s.gate.ready(), true);
  assert.equal(button('#job-panel').inert, false);
  assert.equal(button('#required-sync').hidden, true);
  assert.deepEqual(s.calls, ['sync','save']);
  s.expire(); s.timer();
  assert.equal(s.gate.ready(), true);
  assert.equal(button('#required-sync').hidden, true);
});
test('errores no habilitan el formulario; permite reintentar', async () => {
  const s = setup(), click = id => s.document.querySelector(id).click();
  s.gate.session({uid:'a'}); s.gate.account({initial_sync_completed:false}); s.failGrant(true);
  click('#verify-session-gmail'); await settle();
  assert.equal(s.gate.ready(), false);
  assert.match(s.document.querySelector('#verify-session-status').textContent, /Error/);
  s.failGrant(false); click('#verify-session-gmail'); await settle();
  s.failDrive(true); click('#verify-drive'); await settle();
  assert.equal(s.gate.ready(), false);
  s.failDrive(false); click('#verify-drive'); await settle();
  assert.equal(s.gate.ready(), true);
  s.gate.session({uid:'b'});
  assert.equal(s.gate.ready(), false);
});
test('una verificación de otra cuenta no valida la sesión nueva', async () => {
  const s = setup(); s.gate.session({uid:'a'}); s.gate.account({initial_sync_completed:false});
  const pending = s.defer();
  s.document.querySelector('#verify-session-gmail').click(); await settle();
  s.gate.session({uid:'b'}); pending.resolve(); await settle();
  assert.equal(s.document.querySelector('#verify-drive').disabled, true);
  assert.equal(s.gate.ready(), false);
});
test('cuentas verificadas entran sin autorizaciones en memoria, también en otra sesión', () => {
  const s = setup(); s.gate.session({uid:'registered'});
  assert.equal(s.gate.ready(), false);
  s.gate.account({initial_sync_completed:true});
  assert.equal(s.gate.ready(), true);
  assert.equal(s.document.querySelector('#required-sync').hidden, true);
  s.gate.session(null); assert.equal(s.gate.ready(), false);
  s.gate.session({uid:'registered'}); s.gate.account({initial_sync_completed:true});
  assert.equal(s.gate.ready(), true);
  s.gate.session({uid:'new'}); s.gate.account({initial_sync_completed:false});
  assert.equal(s.gate.ready(), false);
});
test('fallar sincronización o persistencia conserva los requisitos y permite reintentar', async () => {
  const s = setup(); s.gate.session({uid:'a'}); s.gate.account({initial_sync_completed:false});
  const click = id => s.document.querySelector(id).click();
  click('#verify-session-gmail'); await settle();
  s.failSync(true); click('#verify-drive'); await settle();
  assert.deepEqual(s.calls,['sync']); assert.equal(s.gate.ready(),false);
  s.failSync(false); s.failSave(true); click('#verify-drive'); await settle();
  assert.equal(s.gate.ready(),false); assert.equal(s.document.querySelector('#required-sync').hidden,false);
  s.failSave(false); click('#verify-drive'); await settle();
  assert.equal(s.gate.ready(),true);
});
