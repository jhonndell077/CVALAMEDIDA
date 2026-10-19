const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {parseHTML} = require('linkedom');
function setup() {
  const {window, document} = parseHTML(fs.readFileSync('static/index.html', 'utf8'));
  for (const dialog of document.querySelectorAll('dialog')) {
    dialog.showModal = () => {dialog.open = true; dialog.setAttribute('open', '');};
    dialog.close = () => {dialog.open = false; dialog.removeAttribute('open'); dialog.dispatchEvent(new window.Event('close'));};
  }
  vm.runInNewContext(fs.readFileSync('static/workspace-navigation.js', 'utf8'), {window, document});
  return {window, document, get: id => document.getElementById(id)};
}
test('sidebar relocates original services and panels without duplicate controls', () => {
  const {document, get} = setup();
  for (const id of ['telegram-panel', 'bank-panel']) assert.ok(get('workspace-sidebar').contains(get(id)));
  assert.ok(get('vacancy-window').contains(get('job-panel')));
  assert.ok(get('history-window').contains(get('application-history-panel')));
  for (const id of ['telegram-link', 'select-account-folders', 'open-onboarding', 'analyze-button']) assert.equal(document.querySelectorAll('#' + id).length, 1);
  assert.ok(document.querySelector('main #analysis-panel'));
});
test('menu opens vacancy without submitting and retains text across closing', () => {
  const {get} = setup(); let submissions = 0;
  get('analyze-button').addEventListener('click', () => submissions++);
  get('workspace-menu').click(); assert.equal(get('workspace-menu').getAttribute('aria-expanded'), 'true');
  get('open-vacancy').click(); assert.equal(get('workspace-sidebar').open, false); assert.equal(get('vacancy-window').open, true);
  get('job-text').value = 'Cocinero';
  get('vacancy-window').querySelector('[data-workspace-close]').click();
  get('open-vacancy').click(); assert.equal(get('job-text').value, 'Cocinero'); assert.equal(submissions, 0);
});
test('history opens expanded without triggering a refresh', () => {
  const {get} = setup(); let refresh = 0;
  get('refresh-application-history').addEventListener('click', () => refresh++);
  get('open-history').click(); assert.equal(get('history-window').open, true);
  assert.equal(get('application-history-details').open, true); assert.equal(refresh, 0);
});
test('step transitions close vacancy and returning from analysis reopens it', () => {
  const {window, get} = setup();
  window.cvWorkspace.showStep(1); assert.ok(!get('vacancy-window').open);
  get('open-vacancy').click(); window.cvWorkspace.showStep(2); assert.equal(get('vacancy-window').open, false);
  window.cvWorkspace.showStep(1); assert.equal(get('vacancy-window').open, true);
});
test('Escape closes menu and updates its expanded state', () => {
  const {window, get} = setup();
  get('workspace-menu').click();
  get('workspace-sidebar').dispatchEvent(new window.Event('cancel', {cancelable: true}));
  assert.equal(get('workspace-sidebar').open, false);
  assert.equal(get('workspace-menu').getAttribute('aria-expanded'), 'false');
});
test('incomplete account setup keeps the vacancy form behind the existing sign-in flow', () => {
  const {window, get} = setup(); let prompts = 0;
  window.cvRequiredSync = {ready: () => false};
  get('auth-panel').scrollIntoView = () => prompts++;
  get('workspace-menu').click(); get('open-vacancy').click();
  assert.equal(get('workspace-sidebar').open, false);
  assert.ok(!get('vacancy-window').open); assert.equal(prompts, 1);
});
