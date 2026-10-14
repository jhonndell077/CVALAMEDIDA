const state = {
  analysis: null,
  draft: null,
  pdf: null,
  applications: [],
  gmailAttempt: null,
  gmailSending: false,
  model: "",
  authRequired: false,
  modelAvailable: false,
  provider: "ollama-local",
  auth: null,
  idToken: null,
  user: null,
  photoUrl: null,
  profileEditable: false,
  profileDraft: null,
  profileDirty: false,
  knowledgeMap: null,
  bankEnabled: false,
  bankSyncPromise: null,
  multiAccount: false,
  accountReady: false,
  activeUserId: null,
};

const $ = (selector) => document.querySelector(selector);
const jobPanel = $("#job-panel");
const analysisPanel = $("#analysis-panel");
const cvPanel = $("#cv-panel");
const errorBox = $("#app-error");
const fileInput = $("#job-file");
const modelSelect = $("#model-select");
const informationForm = $("#new-information-form");
let informationRequestId = null;
let informationRequestSignature = null;
let informationSaving = false;
function closeInformationForm() {
  informationForm.hidden = true;
  $("#new-information").setAttribute("aria-expanded", "false");
}
$("#new-information").addEventListener("click", () => {
  informationForm.hidden = !informationForm.hidden;
  $("#new-information").setAttribute("aria-expanded", String(!informationForm.hidden));
  if (!informationForm.hidden) informationForm.elements.type.focus();
});
$("#cancel-information").addEventListener("click", closeInformationForm);
informationForm.elements.type.addEventListener("change", () => {
  informationForm.querySelectorAll("[data-information-types]").forEach(group => {
    const active = group.dataset.informationTypes.split(" ").includes(informationForm.elements.type.value);
    group.hidden = !active;
    group.querySelectorAll("input, textarea").forEach(input => { input.disabled = !active; });
  });
});
informationForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (informationSaving) return;
  informationSaving = true;
  const button = $("#save-information");
  const errorBox = $("#information-error");
  errorBox.hidden = true;
  try {
    const values = {...Object.fromEntries(new FormData(informationForm)), ...window.cvRepeaters.collect(informationForm)};
    const type = values.type;
    delete values.type;
    const signature = JSON.stringify({type, fields: values});
    if (signature !== informationRequestSignature) informationRequestId = null;
    informationRequestId ||= crypto.randomUUID().replaceAll("-", "");
    informationRequestSignature = signature;
    setBusy(button, true, "Guardando nueva información");
    if (state.user) state.idToken = await state.user.getIdToken();
    const saved = await requestJson("/api/profile/information", { type, request_id: informationRequestId, fields: values });
    // The save is complete even if the subsequent profile refresh fails.
    informationRequestId = null;
    informationRequestSignature = null;
    informationForm.reset();
    window.cvRepeaters.reset(informationForm);
    informationForm.elements.type.dispatchEvent(new Event("change"));
    closeInformationForm();
    state.analysis = null;
    state.draft = null;
    state.pdf = null;
    state.vacancyRevision = (state.vacancyRevision || 0) + 1;
    analysisPanel.hidden = true;
    cvPanel.hidden = true;
    jobPanel.hidden = false;
    $("#information-status").textContent = saved.message + " Analiza la vacante para usar tu perfil actualizado.";
    if (saved.profile) applySavedProfile(saved.profile);
    else await loadProfileSummary();
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
    if (informationForm.hidden) $("#information-status").textContent += " No se pudo actualizar la vista: " + error.message;
  } finally {
    informationSaving = false;
    setBusy(button, false);
  }
});
const templateDetails = {
  cocina: {
    name: "Gastronomía y operaciones",
    accent: "#518ecb",
    sidebar: "#eaf2f8",
  },
  oficina: {
    name: "Administración y servicio",
    accent: "#477b63",
    sidebar: "#eaf3ed",
  },
  supermercados: {
    name: "Retail y operaciones",
    accent: "#c17836",
    sidebar: "#fbefe4",
  },
  microsoft: {
    name: "Perfil técnico",
    accent: "#3976bd",
    sidebar: "#e8f0fa",
  },
};

function getTemplateDetails(template) {
  return templateDetails[template] || templateDetails.oficina;
}

function addText(parent, tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text ?? "";
  if (className) element.className = className;
  parent.append(element);
  return element;
}

const busyButtons = new WeakMap();
function setBusy(button, busy, label = "Cargando") {
  button.disabled = busy;
  button.classList.toggle("loading-label", busy);
  if (busy) {
    if (!busyButtons.has(button)) busyButtons.set(button, {
      nodes: [...button.childNodes], finish: window.cvLoading.start(label),
    });
    button.textContent = label;
  } else {
    const operation = busyButtons.get(button);
    if (operation) {
      button.replaceChildren(...operation.nodes);
      busyButtons.delete(button);
      operation.finish();
    }
  }
}

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

function clearError() {
  errorBox.textContent = "";
  errorBox.hidden = true;
}

async function requestJson(url, payload) {
  if (window.cvBackground.enabled() && window.cvBackground.handles(url)) return window.cvBackground.run(url, payload);
  return directRequestJson(url, payload);
}

async function directRequestJson(url, payload, headers = {}) {
  const requestOwner = state.user?.uid;
  if (state.user) state.idToken = await state.user.getIdToken();
  const response = await fetch(url, {
    method: "POST",
    headers: authenticatedHeaders({ "Content-Type": "application/json", ...headers }),
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (requestOwner !== state.user?.uid) throw Object.assign(new Error('La cuenta cambió. Inicia esta operación con tu nueva sesión.'), {terminal: true});
  if (!response.ok) {
    throw Object.assign(new Error(data.error || `La solicitud falló (${response.status}).`), {status: response.status});
  }
  return data;
}

async function processFetch(url, settings) {
  if (!window.cvBackground.enabled() || !window.cvBackground.handles(url) || settings.method !== 'POST') return fetch(url, settings);
  const result = await window.cvBackground.run(url, JSON.parse(settings.body || '{}'), settings.headers);
  if (result.download_url) {
    if (state.user) state.idToken = await state.user.getIdToken();
    const file = await fetch(result.download_url, {headers: authenticatedHeaders()});
    if (!file.ok) return file;
    return new Response(await file.blob(), {headers: {'Content-Type': file.headers.get('Content-Type'),
      'Content-Disposition': `attachment; filename="${result.fileName}"`, 'X-CV-Drive-URL': result.driveUrl || ''}});
  }
  return new Response(JSON.stringify(result), {headers: {'Content-Type': 'application/json'}});
}

function authenticatedHeaders(headers = {}) {
  if (state.idToken) headers.Authorization = `Bearer ${state.idToken}`;
  Object.assign(headers, window.cvDrive?.headersIfConnected?.() || {});
  return headers;
}

function updateAnalyzeButton() {
  $("#analyze-button").disabled =
    !state.modelAvailable || (state.authRequired && !state.idToken);
}

async function loadModels(health) {
  const help = $("#model-help");
  state.provider = health.provider;
  state.modelAvailable = health.model_available === true;
  modelSelect.replaceChildren();
  if (health.provider === "vertex-ai") {
    if (!health.model_available) {
      modelSelect.add(new Option("Vertex AI no está configurado", ""));
      help.textContent =
        "El servidor necesita un proyecto de Google Cloud para habilitar Gemini.";
    } else {
      const model = health.models[0];
      modelSelect.add(new Option(`${model.name} · Vertex AI`, model.name));
      modelSelect.value = model.name;
      state.model = model.name;
      help.textContent =
        "Gemini analiza la vacante y la experiencia pertinente. Los datos de contacto no se incluyen en esa solicitud.";
    }
    $("#privacy-status").textContent = "IA en Google Cloud · cuenta protegida";
    $("#privacy-note").innerHTML =
      "<b>Procesamiento en Google Cloud.</b> La vacante y las evidencias laborales se envían a Vertex AI para el análisis; tus datos personales de contacto no se incluyen en esa solicitud. El historial de postulaciones se guarda en tu Drive.";
  } else {
    const models = health.models || [];
    if (!models.length) {
      modelSelect.add(new Option("Ollama no está disponible", ""));
      help.textContent =
        "Inicia Ollama y confirma que haya al menos un modelo descargado.";
      $("#privacy-status").textContent = "Ollama no está disponible";
    } else {
      const preferred =
        models.find((item) => /^qwen2\.5-coder:latest$/i.test(item.name)) ||
        models.find((item) => /^llama3\.1(?::|$)/i.test(item.name)) ||
        models.find((item) => /^qwen3\.6(?::|$)/i.test(item.name)) ||
        models[0];
      models.forEach((model) => {
        const size = model.size
          ? ` · ${(model.size / (1024 ** 3)).toFixed(1)} GB`
          : "";
        modelSelect.add(new Option(`${model.name}${size}`, model.name));
      });
      modelSelect.value = preferred.name;
      state.model = preferred.name;
      help.textContent =
        "El análisis se ejecuta localmente. Para imágenes y PDF escaneados se selecciona un modelo con visión si está disponible.";
      $("#privacy-status").textContent =
        "IA local · CV guardados en Drive";
      $("#privacy-note").innerHTML =
        "<b>Análisis local.</b> La vacante se procesa con Ollama en este equipo. Al exportar, el CV se guarda en Google Drive con tu autorización.";
    }
  }
  updateAnalyzeButton();
}

function loadScript(source) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = source;
    script.onload = resolve;
    script.onerror = () =>
      reject(new Error("No se pudo cargar el inicio de sesión de Firebase."));
    document.head.append(script);
  });
}

