const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const {parseHTML} = require('linkedom');
function setup() {
  const {document, window} = parseHTML(fs.readFileSync('static/index.html', 'utf8'));
  vm.runInNewContext(fs.readFileSync('static/presentation.js', 'utf8'), {document, window});
  return {document, window};
}
test('public CTAs use the existing vacancy opener without submitting an analysis', () => {
  const {document} = setup(); let opens = 0, submits = 0;
  document.getElementById('open-vacancy').addEventListener('click', () => opens++);
  document.getElementById('analyze-button').addEventListener('click', () => submits++);
  const buttons = [...document.querySelectorAll('[data-presentation-start]')];
  buttons.forEach(button => button.click());
  assert.equal(opens, 2); assert.equal(submits, 0);
});
function sessionSetup(state) {
  const ui = setup();
  const source = fs.readFileSync('static/app.js', 'utf8');
  const start = source.slice(source.indexOf('function startPresentation()'), source.indexOf('const jobPanel ='));
  vm.runInNewContext(start, {state, window: ui.window, $: selector => ui.document.querySelector(selector)});
  let signIns = 0, opens = 0;
  ui.document.getElementById('google-sign-in').addEventListener('click', () => signIns++);
  ui.document.getElementById('open-vacancy').addEventListener('click', () => opens++);
  return {...ui, counts: () => ({signIns, opens})};
}
test('both public CTAs start the existing sign-in when no session is active', () => {
  const ui = sessionSetup({authRequired: true, auth: {currentUser: null}, user: null});
  ui.document.querySelectorAll('[data-presentation-start]').forEach(button => button.click());
  assert.deepEqual(ui.counts(), {signIns: 2, opens: 0});
  assert.equal(ui.document.getElementById('auth-panel').hidden, false);
});
test('both CTAs retain their normal action when signed in and detect a later logout', () => {
  const state = {authRequired: true, auth: {currentUser: {uid: 'fixture'}}, user: {uid: 'fixture'}};
  const ui = sessionSetup(state);
  ui.document.querySelectorAll('[data-presentation-start]').forEach(button => button.click());
  assert.deepEqual(ui.counts(), {signIns: 0, opens: 2});
  state.auth.currentUser = null; // Cached account data must not count as a live session.
  ui.document.querySelector('[data-presentation-start]').click();
  assert.deepEqual(ui.counts(), {signIns: 1, opens: 2});
});
test('CTA keeps local mode usable and safely reveals sign-in while the SDK loads', () => {
  const state = {authRequired: false, auth: null, user: null};
  const ui = sessionSetup(state);
  ui.document.querySelector('[data-presentation-start]').click();
  assert.deepEqual(ui.counts(), {signIns: 0, opens: 1});
  state.authRequired = true;
  let focused = false;
  ui.document.getElementById('google-sign-in').focus = () => focused = true;
  ui.document.querySelector('[data-presentation-start]').click();
  assert.equal(focused, true);
  assert.match(ui.document.getElementById('auth-help').textContent, /preparando el inicio de sesión/);
  assert.deepEqual(ui.counts(), {signIns: 0, opens: 1});
});
test('illustrative preview switches by click and keyboard with matching ARIA state', () => {
  const {document, window} = setup();
  const job = document.getElementById('sample-job-tab'), cv = document.getElementById('sample-cv-tab');
  cv.click();
  assert.equal(cv.getAttribute('aria-selected'), 'true'); assert.equal(document.getElementById('sample-job').hidden, true);
  assert.equal(document.getElementById('sample-cv').hidden, false);
  const event = new window.Event('keydown', {cancelable: true}); event.key = 'ArrowRight'; cv.dispatchEvent(event);
  assert.equal(job.getAttribute('aria-selected'), 'true'); assert.equal(document.getElementById('sample-cv').hidden, true);
});
test('presentation preserves operational IDs and has navigable public anchors', () => {
  const {document} = setup();
  assert.equal(document.querySelectorAll('h1').length, 1);
  for (const id of ['telegram-link','open-onboarding','analyze-button','workspace-menu','job-panel','auth-panel','application-history-panel']) assert.equal(document.querySelectorAll('#' + id).length, 1);
  for (const a of document.querySelectorAll('.presentation-nav a')) assert.ok(document.querySelector(a.getAttribute('href')));
});
