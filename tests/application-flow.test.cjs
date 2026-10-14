const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup() {
  const elements = new Map();
  const $ = selector => {
    if (!elements.has(selector)) elements.set(selector, { value: '', textContent: '', addEventListener() {} });
    return elements.get(selector);
  };
  const calls = [];
  const popup = { opener: {}, location: {}, close() { this.closed = true; } };
  const state = { draft: { position: 'Chef & cocina / turno A', candidate: { name: 'Candidato de prueba' } }, applications: [] };
  const context = vm.createContext({ $, state, URLSearchParams, Date, crypto: { randomUUID: () => 'test-application' },
    authenticatedHeaders: v => v, setBusy() {},
    window: { cvGmail: {connect: async () => {}, headers: () => ({'X-Gmail-Access-Token': 'test-token'}), reset() {}}, cvDrive: { isConnected: () => true, headers: () => ({}), connect: async () => {} },
      open: () => { calls.push('open'); return popup; }, addEventListener() {} },
    download: async () => ({ driveUrl: 'https://drive.google.com/file/d/cv-test/view' }),
    fetch: async (url, options) => { const record = JSON.parse(options.body); calls.push(record); return {ok: true, json: async () => ({entry: url === '/api/gmail/send' ? {...record, position: state.draft.position, status: 'gmail_accepted'} : record})}; },
  });
  context.processFetch = (...args) => context.fetch(...args);
  const source = fs.readFileSync('static/app.js', 'utf8');
  vm.runInContext(source.slice(source.indexOf('async function applicationRequest'), source.indexOf('$("#back-to-job")')), context);
  vm.runInContext('renderApplications = () => {};', context);
  return { context, $, calls, popup, state };
}

(async () => {
  let qa = setup();
  qa.$('#application-email').value = 'empleos@example.com';
  qa.$('#application-message').value = 'Mensaje de postulación';
  await qa.context.prepareApplication('gmail', {});
  assert.equal(qa.calls[0].recipient, 'empleos@example.com');
  assert.equal(qa.calls[0].message, 'Mensaje de postulación');
  assert.equal(qa.state.applications[0].status, 'gmail_accepted');
  assert.equal(qa.state.applications.length, 1);
  await qa.context.sendApplicationGmail();
  assert.equal(qa.calls.length, 1, 'a confirmed automatic send is never repeated');
  assert.ok(!qa.calls.includes('open'), 'Gmail sends through the API instead of opening a compose window');

  qa = setup();
  qa.$('#application-phone').value = '809-555-0100';
  const saveHistory = qa.context.fetch;
  qa.context.fetch = (...args) => {
    assert.equal(qa.popup.location.href, undefined, 'save before launching WhatsApp on mobile');
    return saveHistory(...args);
  };
  await qa.context.prepareApplication('whatsapp', {});
  let url = new URL(qa.popup.location.href);
  assert.equal(url.pathname, '/18095550100');
  assert.ok(url.searchParams.get('text').includes(qa.state.draft.position));
  assert.equal(qa.state.applications.length, 1);

  assert.equal(qa.state.applications[0].status, 'whatsapp_opened');
  assert.equal(qa.state.applications[0].channel, 'whatsapp');
  assert.equal(qa.state.applications[0].recipient, '18095550100');
  assert.equal(qa.state.applications[0].cv_url, 'https://drive.google.com/file/d/cv-test/view');
  assert.match(qa.$('#application-send-status').textContent, /guardada automáticamente/);

  qa = setup();
  qa.$('#application-phone').value = '8095550100';
  qa.context.window.open = () => null;
  await qa.context.prepareApplication('whatsapp', {});
  assert.equal(qa.state.applications.length, 0);

  qa = setup();
  qa.$('#application-phone').value = '8095550100';
  let finishPdf;
  qa.context.download = () => new Promise(resolve => { finishPdf = resolve; });
  const firstClick = qa.context.prepareApplication('whatsapp', {});
  await qa.context.prepareApplication('whatsapp', {});
  assert.equal(qa.calls.filter(call => call === 'open').length, 1);
  finishPdf({driveUrl: 'https://drive.google.com/file/d/cv-test/view'});
  await firstClick;
  assert.equal(qa.state.applications.length, 1);

  qa = setup();
  qa.$('#application-email').value = 'bad\r\nBcc: injected@example.com';
  await qa.context.prepareApplication('gmail', {});
  assert.equal(qa.calls.length, 0);

  qa = setup();
  qa.$('#application-phone').value = '8095550100';
  qa.context.download = async () => null;
  await qa.context.prepareApplication('whatsapp', {});
  assert.equal(qa.popup.closed, true);
  assert.equal(qa.state.applications.length, 0);

  qa = setup();
  qa.$('#application-phone').value = '8095550100';
  qa.context.fetch = async () => ({ok: false, json: async () => ({error: 'Drive no disponible'})});
  await qa.context.prepareApplication('whatsapp', {});
  assert.ok(qa.popup.location.href.startsWith('https://wa.me/'));
  assert.match(qa.$('#application-send-status').textContent, /historial no quedó guardado/);
  assert.equal(qa.state.applications.length, 0);
  qa = setup();
  qa.$('#application-email').value = 'empleos@example.com';
  qa.$('#application-message').value = 'Mensaje';
  qa.context.fetch = async () => { throw new Error('Network failure'); };
  await qa.context.sendApplicationGmail({});
  assert.equal(qa.state.gmailAttempt.unknown, true);
  await qa.context.sendApplicationGmail({});
  assert.match(qa.$('#application-send-status').textContent, /Comprueba Enviados/);
  assert.equal(qa.state.applications.length, 0);
  process.stdout.write('Postulaciones: destinatarios, asunto, WhatsApp, PDF fallido e historial sin falsos envíos verificados.\n');
})().catch(error => { console.error(error); process.exitCode = 1; });