function renderBankStatus(data) {
  const list = $("#bank-documents");
  list.replaceChildren();
  for (const doc of data.documents || []) {
    if (!doc.active) continue;
    const row = document.createElement("p");
    const link = document.createElement("a");
    link.href = `https://drive.google.com/file/d/${encodeURIComponent(doc.file_id)}/view`;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = doc.name;
    row.append(link, document.createTextNode(` · ${doc.active ? doc.status : "retirado del banco"}${doc.message ? " · " + doc.message : ""}`));
    list.append(row);
  }
  const warnings = $("#bank-warnings");
  warnings.replaceChildren();
  for (const warning of data.warnings || []) addText(warnings, "p", `${warning.name}: ${warning.message}`);
  const unread = (data.documents || []).filter(doc => doc.active && doc.status === "revision").length;
  $("#bank-status").textContent = data.pending
    ? `${data.pending} documento(s) pendiente(s) de lectura.`
    : `Banco actualizado · ${data.counts.courses} cursos · ${data.counts.education} estudios · ${data.counts.experiences} experiencias.${unread ? ` ${unread} archivo(s) no pudieron leerse; revisa los avisos.` : ""}`;
}

async function synchronizeBank(onProgress) {
  if (!state.bankEnabled) return;
  if (state.bankSyncPromise) return state.bankSyncPromise;
  const bankOwner = state.user?.uid;
  const operation = state.bankSyncPromise = (async () => {
    const button = $("#sync-bank");
    setBusy(button, true, "Leyendo documentos de Drive…");
    let previousSignature = null;
    try {
      if (window.cvBackground.enabled()) {
        const data = await window.cvBackground.run('/api/bank/sync', {}, {}, onProgress);
        if (bankOwner !== state.user?.uid) throw new Error('La cuenta cambió durante la sincronización.');
        renderBankStatus(data);
        return data;
      }
      // One document per request keeps large banks within server time limits.
      for (;;) {
        if (state.authRequired && !state.user) throw new Error("Inicia sesión para sincronizar el banco.");
        if (state.user) state.idToken = await state.user.getIdToken();
        const data = await requestJson("/api/bank/sync", {});
        if (bankOwner !== state.user?.uid) throw new Error('La cuenta cambió durante la sincronización.');
        renderBankStatus(data);
        if (!data.pending) return data;
        const signature = JSON.stringify(data.documents.map(d => [d.file_id, d.status, d.processed_at]));
        if (signature === previousSignature) throw new Error("Quedaron documentos pendientes. Revisa los avisos y vuelve a sincronizar.");
        previousSignature = signature;
      }
    } catch (error) {
      if (bankOwner === state.user?.uid) $("#bank-status").textContent = error.message;
      throw error;
    } finally {
      if (bankOwner === state.user?.uid) {
        setBusy(button, false);
        button.disabled = state.authRequired && !state.user;
      }
    }
  })();
  try { return await operation; }
  finally { if (state.bankSyncPromise === operation) state.bankSyncPromise = null; }
}

let synchronizationRunning = false;
$("#sync-bank").addEventListener("click", async () => {
  if (synchronizationRunning) return;
  synchronizationRunning = true;
  $("#sync-bank").disabled = true;
  clearError();
  try { await window.cvLoading.run("Sincronizando tu banco en Google Drive", async update => {
    update(2, 'Comprobando la conexión de Gmail y Drive');
    await window.cvDrive.connect();
    if (!window.cvDrive.isConnected()) throw new Error("Faltan permisos de Drive. Pulsa Sincronizar todo y acepta los permisos.");
    update(15, 'Conexión comprobada; sincronizando el banco');
    await synchronizeBank((progress, stage, durable) => update(15 + Math.floor(progress * 0.75), stage, durable));
    update(92, 'Banco sincronizado; actualizando tu perfil');
    await loadProfileSummaryWork();
    update(99, 'Banco de datos sincronizado');
    await window.cvOnboarding?.check();
  }); }
  catch (error) { showError(error.message); }
  finally { synchronizationRunning = false; $("#sync-bank").disabled = state.authRequired && !state.user; }
});

async function loadProfileSummary() {
  return window.cvLoading.run("Cargando tu perfil", () => loadProfileSummaryWork());
}

async function loadProfileSummaryWork() {
  const profileOwner = state.user?.uid;
  const profileRevision = state.vacancyRevision || 0;
  const response = await fetch("/api/profile", {
    cache: "no-store",
    headers: authenticatedHeaders(),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || "No se pudo cargar el perfil profesional.");
  }
  const profile = await response.json();
  if (profileOwner !== state.user?.uid || profileRevision !== (state.vacancyRevision || 0)) return;
  applySavedProfile(profile);
  if (state.profileEditable && !state.bankEnabled) {
    $("#knowledge-local-controls").hidden = false;
    $("#knowledge-local-note").hidden = true;
    try {
      await refreshKnowledgeMap();
    } catch (error) {
      $("#knowledge-status").textContent = "No se pudo cargar el mapa";
      $("#knowledge-error").textContent =
        error.message || "No se pudo cargar el mapa de conocimiento.";
      $("#knowledge-error").hidden = false;
    }
  } else {
    $("#knowledge-local-controls").hidden = true;
    $("#knowledge-local-note").hidden = false;
    $("#knowledge-status").textContent = state.bankEnabled ? "Documentos en Drive" : "Solo disponible localmente";
  }
}

function applySavedProfile(profile) {
  state.profile = profile;
  state.profileDraft = structuredClone(profile);
  state.profileDirty = false;
  $("#profile-panel").hidden = false;
  renderProfileTree();
}

function renderKnowledgeMap(knowledgeMap) {
  state.knowledgeMap = knowledgeMap;
  const results = $("#knowledge-results");
  results.replaceChildren();
  const documents = Object.values(knowledgeMap.documents || {}).sort(
    (left, right) =>
      String(right.lastProcessedAt || "").localeCompare(
        String(left.lastProcessedAt || ""),
      ),
  );
  const pendingCount = Object.values(knowledgeMap.evidence || {}).filter(
    (item) => item.status === "pending_validation",
  ).length;
  $("#knowledge-status").textContent =
    `${documents.length} documento(s) · ${pendingCount} evidencia(s) pendiente(s)`;
  if (!documents.length) {
    addText(
      results,
      "p",
      "Aún no hay documentos históricos registrados.",
      "profile-locked",
    );
    return;
  }
  documents.forEach((item) => {
    const card = addText(results, "article", "", "knowledge-document");
    addText(card, "b", item.fileName || "Documento local");
    const evidenceCount = (item.evidenceIds || []).length;
    const processed = item.lastProcessedAt
      ? new Date(item.lastProcessedAt).toLocaleString()
      : "Sin fecha";
    const modified = item.modifiedTime
      ? new Date(item.modifiedTime).toLocaleString()
      : "No disponible";
    addText(
      card,
      "p",
      `${item.status || "procesado"} · ${item.revisionCount || 1} revisión(es) · ` +
        `${evidenceCount} fragmento(s) pendiente(s) · tema: ` +
        `${(item.topic || ["Pendiente de clasificar"]).join(", ")} · modificado: ` +
        `${modified} · procesado: ${processed}`,
    );
    const evidenceItems = (item.evidenceIds || [])
      .map((id) => knowledgeMap.evidence?.[id])
      .filter(Boolean);
    if (evidenceItems.length) {
      const details = addText(card, "details", "", "knowledge-evidence");
      addText(
        details,
        "summary",
        `Ver evidencia pendiente (${evidenceItems.length})`,
      );
      evidenceItems.slice(0, 10).forEach((evidence) => {
        addText(details, "p", evidence.text || "");
        if (evidence.references?.length) {
          addText(
            details,
            "p",
            `Referencias candidatas: ${evidence.references
              .map((reference) => reference.id)
              .join(", ")}`,
          );
        }
      });
      if (evidenceItems.length > 10) {
        addText(
          details,
          "p",
          `Se muestran 10 de ${evidenceItems.length} fragmentos.`,
        );
      }
    }
  });
}

async function refreshKnowledgeMap() {
  const response = await fetch("/api/knowledge-map", {
    cache: "no-store",
    headers: authenticatedHeaders(),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || "No se pudo cargar el mapa de conocimiento.");
  }
  $("#knowledge-sync-summary").textContent = "";
  renderKnowledgeMap(data);
}

async function updateKnowledgeMap() {
  return window.cvLoading.run("Actualizando mapa de conocimiento", updateKnowledgeMapWork);
}

