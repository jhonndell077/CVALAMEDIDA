(() => {
  const loadedVersion = document.querySelector('meta[name="cv-build"]')?.content;
  if (!loadedVersion) return;
  const storageKey = "cv-acknowledged-build";
  let pendingVersion = "";
  let checking = false;
  let reloading = false;
  let banner;
  function storedVersion() {
    try { return localStorage.getItem(storageKey); } catch { return null; }
  }
  function acknowledge(version) {
    try { localStorage.setItem(storageKey, version); } catch { /* Private browsing is supported. */ }
  }
  function show(version) {
    pendingVersion = version;
    if (banner) return;
    banner = document.createElement("aside");
    banner.className = "update-banner";
    banner.id = "update-banner";
    banner.setAttribute("aria-label", "Actualización de la aplicación");
    const message = document.createElement("div");
    message.setAttribute("role", "status");
    message.setAttribute("aria-live", "polite");
    const title = document.createElement("strong");
    title.textContent = "Nueva actualización disponible";
    const detail = document.createElement("p");
    detail.textContent = "Termina tu tarea y pulsa Actualizar para cargar los cambios. La página se recargará.";
    message.append(title, detail);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button button-primary";
    button.textContent = "Actualizar";
    button.addEventListener("click", () => {
      if (reloading || document.body.classList.contains("is-loading")) return;
      reloading = true;
      button.disabled = true;
      button.textContent = "Actualizando…";
      acknowledge(pendingVersion);
      const url = new URL(window.location.href);
      url.searchParams.set("cv_v", pendingVersion);
      window.location.replace(url.toString());
    });
    banner.append(message, button);
    document.body.append(banner);
  }
  async function check() {
    if (checking || reloading || document.hidden) return;
    checking = true;
    try {
      const response = await fetch(`/version.json?t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) return;
      const data = await response.json();
      const latest = data?.buildId;
      if (typeof latest !== "string" || !/^[A-Za-z0-9_-]{1,100}$/.test(latest)) return;
      // Always compare with the version actually loaded in this tab.
      if (latest !== loadedVersion) show(latest);
    } catch { /* Offline checks never interrupt the CV flow. */ }
    finally { checking = false; }
  }
  const previous = storedVersion();
  if (previous && previous !== loadedVersion) show(loadedVersion);
  else if (!previous) acknowledge(loadedVersion);
  check();
  window.setInterval(check, 60000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) check(); });
  window.addEventListener("focus", check);
  window.addEventListener("online", check);
})();
