/* Gmail and Drive reuse one Google authorization. Tokens remain in memory. */
window.cvGmail = (() => {
  let token = "", expires = 0, connection = null;
  function reset() { token = ""; expires = 0; }
  function isConnected() { return Boolean(token && Date.now() < expires); }
  function acceptCredential(accessToken, expiresIn = 3600, scope) {
    if (!accessToken || (scope && !String(scope).split(" ").includes("https://www.googleapis.com/auth/gmail.send"))) {
      reset(); return false;
    }
    token = accessToken;
    expires = Date.now() + Number(expiresIn) * 1000 - 60000;
    return true;
  }
  function connect() {
    if (isConnected()) return Promise.resolve();
    if (connection) return connection;
    connection = window.cvDrive.connect({ requireGmail: true }).then(() => {
      if (!isConnected()) throw new Error("Google no concedió el permiso para enviar. Sincroniza el banco y autoriza Gmail con tu cuenta comprobada.");
    }).finally(() => { connection = null; });
    return connection;
  }
  function headers() {
    if (!token || Date.now() >= expires) { reset(); throw new Error("Autoriza Gmail para enviar el CV."); }
    return { "X-Gmail-Access-Token": token };
  }
  return { connect, headers, reset, isConnected, acceptCredential };
})();