async function updateKnowledgeMapWork() {
  const button = $("#update-knowledge-map");
  const input = $("#knowledge-files");
  const errorBox = $("#knowledge-error");
  const selectedFiles = [...(input.files || [])];
  errorBox.hidden = true;
  errorBox.textContent = "";
  if (!selectedFiles.length) {
    errorBox.textContent = "Selecciona al menos un documento histórico.";
    errorBox.hidden = false;
    return;
  }
  const totalBytes = selectedFiles.reduce((total, file) => total + file.size, 0);
  if (selectedFiles.length > 8 || totalBytes > 15 * 1024 * 1024) {
    errorBox.textContent =
      "Selecciona hasta 8 archivos y mantén cada archivo bajo 10 MB y la carga total bajo 15 MB.";
    errorBox.hidden = false;
    return;
  }
  const body = new FormData();
  selectedFiles.forEach((file) => body.append("files", file, file.name));
  body.append(
    "modifiedTimes",
    JSON.stringify(
      selectedFiles.map((file) =>
        Number.isFinite(file.lastModified)
          ? new Date(file.lastModified).toISOString()
          : null,
      ),
    ),
  );
  try {
    setBusy(button, true, "Actualizando mapa…");
    const response = await fetch("/api/knowledge-map/documents", {
      method: "POST",
      headers: authenticatedHeaders(),
      body,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || `No se pudo actualizar el mapa (${response.status}).`);
    }
    renderKnowledgeMap(data.knowledge_map);
    $("#knowledge-sync-summary").textContent = (data.results || [])
      .map((item) => {
        const status = {
          processed: "nuevo",
          updated: "cambios registrados",
          unchanged: "sin cambios; no se reprocesó",
          duplicate_content: "contenido ya registrado",
          error: "error",
        }[item.status] || item.status;
        return `${item.fileName}: ${status}`;
      })
      .join(" · ");
    const errors = (data.results || [])
      .filter((item) => item.status === "error")
      .map((item) => `${item.fileName}: ${item.error}`);
    if (errors.length) {
      errorBox.textContent = errors.join(" ");
      errorBox.hidden = false;
    }
    input.value = "";
  } catch (error) {
    errorBox.textContent =
      error.message || "No se pudo actualizar el mapa de conocimiento.";
    errorBox.hidden = false;
  } finally {
    setBusy(button, false);
  }
}

const profileLabels = {
  candidate: "Datos personales",
  name: "Nombre",
  national_id: "Cédula",
  address: "Dirección",
  residence: "Residencia",
  phones: "Teléfonos",
  email: "Correo electrónico",
  photo: "Fotografía fija",
  education: "Estudios",
  courses: "Cursos realizados",
  references: "Referencias",
  skills: "Habilidades",
  experiences: "Experiencias",
  projects: "Proyectos",
  not_documented: "Datos pendientes de documentar",
  id: "Identificador",
  title: "Cargo o título",
  employer: "Empleador",
  category: "Categoría",
  responsibilities: "Funciones",
  origin: "Procedencia de la función",
  text: "Descripción",
  institution: "Institución",
  role: "Cargo o relación",
  phone: "Teléfono",
  label: "Habilidad",
  sources: "Ámbitos relacionados",
  description: "Descripción del proyecto",
  technologies: "Tecnologías",
  url: "Enlace",
};

function profileLabel(key) {
  return profileLabels[key] || key.replaceAll("_", " ");
}

function profileEntryTitle(value, index) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const heading = value.title || value.name || value.label || value.text || value.id;
    const employer = value.employer ? ` · ${value.employer}` : "";
    if (heading) return `${heading}${employer}`;
  }
  return typeof value === "string" && value ? value : `Elemento ${index + 1}`;
}

function setProfilePath(path, value) {
  let parent = state.profileDraft;
  path.slice(0, -1).forEach((part) => {
    parent = parent[part];
  });
  parent[path.at(-1)] = value;
  state.profileDirty = true;
  $("#save-profile").disabled = !state.profileEditable;
  $("#discard-profile").disabled = false;
  $("#profile-status").textContent = "Cambios sin guardar";
  $("#profile-error").hidden = true;
}

function makeProfileId(prefix) {
  const suffix = globalThis.crypto?.randomUUID
    ? crypto.randomUUID().slice(0, 8)
    : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  return `${prefix}-${suffix}`.toLowerCase();
}

function newProfileArrayItem(path) {
  const section = path[0];
  if (section === "experiences" && path.length === 1) {
    return {
      id: makeProfileId("experiencia"),
      title: "",
      employer: "",
      category: "oficina",
      responsibilities: [
        { id: makeProfileId("funcion"), text: "" },
      ],
    };
  }
  if (section === "experiences" && path.at(-1) === "responsibilities") {
    return { id: makeProfileId("funcion"), text: "" };
  }
  const templates = {
    education: { id: makeProfileId("estudio"), title: "", institution: "" },
    courses: { id: makeProfileId("curso"), title: "", institution: "" },
    skills: { id: makeProfileId("habilidad"), label: "", sources: [] },
    projects: {
      id: makeProfileId("proyecto"),
      title: "",
      description: "",
      technologies: [],
      url: "",
    },
    references: { name: "", role: "", phone: "" },
  };
  if (templates[section] && path.length === 1) return templates[section];
  if (section === "not_documented" || path.at(-1) === "phones") return "";
  if (path.at(-1) === "sources" || path.at(-1) === "technologies") return "";
  const current = path.reduce((value, part) => value?.[part], state.profileDraft);
  if (current.length && typeof current[0] === "object") {
    const copy = structuredClone(current[0]);
    Object.keys(copy).forEach((key) => {
      if (key === "id") copy[key] = makeProfileId(section.slice(0, -1) || "item");
      else if (Array.isArray(copy[key])) copy[key] = [];
      else if (typeof copy[key] === "string") copy[key] = "";
    });
    return copy;
  }
  return "";
}

function canDeleteProfilePath(path) {
  return (path.length === 2 && ['experiences', 'skills', 'education', 'courses', 'projects', 'references', 'not_documented'].includes(path[0]))
    || (path.length === 2 && path[0] === 'candidate' && ['name', 'national_id', 'address', 'residence', 'email'].includes(path[1]))
    || (path.length === 3 && path[0] === 'candidate' && path[1] === 'phones')
    || (path.length === 4 && path[0] === 'experiences' && path[2] === 'responsibilities');
}

