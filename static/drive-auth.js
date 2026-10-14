const oauthParams = new URLSearchParams(location.search);
const returnOrigin = oauthParams.get("origin");
const authNonce = oauthParams.get("nonce");
const gmailMode = oauthParams.get("mode") === "gmail";
const combinedMode = oauthParams.get("mode") === "combined";
const allowedOrigins = new Set([
  "https://cvalamedida.web.app", "https://cvalamedida.firebaseapp.com",
  "https://cv-a-la-medida-jhonn.web.app", "https://cv-a-la-medida-jhonn.firebaseapp.com",
  "http://127.0.0.1:8765", "http://localhost:8765",
]);
const oauthStatus = document.querySelector("#oauth-status");
const authorizeButton = document.querySelector("#authorize");
async function prepareDriveAuth() {
  if (!window.opener || !allowedOrigins.has(returnOrigin) || !/^[a-f0-9-]{36}$/.test(authNonce || "")) {
    throw new Error("Abre esta ventana usando Conectar Google Drive desde la aplicación.");
  }
  const response = await fetch("/drive-config.json", { cache: "no-store" });
  if (!response.ok) throw new Error("No se pudo cargar la configuración de Drive.");
  const config = await response.json();
  if (gmailMode) {
    document.querySelector("h1").textContent = "Conectar Gmail";
    document.querySelector(".panel > p").textContent = "Autoriza el envío de correos con tu cuenta. La aplicación no necesita leer tu bandeja de entrada.";
    authorizeButton.textContent = "Autorizar envío por Gmail";
    document.title = "Conectar Gmail";
  }
  if (combinedMode) {
    document.querySelector("h1").textContent = "Conectar Gmail y Drive";
    document.querySelector(".panel > p").textContent = "Autoriza tu cuenta comprobada para guardar los CV y enviarlos por Gmail. Se reutilizarán ambos permisos.";
    authorizeButton.textContent = "Continuar con mi cuenta";
    document.title = "Conectar Gmail y Drive";
  }
  const client = google.accounts.oauth2.initTokenClient({
    client_id: config.client_id,
    scope: combinedMode ? "openid email https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/gmail.send" : gmailMode ? "openid email https://www.googleapis.com/auth/gmail.send" : "openid email https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file",
    include_granted_scopes: true,
    login_hint: config.allowed_email,
    callback: (result) => {
      if (result.error) { oauthStatus.textContent = `Google no autorizó ${gmailMode ? "Gmail" : "Drive"}. Inténtalo de nuevo.`; authorizeButton.disabled = false; return; }
      window.opener.postMessage({ nonce: authNonce, result }, returnOrigin);
      window.close();
    },
    error_callback: () => { authorizeButton.disabled = false; oauthStatus.textContent = "La autorización se cerró. Vuelve a intentarlo."; },
  });
  authorizeButton.disabled = false;
  oauthStatus.textContent = gmailMode ? "El permiso permite enviar correos desde esta página. Al crear tu CV, se enviará automáticamente al correo detectado en la vacante." : "Tu permiso se limita a los archivos y la carpeta que selecciones para esta aplicación.";
  authorizeButton.addEventListener("click", () => {
    authorizeButton.disabled = true;
    client.requestAccessToken({ prompt: "" });
  });
}
prepareDriveAuth().catch((error) => { oauthStatus.textContent = error.message; });
