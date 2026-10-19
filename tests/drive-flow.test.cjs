const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

async function main() {
  const elements = new Map();
  const listeners = new Map();
  const calls = [];
  let popup;
  let blocked = false;
  const document = {
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, {textContent: '', addEventListener() {}});
      return elements.get(selector);
    },
    createElement() {return {};},
    head: {append(element) {queueMicrotask(() => element.onload());}},
  };
  const window = {
    cvLoading: {start() {return () => {}; }},
    open(url) {calls.push(url); popup = {closed: false}; return blocked ? null : popup;},
    addEventListener(type, callback) {listeners.set(type, callback);},
    dispatchEvent(event) {listeners.get(event.type)?.(event);},
    removeEventListener(type) {listeners.delete(type);},
  };
  const context = vm.createContext({window, document, crypto: {randomUUID: () => 'test-nonce'},
    location: {origin: 'https://cv-a-la-medida-jhonn.web.app'}, Date, Promise, Event,
    setInterval, clearInterval, gapi: {load(name, options) {options.callback();}},
    fetch: async (url, options) => {
      calls.push({url, headers: options.headers});
      return {ok: true, json: async () => ({folder_id: 'output-folder'})};
    },
  });
  vm.runInContext(fs.readFileSync('static/drive.js', 'utf8'), context);
  const drive = window.cvDrive;
  await drive.initialize({provider: 'drive', folder_id: 'output-folder'}, () => ({Authorization: 'Bearer test-session'}));
  const connection = drive.connect();
  assert.equal(typeof calls[0], 'string', 'Popup opens before awaiting any request');
  assert.equal(drive.connect(), connection, 'Concurrent calls reuse the connection');
  assert.equal(drive.isConnected(), false);
  listeners.get('message')({origin: 'https://wrong-origin.example', source: popup, data: {nonce: 'test-nonce', result: {access_token: 'bad'}}});
  assert.equal(calls.length, 1, 'Untrusted messages do not trigger a Drive request');
  listeners.get('message')({origin: 'https://cv-a-la-medida-jhonn.firebaseapp.com', source: popup, data: {nonce: 'test-nonce', result: {access_token: 'test-drive-token', expires_in: 3600}}});
  await connection;
  assert.equal(drive.isConnected(), true);
  assert.equal(calls[1].url, '/api/drive/check');
  assert.equal(calls[1].headers['X-Drive-Access-Token'], 'test-drive-token');
  assert.equal(drive.headers()['X-Drive-Access-Token'], 'test-drive-token');
  await drive.connect();
  assert.equal(calls.length, 2, 'Connected sessions do not open another popup');
  drive.reset();
  assert.throws(() => drive.headers(), /Conecta Google Drive/);
  await drive.acceptCredential('login-drive-token');
  assert.equal(drive.headers()['X-Drive-Access-Token'], 'login-drive-token', 'Google login credential enables saving');
  drive.reset();
  blocked = true;
  await assert.rejects(drive.connect(), /ventanas emergentes/);
  vm.runInContext(fs.readFileSync('static/gmail.js', 'utf8'), context);
  let authorizationCalls = 0;
  drive.setAuthorizationHandler(async () => {
    authorizationCalls++;
    return {access_token: 'combined-token', expires_in: 3600, scope: 'openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/gmail.send'};
  });
  await drive.connect({requireGmail: true});
  assert.equal(window.cvGmail.headers()['X-Gmail-Access-Token'], drive.headers()['X-Drive-Access-Token']);
  await window.cvGmail.connect();
  await drive.connect({requireGmail: true});
  assert.equal(authorizationCalls, 1, 'Sync and sending reuse a single Google authorization');
  window.cvGmail.reset();
  await drive.connect({requireGmail: true});
  assert.equal(authorizationCalls, 2, 'A missing Gmail token renews the shared authorization even when Drive is connected');
  const credentialHeaders = drive.headers();
  assert.equal(drive.invalidateAuthorization('unknown_error', credentialHeaders), false);
  assert.equal(drive.invalidateAuthorization('google_authorization_expired', {}), false);
  assert.equal(drive.invalidateAuthorization('google_authorization_expired', {'X-Drive-Access-Token': 'old-token'}), false);
  assert.equal(drive.isConnected(), true, 'Unrelated and stale failures preserve the current permission');
  assert.equal(drive.invalidateAuthorization('google_authorization_expired', credentialHeaders), true);
  assert.equal(drive.isConnected(), false);
  assert.deepEqual(Object.keys(drive.headersIfConnected()), []);
  assert.equal(authorizationCalls, 2, 'Invalidating permission never replays an authorization or write automatically');
  await drive.connect();
  assert.equal(authorizationCalls, 3, 'The next user action renews the revoked permission');
  await drive.acceptCredential('newer-credential');
  assert.equal(drive.invalidateAuthorization('google_authorization_expired', credentialHeaders), false);
  assert.equal(drive.isConnected(), true, 'A late failure cannot invalidate the replacement credential');
  drive.reset();
  drive.setAuthorizationHandler(async () => {throw new Error('Authorization cancelled');});
  await assert.rejects(drive.connect({requireGmail: true}), /Authorization cancelled/);
  assert.equal(document.querySelector('#connect-drive').disabled, false);
  assert.equal(document.querySelector('#drive-status').textContent, 'Authorization cancelled');
  console.log('Drive: conexión, permiso de inicio de sesión, origen, reconexión y bloqueo de popup verificados.');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