function addProfileDeleteButton(parent, path, value) {
  if (!canDeleteProfilePath(path) || value === '') return;
  const button = addText(parent, 'button', 'Eliminar', 'profile-remove');
  button.type = 'button';
  button.setAttribute('aria-label', `Eliminar ${typeof value === 'object' ? profileEntryTitle(value, 0) : value}`);
  button.addEventListener('click', async event => {
    event.preventDefault();
    event.stopPropagation();
    if (state.profileDeleting) return;
    if (!window.confirm('¿Eliminar este dato del banco profesional? No aparecerá en los próximos CV, aunque vuelvas a sincronizar.')) return;
    state.profileDeleting = true;
    button.disabled = true;
    const errorBox = $('#profile-error');
    errorBox.hidden = true;
    try {
      await window.cvLoading.run('Eliminando del banco', async () => {
        const response = await fetch('/api/profile/delete', {
          method: 'POST', headers: authenticatedHeaders({'Content-Type': 'application/json'}),
          body: JSON.stringify({path, expected: value}),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'No se pudo eliminar el registro.');
        state.profile = data.profile;
        state.profileDraft = structuredClone(data.profile);
        state.profileDirty = false;
        state.analysis = null; state.draft = null; state.pdf = null;
        state.vacancyRevision = (state.vacancyRevision || 0) + 1;
        analysisPanel.hidden = true; cvPanel.hidden = true;
        renderProfileTree();
        $('#profile-status').textContent = data.message;
      });
    } catch (error) {
      errorBox.textContent = error.message || 'No se pudo eliminar el registro.';
      errorBox.hidden = false;
    } finally {
      state.profileDeleting = false;
      button.disabled = false;
    }
  });
}

function renderProfileField(parent, key, value, path) {
  const field = addText(parent, "label", "", "profile-field");
  addText(field, "span", profileLabel(key));
  if (key === "origin") {
    addText(field, "small", value === "generada_por_puesto" ? "Función habitual generada a partir del cargo" : "Función registrada en el banco");
    return;
  }
  if (key === "photo") {
    addText(field, "small", state.bankEnabled ? "Se usará en todos los CV. Reemplaza hoja_de_vida.jpeg en Banco de Datos y vuelve a sincronizar." : "Se usará en todos los CV; este archivo está fijo.", "profile-photo-note");
    return;
  }
  const input = document.createElement(value.length > 90 ? "textarea" : "input");
  input.value = value;
  input.disabled = !state.profileEditable;
  input.setAttribute("aria-label", profileLabel(key));
  input.addEventListener("input", () => setProfilePath(path, input.value));
  field.append(input);
  if (path[0] === 'candidate' && path.length === 2) addProfileDeleteButton(parent, path, value);
  if (Array.isArray(parent)) return;
}

function renderProfileSummary(section, key, count) {
  const descriptions = {
    candidate: ["◉", "Tu identidad y contacto"],
    experiences: ["▣", "Tu recorrido profesional"],
    skills: ["✦", "Lo que sabes hacer"],
    education: ["▤", "Tu formación académica"],
    courses: ["✧", "Aprendizaje y certificados"],
    projects: ["◇", "Ideas que has llevado a la práctica"],
    references: ["◎", "Personas que respaldan tu trayectoria"],
    not_documented: ["⋯", "Información por completar"],
  };
  const [icon, description] = descriptions[key] || ["◇", "Explora tu información"];
  const summary = addText(section, "summary", "", "profile-section-summary");
  addText(summary, "span", icon, "profile-card-icon").setAttribute("aria-hidden", "true");
  const copy = addText(summary, "span", "", "profile-card-copy");
  addText(copy, "span", profileLabel(key), "profile-card-title");
  addText(copy, "span", description, "profile-card-description");
  if (count !== undefined) addText(summary, "span", String(count), "profile-card-count");
  addText(summary, "span", "›", "profile-card-chevron").setAttribute("aria-hidden", "true");
}

function renderProfileValue(parent, key, value, path, options = {}) {
  if (Array.isArray(value)) {
    const section = addText(parent, "details", "", options.topLevel ? "profile-node" : "profile-entry");
    if (options.topLevel) renderProfileSummary(section, key, value.length);
    else addText(section, "summary", `${profileLabel(key)} · ${value.length}`);
    const body = addText(section, "div", "", "profile-node-body");
    value.forEach((item, index) => {
      const itemPath = [...path, index];
      if (item && typeof item === "object") {
        const entry = addText(body, "details", "", "profile-entry");
        const entrySummary = addText(entry, "summary", profileEntryTitle(item, index));
        addProfileDeleteButton(entrySummary, itemPath, item);
        const fields = addText(entry, "div", "", "profile-fields");
        Object.entries(item).forEach(([childKey, childValue]) => {
          if (!childKey.startsWith('_') && !['source_documents','id'].includes(childKey)) renderProfileValue(fields, childKey, childValue, [...itemPath, childKey]);
        });
      } else {
        const wrapper = addText(body, "div", "", "profile-entry profile-leaf");
        const fields = addText(wrapper, "div", "", "profile-fields");
        renderProfileField(fields, `${profileLabel(key)} ${index + 1}`, item, itemPath);
        addProfileDeleteButton(wrapper, itemPath, item);
      }
    });
    if (state.profileEditable) {
      const add = addText(body, "button", `＋ Agregar ${profileLabel(key).toLowerCase()}`, "profile-add");
      add.type = "button";
      add.addEventListener("click", () => {
        value.push(newProfileArrayItem(path));
        state.profileDirty = true;
        renderProfileTree();
      });
    }
    return;
  }
  if (value && typeof value === "object") {
    const section = addText(parent, "details", "", options.topLevel ? "profile-node" : "profile-entry");
    if (options.topLevel) renderProfileSummary(section, key);
    else addText(section, "summary", profileLabel(key));
    const fields = addText(section, "div", "", "profile-fields");
    Object.entries(value).forEach(([childKey, childValue]) => {
      renderProfileValue(fields, childKey, childValue, [...path, childKey]);
    });
    return;
  }
  renderProfileField(parent, key, value, path);
}

function renderProfileTree() {
  const tree = $("#profile-tree");
  tree.replaceChildren();
  if (!state.profileDraft) return;
  const sectionOrder = [
    "candidate",
    "experiences",
    "skills",
    "education",
    "courses",
    "projects",
    "references",
    "not_documented",
  ];
  sectionOrder.forEach((section) => {
    renderProfileValue(
      tree,
      section,
      state.profileDraft[section],
      [section],
      { topLevel: true },
    );
  });
  $("#profile-status").textContent = state.profileEditable
    ? state.profileDirty
      ? "Cambios sin guardar"
      : "Banco listo para editar"
    : "Banco profesional · puedes eliminar registros";
  $("#save-profile").hidden = !state.profileEditable;
  $("#discard-profile").hidden = !state.profileEditable;
  $("#save-profile").disabled = !state.profileEditable || !state.profileDirty;
  $("#discard-profile").disabled = !state.profileDirty;
  if (!state.profileEditable) {
    addText(
      tree,
      "p",
      "Abre una tarjeta y pulsa Eliminar junto al dato que quieras quitar. Los datos eliminados no se incluirán en los próximos CV ni volverán al sincronizar. Los documentos originales de Drive se conservan.",
      "profile-locked",
    );
  }
}

async function saveProfileChanges() {
  return window.cvLoading.run("Guardando cambios", () => saveProfileChangesWork());
}

async function saveProfileChangesWork() {
  const saveButton = $("#save-profile");
  const profileError = $("#profile-error");
  profileError.hidden = true;
  saveButton.disabled = true;
  saveButton.textContent = "Guardando…";
  try {
    if (state.user) state.idToken = await state.user.getIdToken();
    const response = await fetch("/api/profile", {
      method: "PUT",
      headers: authenticatedHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(state.bankEnabled ? {profile:state.profileDraft,expected_profile:state.profile} : state.profileDraft),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || `No se pudo guardar (${response.status}).`);
    }
    state.profile = data.profile;
    state.profileDraft = structuredClone(data.profile);
    state.profileDirty = false;
    state.analysis = null; state.draft = null; state.pdf = null;
    state.vacancyRevision = (state.vacancyRevision || 0) + 1;
    analysisPanel.hidden = true; cvPanel.hidden = true; jobPanel.hidden = false;
    renderProfileTree();
    $("#profile-status").textContent = data.message || "Guardado en tu banco";
  } catch (error) {
    profileError.textContent = error.message || "No se pudieron guardar los cambios.";
    profileError.hidden = false;
    saveButton.disabled = false;
  } finally {
    saveButton.textContent = "Guardar cambios";
    saveButton.disabled = !state.profileEditable || !state.profileDirty;
  }
}

async function updateGoogleUser(user) {
  return updateGoogleUserWork(user);
}

async function updateGoogleUserWork(user) {
  const changed = state.activeUserId !== (user?.uid || null);
  state.activeUserId = user?.uid || null;
  if (changed) {
    window.cvDrive.reset(); window.cvGmail.reset(); window.cvOnboarding?.reset();
    state.analysis = null; state.draft = null; state.pdf = null; state.profile = null; state.profileDraft = null;
    state.employmentContact=null;
    state.applications = []; state.accountReady = false; state.gmailAttempt = null;
    state.bankSyncPromise = null;
    $('#select-account-folders').hidden = true;
    setBusy($('#sync-bank'), false);
    jobPanel.hidden = false; setActiveStep(1);
    analysisPanel.hidden = true; $('#profile-panel').hidden = true; cvPanel.hidden = true;
    $('#bank-documents').replaceChildren(); $('#bank-warnings').replaceChildren();
    $('#profile-tree').replaceChildren(); $('#draft-preview').replaceChildren();
    $('#bank-folder').removeAttribute('href'); $('#drive-folder').removeAttribute('href');
    $('#job-text').value = ''; fileInput.value = ''; renderApplications();
    if (state.photoUrl) URL.revokeObjectURL(state.photoUrl); state.photoUrl = null;
  }
  state.user = user;
  state.idToken = user ? await user.getIdToken() : null;
  window.cvEmployment?.initialize(user, async path => {
    const owner = state.user;
    if (!owner) throw new Error('Inicia sesión para continuar.');
    const token = await owner.getIdToken();
    if (owner.uid !== state.user?.uid) throw new Error('La cuenta cambió.');
    state.idToken = token;
    const header = {Authorization: `Bearer ${token}`};
    return path === 'search' || path === 'automatic-simulation' ? authenticatedHeaders(header) : header;
  }).catch(() => {});
  window.cvTelegram?.initialize(user, authenticatedHeaders).catch(() => {});
  if (state.multiAccount) window.cvOnboarding?.initialize(user, {
    headers: authenticatedHeaders,
    refreshToken: async () => { const owner=state.user; if (owner) { const token=await owner.getIdToken(); if (owner.uid===state.user?.uid) state.idToken=token; } },
    profile: () => state.profile,
    consolidate: async () => { await synchronizeBank(); await loadProfileSummaryWork(); },
    completed: count => { $('#bank-status').textContent = count ? 'Datos guardados y banco consolidado. Puedes seguir agregando archivos en tus carpetas.' : 'Puedes completar tus datos m\u00e1s adelante.'; },
  }).catch(error => showError(error.message));
  $("#google-sign-in").hidden = Boolean(user);
  $("#google-sign-out").hidden = !user;
  $("#auth-user").hidden = !user;
  $("#auth-user").textContent = user ? `Sesión: ${user.email}` : "";
  $("#application-history-panel").hidden = !user;
  $("#auth-help").textContent = user
    ? "Sesión iniciada. Sincroniza para conectar Gmail y Drive; los permisos concedidos se reutilizan al enviar tus CV."
    : "Inicia sesión con la cuenta de Google cuyo banco de datos deseas usar.";
  updateAnalyzeButton();
  if (user) {
    try {
      $("#sync-bank").disabled = false;
      await window.cvBackground.initialize({enabled: state.authRequired && state.provider === 'vertex-ai',
        user: () => state.user, request: directRequestJson,
        file: async url => { state.idToken = await state.user.getIdToken(); return fetch(url, {headers: authenticatedHeaders()}); }});
      if (state.multiAccount) {
        const response = await fetch('/api/account', {headers: authenticatedHeaders()});
        const account = await response.json();
        if (!response.ok) throw new Error(account.error || 'No se pudo consultar tu cuenta.');
        if (user.uid !== state.user?.uid) return;
        state.accountReady = account.ready;
        window.cvDrive.setAccount({...account, email:user.email});
        $('#select-account-folders').hidden = false;
        if (!account.ready || !window.cvDrive.isConnected()) {
          $('#bank-status').textContent = 'Conecta tu Drive. Se crearán Banco de Datos, CV Generados y las cinco subcarpetas que falten.';
          return;
        }
      }
      await loadProfileSummaryWork();
      if (state.bankEnabled) {
        const response = await fetch('/api/bank/status', {headers: authenticatedHeaders()});
        const bank = await response.json();
        if (!response.ok) throw new Error(bank.error || 'No se pudo consultar el banco.');
        if (user.uid !== state.user?.uid) return;
        renderBankStatus(bank);
        if (bank.pending && !window.cvBackground.hasActive()) {
          synchronizeBank().then(() => loadProfileSummary()).catch(error => showError(error.message));
        }
      }
    } catch (error) {
      showError(error.message || "No se pudo cargar el perfil profesional.");
    }
  } else {
    await window.cvBackground.initialize({enabled: false, user: () => null});
    $("#sync-bank").disabled = true;
    $("#bank-documents").replaceChildren();
    $("#bank-warnings").replaceChildren();
    $("#bank-status").textContent = "Inicia sesión para consultar tu banco.";
    window.cvDrive.reset();
    window.cvGmail.reset();
    state.applications = [];
    renderApplications();
    $("#application-history-status").textContent = "Conecta Drive para consultar tus postulaciones.";
    state.profile = null;
    state.profileDraft = null;
    $("#profile-panel").hidden = true;
  }
}

async function initializeGoogleAuth() {
  await loadScript("/__/firebase/10.12.5/firebase-app-compat.js");
  await loadScript("/__/firebase/10.12.5/firebase-auth-compat.js");
  await loadScript("/__/firebase/init.js");
  state.auth = window.firebase.auth();
  const googleProvider = () => {
    const provider = new window.firebase.auth.GoogleAuthProvider();
    if (state.driveEnabled) provider.addScope("https://www.googleapis.com/auth/drive.file");
    if (state.multiAccount) provider.addScope('https://www.googleapis.com/auth/drive.readonly');
    provider.addScope("https://www.googleapis.com/auth/gmail.send");
    provider.setCustomParameters(state.user ? {login_hint:state.user.email, include_granted_scopes:'true'} : {prompt:'select_account', include_granted_scopes:'true'});
    return provider;
  };
  window.cvDrive.setAuthorizationHandler(async () => {
    // Open Google authorization directly from the click, independently of Telegram.
    const result = state.user
      ? await state.user.reauthenticateWithPopup(googleProvider())
      : await state.auth.signInWithPopup(googleProvider());
    state.user = result.user;
    state.idToken = await result.user.getIdToken();
    if (!result.credential?.accessToken) throw new Error("Google no entregó los permisos de Gmail y Drive.");
    return { access_token: result.credential.accessToken, expires_in: 3600, gmailRequested: true };
  });
  state.auth.onIdTokenChanged((user) => {
    updateGoogleUser(user).catch((error) =>
      showError(error.message || "No se pudo comprobar la sesión de Google."),
    );
  });
  $("#google-sign-in").addEventListener("click", async () => {
    const finish = window.cvLoading.start("Iniciando sesión y conectando Drive");
    clearError();
    try {
      const provider = googleProvider();
      const result = await state.auth.signInWithPopup(provider);
      state.user = result.user;
      state.idToken = await result.user.getIdToken();
      await updateGoogleUser(result.user);
      if (state.driveEnabled) await window.cvDrive.acceptCredential(result.credential?.accessToken, { gmailRequested: true });
    } catch (error) {
      showError(error.message || "No se pudo iniciar sesión con Google.");
    } finally { finish(); }
  });
  $("#google-sign-out").addEventListener("click", async () => {
    const finish = window.cvLoading.start("Cerrando sesión");
    clearError();
    try {
      await state.auth.signOut();
    } catch (error) {
      showError(error.message || "No se pudo cerrar la sesión.");
    } finally { finish(); }
  });
}

async function bootstrap() {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    if (!response.ok) throw new Error("La interfaz está publicada, pero el servidor no está disponible. Falta activar Blaze y desplegar el backend en Firebase.");
    const health = await response.json();
    document.querySelector('#employment-panel')?.toggleAttribute('hidden', health.employment_enabled !== true || window.location?.hash !== '#employment-panel');
    document.querySelector('.employment-nav')?.toggleAttribute('hidden', health.employment_enabled !== true);
    document.querySelector('.employment-nav')?.addEventListener('click', () => {
      const panel=document.querySelector('#employment-panel');
      if (panel && health.employment_enabled === true) {panel.hidden=false; panel.scrollIntoView({behavior:'smooth'});}
    });
    state.authRequired = health.auth_required === true;
    state.multiAccount = health.multi_account === true;
    state.profileEditable = health.profile_editable === true;
    state.bankEnabled = health.bank?.provider === "drive";
    $("#bank-panel").hidden = !state.bankEnabled;
    $("#sync-panel").hidden = !state.bankEnabled;
    $("#bank-folder").href = `https://drive.google.com/drive/folders/${health.bank?.folder_id || ""}`;
    $("#sync-bank").disabled = state.authRequired;

    state.driveEnabled = health.archive?.provider === "drive";
    window.cvDrive.initialize(health.archive, authenticatedHeaders).catch(error => showError(error.message));
    if (state.authRequired) {
      $("#auth-panel").hidden = false;
      await initializeGoogleAuth();
    } else {
      await synchronizeBank();
      await loadProfileSummary();
    }

    $("#save-profile").addEventListener("click", saveProfileChanges);
    $("#update-knowledge-map").addEventListener("click", updateKnowledgeMap);
    $("#discard-profile").addEventListener("click", () => {
      state.profileDraft = structuredClone(state.profile);
      state.profileDirty = false;
      $("#profile-error").hidden = true;
      renderProfileTree();
    });
    loadModels(health);
  } catch (error) {
    showError(error.message || "No se pudo iniciar la aplicación.");
    $("#privacy-status").textContent = "Servicio no disponible";
  }
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("No se pudo leer el archivo."));
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.slice(result.indexOf(",") + 1));
    };
    reader.readAsDataURL(file);
  });
}

