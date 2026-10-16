const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
(async () => {
  let authorizeCount = 0, release;
  const window = {cvDrive: {connect(options) {
    assert.equal(options.requireGmail, true);
    authorizeCount++;
    return new Promise(resolve => {release = () => {
      window.cvGmail.acceptCredential('shared-token', 3600, 'openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/gmail.send');
      resolve();
    };});
  }}};
  const context = vm.createContext({window, Date, Promise});
  vm.runInContext(fs.readFileSync('static/gmail.js', 'utf8'), context);
  const gmail = window.cvGmail;
  const first = gmail.connect();
  assert.equal(gmail.connect(), first);
  release(); await first;
  assert.equal(gmail.headers()['X-Gmail-Access-Token'], 'shared-token');
  await gmail.connect(); await gmail.connect();
  assert.equal(authorizeCount, 1);
  gmail.reset();
  assert.equal(gmail.isConnected(), false);
  assert.equal(gmail.acceptCredential('drive-only', 3600, 'openid email https://www.googleapis.com/auth/drive.file'), false);
  assert.throws(() => gmail.headers(), /Autoriza Gmail/);
  gmail.acceptCredential('expired', 30, 'https://www.googleapis.com/auth/gmail.send');
  assert.equal(gmail.isConnected(), false);
  assert.equal(gmail.acceptCredential('google-login-token'), false);
  const renewed = gmail.connect(); release(); await renewed;
  assert.equal(authorizeCount, 2);
  console.log('Gmail: shared authorization, reuse, partial scopes and expiration verified.');
})().catch(error => {console.error(error); process.exitCode = 1;});
