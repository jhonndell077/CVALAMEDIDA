const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
test('creating the CV renders it and automatically dispatches Gmail once', async () => {
  const calls = [], elements = new Map(); let handler;
  const $ = selector => {
    if (!elements.has(selector)) elements.set(selector, {addEventListener: (_, callback) => {handler = callback;}});
    return elements.get(selector);
  };
  const context = vm.createContext({$, window: {}, state: {analysis: {}}, clearError() {}, setBusy() {},
    requestJson: async () => ({draft: {position: 'Chef'}}), renderDraft: async () => calls.push('preview'),
    analysisPanel: {}, cvPanel: {}, setActiveStep() {}, sendApplicationGmail: async () => calls.push('gmail')});
  const source = fs.readFileSync('static/app.js', 'utf8');
  vm.runInContext(source.slice(source.indexOf('$("#create-button").addEventListener'), source.indexOf('function addPreviewSection')), context);
  await handler({currentTarget: {}});
  assert.deepEqual(calls, ['preview', 'gmail']);
  assert.equal(context.window.cvDraftAnalyses.get(context.state.draft), context.state.analysis);
  assert.equal(context.cvPanel.hidden, false);
  assert.ok(!fs.readFileSync('static/index.html', 'utf8').includes('id="send-gmail"'));
});

test('multiple detected recipients require manual selection before any connection or send', async () => {
  const elements = new Map();
  const $ = selector => {
    if (!elements.has(selector)) elements.set(selector, {value: selector === '#application-email' ? 'one@example.com' : '', hidden: true});
    return elements.get(selector);
  };
  const context = vm.createContext({$, window: {}, state: {draft: {}, analysis: {vacancy: {application_emails: ['one@example.com', 'two@example.com']}}}});
  const source = fs.readFileSync('static/app.js', 'utf8');
  vm.runInContext(source.slice(source.indexOf('async function sendApplicationGmail('), source.indexOf("$('#retry-gmail').addEventListener")), context);
  await context.sendApplicationGmail();
  assert.match($('#application-send-status').textContent, /varios correos/);
  assert.equal($('#retry-gmail').hidden, false);
});