const jobTextInput = $("#job-text");
const removeJobTextButton = $("#remove-job-text");
function updateRemoveTextButton() {
  removeJobTextButton.disabled = jobTextInput.value.length === 0;
}
function resetVacancyChoice() {
  state.vacancyRevision = (state.vacancyRevision || 0) + 1;
  $("#vacancy-choice").hidden = true;
  $("#vacancy-choice-options").replaceChildren();
}

async function analyzeVacancyRequest(payload) {
  if (window.cvBackground.enabled()) return window.cvBackground.run('/api/analyze', payload);
  if (!state.authRequired || state.provider !== "vertex-ai") return requestJson("/api/analyze", payload);
  const submitted = await requestJson("/api/analyze/jobs", { ...payload, request_id: crypto.randomUUID() });
  for (let attempt = 0; attempt < 300; attempt += 1) {
    const job = await requestJson(`/api/analyze/jobs/${submitted.job_id}`, {});
    if (job.state === "done") return job.result;
    if (job.state === "failed") throw new Error(job.error || "No se pudo completar el análisis.");
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error("El análisis sigue en la cola de procesamiento. Espera unos minutos antes de volver a intentarlo.");
}
jobTextInput.addEventListener("input", () => { state.employmentContact=null; updateRemoveTextButton(); resetVacancyChoice(); });
window.addEventListener('cv-employment-vacancy', event => {
  const text=event.detail?.text;
  if (typeof text!=='string' || !text.trim() || text.length>40000) return;
  event.preventDefault();
  state.analysis=null; state.draft=null; state.pdf=null;
  jobTextInput.value=text; fileInput.value='';
  const contact=event.detail?.contact;
  state.employmentContact=contact && typeof contact.email==='string' && typeof contact.whatsapp==='string'
    ? {email:contact.email,whatsapp:contact.whatsapp,text} : null;
  $('#remove-job-file').hidden=true; $('#file-name').textContent='Vacante seleccionada en Empleo Inteligente.';
  resetVacancyChoice(); updateRemoveTextButton();
  jobPanel.hidden=false; analysisPanel.hidden=true; cvPanel.hidden=true; setActiveStep(1);
  const employmentPanel=$('#employment-panel'); if (employmentPanel) employmentPanel.hidden=true;
  jobPanel.scrollIntoView({behavior:'smooth'});
  const analyze=$('#analyze-button'); if (!analyze.disabled) analyze.click();
});
window.addEventListener("pageshow", updateRemoveTextButton);
removeJobTextButton.addEventListener("click", () => {
  jobTextInput.value = "";
  jobTextInput.dispatchEvent(new Event("input", { bubbles: true }));
  clearError();
  jobTextInput.focus();
});
updateRemoveTextButton();

fileInput.addEventListener("change", () => {
  state.employmentContact=null;
  resetVacancyChoice();
  const file = fileInput.files?.[0];
  $("#remove-job-file").hidden = !file;
  $("#file-name").textContent = file
    ? `${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MB`
    : "También puedes pegar el texto directamente.";
  const visionModel = [...modelSelect.options].find((option) =>
    /^qwen3\.6(?::|$)/i.test(option.value),
  );
  if (file && /\.(pdf|png|jpe?g|webp)$/i.test(file.name) && visionModel) {
    modelSelect.value = visionModel.value;
    state.model = visionModel.value;
  }
  clearError();
});

$("#remove-job-file").addEventListener("click", () => {
  resetVacancyChoice();
  fileInput.value = "";
  $("#remove-job-file").hidden = true;
  $("#file-name").textContent = "Archivo retirado. Puedes adjuntar otro o pegar el texto directamente.";
  clearError();
});

modelSelect.addEventListener("change", () => {
  resetVacancyChoice();
  state.model = modelSelect.value;
});

$("#analyze-button").addEventListener("click", async (event) => {
  if (state.vacancySelecting) return;
  const button = event.currentTarget;
  const revision = state.vacancyRevision || 0;
  clearError();
  setBusy(button, true, "Analizando");
  try {
    const payload = {
      text: $("#job-text").value.trim(),
      model: modelSelect.value,
    };
    const file = fileInput.files?.[0];
    if (file) {
      if (file.size > 10 * 1024 * 1024) {
        throw new Error("El archivo supera el límite de 10 MB.");
      }
      payload.file_name = file.name;
      payload.file_data = await fileToBase64(file);
    }
    if (!window.cvBackground.enabled()) await synchronizeBank();
    const response = await analyzeVacancyRequest(payload);
    handleVacancyResponse(response, payload, revision);
  } catch (error) {
    showError(error.message || "No se pudo analizar la vacante.");
  } finally {
    setBusy(button, false);
    updateAnalyzeButton();
  }
});

function handleVacancyResponse(response, payload, revision = 0) {
  if (revision !== (state.vacancyRevision || 0)) return;
  const choice = $("#vacancy-choice");
  const options = $("#vacancy-choice-options");
  if (response.selection_required) {
    state.analysis = null;
    state.draft = null;
    analysisPanel.hidden = true;
    cvPanel.hidden = true;
    options.replaceChildren();
    choice.hidden = false;
    response.positions.forEach((position) => {
      const button = addText(options, "button", position, "button button-secondary");
      button.type = "button";
      button.addEventListener("click", async () => {
        if (state.vacancySelecting) return;
        state.vacancySelecting = true;
        const buttons = [...options.querySelectorAll("button")];
        buttons.forEach((item) => { item.disabled = true; });
        setBusy(button, true, "Analizando el puesto elegido");
        clearError();
        try {
          const result = await analyzeVacancyRequest({ ...payload, selected_position: position });
          handleVacancyResponse(result, payload, revision);
        } catch (error) { showError(error.message || "No se pudo analizar el puesto elegido."); }
        finally {
          state.vacancySelecting = false;
          setBusy(button, false);
          buttons.forEach((item) => { item.disabled = false; });
        }
      });
    });
    choice.scrollIntoView({ behavior: "smooth", block: "nearest" });
    return;
  }
  choice.hidden = true;
  options.replaceChildren();
  state.analysis = response.analysis;
  if (state.employmentContact && state.employmentContact.text === jobTextInput.value) {
    const contact=state.employmentContact;
    state.analysis.vacancy ||= {};
    if (contact.email) state.analysis.vacancy.application_emails=[contact.email];
    if (contact.whatsapp) state.analysis.vacancy.application_whatsapp=[contact.whatsapp];
  }
  state.model = response.model;
  renderAnalysis(response.analysis);
  jobPanel.hidden = true;
  analysisPanel.hidden = false;
  setActiveStep(2);
}

window.addEventListener('cv-background-result', async event => {
  const {path, result} = event.detail;
  if (path === '/api/analyze') handleVacancyResponse(result, result.selection_payload || {}, state.vacancyRevision || 0);
  if (path === '/api/draft') {
    // A recovered preview must never export a different vacancy's analysis.
    state.analysis = window.cvDraftAnalyses?.get(result.draft) || result.analysis || null;
    state.draft = result.draft;
    await renderDraft(result.draft);
    jobPanel.hidden = true; analysisPanel.hidden = true; cvPanel.hidden = false; setActiveStep(3);
  }
  if (path === '/api/bank/sync') { renderBankStatus(result); await loadProfileSummary(); }
  if (path === '/api/profile/information') {
    $('#information-error').hidden = true;
    state.analysis = null; state.draft = null; state.pdf = null;
    state.vacancyRevision = (state.vacancyRevision || 0) + 1;
    analysisPanel.hidden = true; cvPanel.hidden = true; jobPanel.hidden = false;
    $('#information-status').textContent = result.message;
    if (result.profile) applySavedProfile(result.profile);
    else await loadProfileSummary();
  }
  if (path === '/api/gmail/send' || path === '/api/applications') {
    $('#application-history-status').textContent = result.warning || 'Proceso completado. Conecta Drive para actualizar el historial.';
  }
});

function setActiveStep(active) {
  window.cvUI?.showStep(active);
  document.querySelectorAll("[data-step-indicator]").forEach((step) => {
    step.classList.toggle(
      "active",
      Number(step.dataset.stepIndicator) === active,
    );
  });
}

function renderList(parent, values) {
  if (!values?.length) {
    addText(parent, "p", "No especificado en el anuncio.");
    return;
  }
  const list = addText(parent, "ul", "");
  values.forEach((value) => addText(list, "li", value));
}

function renderAnalysis(analysis) {
  const vacancy = analysis.vacancy;
  const matching = analysis.matching;
  $("#job-title").textContent = vacancy.position || "Análisis de la oportunidad";
  const summary = $("#vacancy-summary");
  summary.replaceChildren();
  [
    ["Nivel", vacancy.seniority],
    ["Sector", vacancy.sector],
    ["Experiencia solicitada", vacancy.experience?.join("; ")],
  ].forEach(([label, value]) => {
    const card = addText(summary, "div", "", "summary-item");
    addText(card, "span", label);
    addText(card, "b", value || "No especificado");
  });

  const details = $("#vacancy-details");
  details.replaceChildren();
  [
    ["Responsabilidades", vacancy.responsibilities],
    ["Requisitos obligatorios", vacancy.mandatory_requirements],
    ["Requisitos deseables", vacancy.desirable_requirements],
    ["Formación solicitada", vacancy.education],
    ["Competencias", vacancy.competencies],
    ["Herramientas e idiomas", [...(vacancy.tools || []), ...(vacancy.languages || [])]],
  ].forEach(([heading, values]) => {
    const card = addText(details, "article", "", "vacancy-detail");
    addText(card, "h3", heading);
    renderList(card, values);
  });

  $("#ideal-candidate").textContent =
    vacancy.ideal_candidate || "No se identificó una descripción adicional.";
  const keywords = $("#keywords");
  keywords.replaceChildren();
  (vacancy.keywords || []).forEach((keyword) =>
    addText(keywords, "span", keyword, "tag"),
  );

  const evidenceList = $("#evidence-list");
  evidenceList.replaceChildren();
  (matching.items || []).forEach((item) => {
    const card = addText(evidenceList, "article", "", "evidence-item");
    const content = addText(card, "div", "");
    addText(content, "b", item.requirement || "Requisito");
    const facts = [];
    (item.experience_ids || []).forEach((id) => {
      const experience = findExperience(id);
      if (!experience) return;
      const selected = (matching.selected_experiences || []).find(
        (entry) => entry.experience_id === id,
      );
      (experience.responsibilities || []).forEach((responsibility) => {
        if (selected?.responsibility_ids?.includes(responsibility.id)) {
          facts.push(`${experience.title} — ${experience.employer}: ${responsibility.text}`);
        }
      });
      if (!selected) facts.push(`${experience.title} — ${experience.employer}`);
    });
    (item.skill_ids || []).forEach((id) => {
      const skill = findSkill(id);
      if (skill) facts.push(skill.label);
    });
    (item.project_ids || []).forEach((id) => {
      const project = (state.profile?.projects || []).find((entry) => entry.id === id);
      if (project) facts.push(`Proyecto: ${project.title} — ${project.description}`);
    });
    addText(
      content,
      "p",
      facts.length ? facts.join(" · ") : "No hay evidencia documentada seleccionada.",
    );
    const typeLabel = {
      directo: "Evidencia directa",
      transferible: "Transferible",
      brecha: "Brecha",
    };
    const typeClass = {
      directo: "direct",
      transferible: "transfer",
      brecha: "gap",
    };
    addText(
      card,
      "span",
      typeLabel[item.type] || "Transferible",
      `evidence-type ${typeClass[item.type] || "transfer"}`,
    );
  });

  const gapBox = $("#gap-box");
  gapBox.replaceChildren();
  if (matching.gaps?.length) {
    addText(gapBox, "b", "Aspectos sin evidencia documentada");
    addText(gapBox, "span", matching.gaps.join(" · "));
    gapBox.hidden = false;
  } else {
    gapBox.hidden = true;
  }
  const template = getTemplateDetails(matching.template);
  $("#template-name").textContent = `Plantilla sugerida: ${template.name}`;
  $("#template-reason").textContent = matching.template_reason || "";
}

function findExperience(id) {
  return (state.profile?.experiences || []).find((item) => item.id === id);
}

function findSkill(id) {
  return (state.profile?.skills || []).find((item) => item.id === id);
}

$("#create-button").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const draftAnalysis = state.analysis;
  try {
    clearError();
    setBusy(button, true, "Generando Hoja de vida");
    const response = await requestJson("/api/draft", {
      analysis: state.analysis,
    });
    state.draft = response.draft;
    window.cvDraftAnalyses ||= new WeakMap();
    window.cvDraftAnalyses.set(response.draft, draftAnalysis);
    await renderDraft(response.draft);
    analysisPanel.hidden = true;
    cvPanel.hidden = false;
    setActiveStep(3);
    await sendApplicationGmail();
  } catch (error) {
    const errorBox = cvPanel.hidden ? $("#gap-box") : $("#cv-error");
    errorBox.hidden = false;
    errorBox.textContent = error.message || "No se pudo crear el CV.";
  } finally {
    setBusy(button, false);
  }
});

function addPreviewSection(parent, title) {
  const section = addText(parent, "section", "", "draft-section");
  addText(section, "h4", title);
  return section;
}

async function renderDraft(draft) {
  for (const id of ['download-pdf', 'download-docx', 'send-whatsapp']) {
    $("#" + id).disabled = !state.analysis;
  }
  $('#back-to-analysis').textContent = state.analysis ? '← Volver al análisis' : '← Analizar otra vez';
  $('#cv-error').hidden = Boolean(state.analysis);
  if (!state.analysis) $('#cv-error').textContent = 'Esta vista previa recuperada no tiene su análisis disponible en esta sesión. Analiza de nuevo la vacante para generar y descargar el CV correcto. Los archivos ya guardados siguen disponibles en Drive.';
  state.pdf = null;
  $("#application-subject").value = draft.position;
  $("#application-message").value = `Hola, me interesa aplicar a la vacante de ${draft.position}. Adjunto mi hoja de vida para su consideración.\n\nSaludos,\n${draft.candidate.name}`;
  const contacts = state.analysis?.vacancy || {};
  $("#application-email").value = contacts.application_emails?.[0] || "";
  $("#application-phone").value = contacts.application_whatsapp?.[0] || "";
  const detected = [...(contacts.application_emails || []), ...(contacts.application_whatsapp || [])];
  $("#application-contacts").textContent = detected.length
    ? "Contactos detectados: " + detected.join(" · ")
    : "El anuncio no indica contactos de postulación. Puedes añadirlos si los conoces.";
  $("#application-send-status").textContent = "";
  const preview = $("#draft-preview");
  preview.replaceChildren();
  const photoResponse = await fetch("/api/profile-photo", {
    cache: "no-store",
    headers: authenticatedHeaders(),
  });
  if (!photoResponse.ok && photoResponse.status !== 404) {
    const error = await photoResponse.json().catch(() => ({}));
    throw new Error(error.error || "No se pudo cargar la fotografía del perfil.");
  }
  if (state.photoUrl) URL.revokeObjectURL(state.photoUrl);
  state.photoUrl = photoResponse.ok ? URL.createObjectURL(await photoResponse.blob()) : null;
  const template = getTemplateDetails(draft.template);
  preview.classList.add("kitchen-preview");
  preview.style.setProperty("--accent", template.accent);
  preview.style.setProperty("--sidebar", template.sidebar);
  const left = addText(preview, "aside", "", "kitchen-sidebar");
  const photo = document.createElement("img");
  photo.className = "kitchen-photo";
  photo.src = state.photoUrl;
  photo.alt = `Fotografía de ${draft.candidate.name}`;
  if (state.photoUrl) left.append(photo);
  addText(left, "h3", draft.candidate.name, "kitchen-name");
  [
    `Cédula: ${draft.candidate.national_id}`,
    draft.candidate.address,
    `Residente en: ${draft.candidate.residence}`,
    "Teléfonos:",
    ...draft.candidate.phones.map((phone, index) => `${index + 1}. ${phone}`),
    `Email: ${draft.candidate.email}`,
  ].forEach((line) => addText(left, "p", line, "kitchen-contact"));
  const skills = addPreviewSection(left, "Habilidades:");
  draft.skills.forEach((skill) => addText(skills, "p", `•  ${skill}`));

  const right = addText(preview, "div", "", "kitchen-content");
  const profile = addPreviewSection(right, "Sobre mi");
  addText(profile, "p", draft.summary, "kitchen-objective");
  const renderProjects = () => {
    if (!draft.projects?.length) return;
    const section = addPreviewSection(right, "Proyectos y experiencia práctica");
    draft.projects.forEach((project) => {
      addText(section, "h5", project.title);
      addText(section, "p", project.description.slice(0, 300));
      if (project.technologies?.length) addText(section, "p", `Tecnologías: ${project.technologies.slice(0, 8).join(", ")}`);
    });
  };
  if (draft.project_focus) renderProjects();
  const education = addPreviewSection(right, "Formación académica");
  addText(education, "h5", "Estudios Académicos");
  draft.education.forEach((item) =>
    addText(education, "p", `•  ${item.institution} (${item.title})`),
  );
  addText(education, "h5", "Cursos Realizados");
  draft.courses.forEach((item) =>
    addText(education, "p", `•  ${item.title} — ${item.institution}`),
  );
  const work = draft.experiences.length ? addPreviewSection(right, draft.experience_heading || "Experiencia laboral") : null;
  draft.experiences.forEach((experience) => {
    const entry = addText(work, "div", "", "experience-preview");
    addText(entry, "p", `${experience.title}: ${experience.employer}`);
    experience.selected_responsibilities.forEach((responsibility) => {
      const label =
        typeof responsibility === "string"
          ? responsibility
          : `${responsibility.employer}: ${responsibility.text}`;
      addText(entry, "p", `•  ${label}`);
    });
  });
  if (!draft.project_focus) renderProjects();
  const references = addPreviewSection(right, "Referencias personales");
  const grid = addText(references, "div", "", "reference-grid");
  draft.references.forEach((item) =>
    addText(
      grid,
      "p",
      `•  ${item.name}\n(${item.role})\nCel. ${item.phone}`,
    ),
  );
  $("#draft-title").textContent = `CV para ${draft.position}`;
  $("#template-confirmation").textContent =
    `El CV aplica el perfil visual ${template.name} y se archiva en la carpeta «CV generados». ` +
    "Revisa las fechas laborales antes de postular: no constan en las fuentes.";
}

async function download(format) {
  const button = format === "pdf" ? $("#download-pdf") : $("#download-docx");
  const cvError = $("#cv-error");
  cvError.textContent = "";
  cvError.hidden = true;
  try {
    if (!state.analysis) throw new Error('Analiza de nuevo esta vacante antes de generar el archivo.');
    setBusy(button, true, format === "pdf" ? "Generando y guardando PDF" : "Generando y guardando Word");
    await window.cvDrive.connect();
    if (state.user) state.idToken = await state.user.getIdToken();
    $("#drive-saved").hidden = true;
    const response = await processFetch(`/api/export/${format}`, {
      method: "POST",
      headers: authenticatedHeaders({ "Content-Type": "application/json", ...window.cvDrive.headers() }),
      body: JSON.stringify({ analysis: state.analysis }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || `No se pudo crear el archivo (${response.status}).`);
    }
    const blob = await response.blob();
    const driveUrl = response.headers.get("X-CV-Drive-URL");
    if (driveUrl?.startsWith("https://drive.google.com/")) {
      const saved = $("#drive-saved");
      saved.replaceChildren();
      const driveLink = addText(saved, "a", "CV guardado en Drive. Abrir archivo");
      driveLink.href = driveUrl; driveLink.target = "_blank"; driveLink.rel = "noopener";
      saved.hidden = false;
    }
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const fileName = match?.[1] || `CV.${format}`;
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = fileName;
    link.click();
    URL.revokeObjectURL(link.href);
    const artifact = { driveUrl: driveUrl || "", fileName };
    if (format === "pdf") state.pdf = artifact;
    return artifact;
  } catch (error) {
    cvError.textContent = error.message || "No se pudo descargar el CV.";
    cvError.hidden = false;
    return null;
  } finally {
    setBusy(button, false);
  }
}

$("#download-pdf").addEventListener("click", () => download("pdf"));
$("#download-docx").addEventListener("click", () => download("docx"));

async function applicationRequest(payload) {
  if (state.user) state.idToken = await state.user.getIdToken();
  const response = await processFetch("/api/applications", {
    method: payload ? "POST" : "GET",
    headers: authenticatedHeaders({ "Content-Type": "application/json", ...window.cvDrive.headers() }),
    ...(payload ? { body: JSON.stringify(payload) } : {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "No se pudo consultar o guardar el historial en Drive.");
  return data;
}

function renderApplications() {
  const list = $("#application-history");
  list.replaceChildren();
  state.applications.forEach((entry) => {
    const card = addText(list, "article", "", "application-history-entry");
    addText(card, "h3", entry.position);
    addText(card, "p", `${entry.channel === "gmail" ? "Gmail" : "WhatsApp"} · ${entry.recipient}`);
    const labels = {
      confirmed_by_user: "Enviado (confirmado por ti)", gmail_accepted: "Enviado · confirmado por Gmail",
      sending: "En proceso · comprueba Enviados en Gmail", send_unknown: "Sin confirmar · comprueba Enviados en Gmail",
      failed: "Gmail rechazó el envío", prepared: "Preparado · envío pendiente de confirmar",
      whatsapp_opened: "WhatsApp abierto · postulación registrada automáticamente",
    };
    addText(card, "p", `${new Date(entry.date).toLocaleString("es-DO")} · ${labels[entry.status] || "Estado pendiente de revisar"}`);
    if (/^https:\/\/drive\.google\.com\/file\/d\/[A-Za-z0-9_-]+\/view$/.test(entry.cv_url || "")) {
      const link = addText(card, "a", "Ver CV en Drive");
      link.href = entry.cv_url; link.target = "_blank"; link.rel = "noopener";
    }
    if (entry.status === "prepared" || entry.status === "whatsapp_opened") {
      const confirm = addText(card, "button", "Ya envié este CV", "button button-secondary");
      confirm.type = "button";
      confirm.addEventListener("click", async () => {
        setBusy(confirm, true, "Guardando confirmación");
        try {
          const result = await applicationRequest({ ...entry, status: "confirmed_by_user" });
          Object.assign(entry, result.entry);
          renderApplications();
          $("#application-history-status").textContent = "Envío confirmado por ti y guardado en Drive.";
        } catch (error) { $("#application-history-status").textContent = error.message; }
        finally { setBusy(confirm, false); }
      });
    }
  });
}

async function refreshApplications() {
  const button = $("#refresh-application-history");
  setBusy(button, true, "Cargando historial de envío");
  try {
    await window.cvDrive.connect();
    const data = await applicationRequest();
    state.applications = data.entries || [];
    renderApplications();
    $("#application-history-status").textContent = data.has_more
      ? "Se muestran las postulaciones de los 100 registros más recientes. El historial completo permanece en Drive."
      : state.applications.length ? "Historial actualizado desde Drive." : "Todavía no has preparado postulaciones.";
  } catch (error) { $("#application-history-status").textContent = error.message; }
  finally { setBusy(button, false); }
}

async function prepareApplication(channel, button) {
  if (channel === "gmail") return sendApplicationGmail(button);
  if (state.whatsappPreparing) return;
  let recipient = $(channel === "gmail" ? "#application-email" : "#application-phone").value.trim();
  const status = $("#application-send-status");
  if (!state.draft) return;
  if (channel === "gmail" && !/^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/.test(recipient)) {
    status.textContent = "Indica un correo válido del anuncio antes de abrir Gmail."; return;
  }
  if (channel === "whatsapp") {
    recipient = recipient.replace(/[^\d]/g, "");
    if (recipient.length === 10 && /^(809|829|849)/.test(recipient)) recipient = "1" + recipient;
    if (!/^[1-9]\d{7,14}$/.test(recipient)) {
      status.textContent = "Indica el número de WhatsApp completo, incluido su código de país."; return;
    }
  }
  if (!window.cvDrive.isConnected()) {
    try { await window.cvDrive.connect(); status.textContent = "Drive conectado. Pulsa de nuevo para preparar la postulación."; }
    catch (error) { status.textContent = error.message; }
    return;
  }
  const popup = window.open("about:blank", "_blank");
  if (!popup) { status.textContent = "Permite abrir ventanas para Gmail o WhatsApp y vuelve a pulsar."; return; }
  popup.opener = null;
  state.whatsappPreparing = true;
  setBusy(button, true, "Preparando postulación y PDF");
  try {
    const pdf = await download("pdf");
    if (!pdf) throw new Error("No se pudo preparar el PDF. Revisa el aviso anterior.");
    const position = state.draft.position;
    const body = `Postulación: ${position}\n\nHola, me interesa aplicar a la vacante de ${position}. Adjunto mi hoja de vida para su consideración.\n\nSaludos,\n${state.draft.candidate.name}`;
    const url = channel === "gmail"
      ? "https://mail.google.com/mail/u/0/?" + new URLSearchParams({ view: "cm", fs: "1", to: recipient, su: position, body })
      : `https://wa.me/${recipient}?` + new URLSearchParams({ text: body });
    const record = { application_id: crypto.randomUUID(), position, recipient, channel, status: "whatsapp_opened", cv_url: pdf.driveUrl };
    try {
      const result = await applicationRequest(record);
      state.applications.unshift(result.entry); renderApplications();
      status.textContent = "Postulación de WhatsApp guardada automáticamente en el historial con vacante, número, fecha y CV. Adjunta el PDF descargado y envíalo en WhatsApp. Puedes confirmar el envío en el historial.";
    } catch (error) {
      status.textContent = `PDF descargado. ${error.message} El historial no quedó guardado. Adjunta el PDF y completa el envío en la aplicación.`;
    }
    // Persist before launching the native app: mobile browsers may suspend this page.
    popup.location.href = url;
  } catch (error) { popup.close(); status.textContent = error.message; }
  finally { state.whatsappPreparing = false; setBusy(button, false); }
}

async function sendApplicationGmail(button) {
  if (state.gmailSending || !state.draft) return;
  const status = $("#application-send-status");
  const recipient = $("#application-email").value.trim();
  const message = $("#application-message").value.trim();
  if (!/^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/.test(recipient)) {
    status.textContent = "No se envió automáticamente: la vacante no indica un correo válido."; return;
  }
  if (!message || message.length > 5000) { status.textContent = "Revisa el mensaje antes de enviar."; return; }
  if (!window.cvDrive.isConnected()) {
    try { await window.cvDrive.connect({ requireGmail: true }); }
    catch (error) { status.textContent = error.message; return; }
  }
  if (state.gmailSending) return;
  if (state.gmailAttempt?.unknown) {
    status.textContent = "No se confirmó la respuesta del envío anterior. Comprueba Enviados en Gmail antes de generar otra postulación."; return;
  }
  const signature = JSON.stringify([recipient, message, state.analysis]);
  if (state.gmailAttempt?.signature !== signature) state.gmailAttempt = { id: crypto.randomUUID(), signature };
  const attempt = state.gmailAttempt;
  if (attempt.sent) { status.textContent = `Gmail ya confirmó el envío a ${recipient}.`; return; }
  state.gmailSending = true;
  status.textContent = "Enviando automáticamente el mensaje y el CV por Gmail…";
  if (button) setBusy(button, true, "Autorizando Gmail y enviando CV");
  let submitted = false, responded = false, sent = false;
  try {
    await window.cvGmail.connect();
    if (state.user) state.idToken = await state.user.getIdToken();
    const headers = authenticatedHeaders({"Content-Type": "application/json", ...window.cvDrive.headers(), ...window.cvGmail.headers()});
    submitted = true;
    const response = await processFetch("/api/gmail/send", {
      method: "POST", headers,
      body: JSON.stringify({ application_id: attempt.id, recipient, message, analysis: state.analysis }),
    });
    const result = await response.json().catch(() => ({}));
    responded = true;
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) window.cvGmail.reset();
      attempt.unknown = response.status >= 500 || response.status === 409;
      throw new Error(result.error || "No se pudo confirmar el envío. Comprueba Enviados en Gmail.");
    }
    if (result.entry?.status !== "gmail_accepted") { attempt.unknown = true; throw new Error("Gmail no confirmó el envío. Comprueba Enviados."); }
    sent = true;
    attempt.sent = true;
    state.applications = [result.entry, ...state.applications.filter(entry => entry.application_id !== attempt.id)];
    renderApplications();
    status.textContent = result.warning || `Gmail confirmó el envío a ${recipient}, con asunto «${state.draft.position}» y el PDF adjunto. El historial quedó guardado en Drive.`;
  } catch (error) {
    if (submitted && !responded) attempt.unknown = true;
    status.textContent = error.message || "No se pudo confirmar el envío. Revisa Enviados en Gmail.";
  } finally {
    state.gmailSending = false;
    if (button) { setBusy(button, false); if (sent) button.disabled = true; }
  }
}

$("#send-whatsapp").addEventListener("click", (event) => prepareApplication("whatsapp", event.currentTarget));
$("#refresh-application-history").addEventListener("click", refreshApplications);
window.addEventListener('cv-account-ready', event => { state.accountReady = event.detail.ready; });
window.addEventListener("cv-drive-connected", async () => {
  refreshApplications();
  if (state.multiAccount) {
    const uid = state.user?.uid;
    try {
      const response = await fetch('/api/bank/status', {headers: authenticatedHeaders()});
      const bank = await response.json();
      if (uid !== state.user?.uid) return;
      if (!response.ok) throw new Error(bank.error || 'No se pudo leer el banco.');
      renderBankStatus(bank);
      if (bank.pending) await synchronizeBank();
      if (uid === state.user?.uid) { await loadProfileSummaryWork(); await window.cvOnboarding?.check(); }
    } catch (error) { showError(error.message); }
  }
});
$('#select-account-folders').addEventListener('click', async () => {
  clearError();
  try { await window.cvDrive.chooseFolders(); } catch (error) { showError(error.message); }
});

$("#back-to-job").addEventListener("click", () => {
  analysisPanel.hidden = true;
  jobPanel.hidden = false;
  cvPanel.hidden = true;
  setActiveStep(1);
});

$("#back-to-analysis").addEventListener("click", () => {
  cvPanel.hidden = true;
  if (!state.analysis) {
    analysisPanel.hidden = true;
    jobPanel.hidden = false;
    setActiveStep(1);
    return;
  }
  renderAnalysis(state.analysis);
  analysisPanel.hidden = false;
  setActiveStep(2);
});

window.cvLoading.run("Cargando", bootstrap);
