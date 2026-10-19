(function (root) {
  'use strict';
  const R = 6371008.8;
  const radians = value => value * Math.PI / 180;
  const degrees = value => value * 180 / Math.PI;
  function destination(origin, east, north) {
    const angular = Math.hypot(east, north) / R, bearing = Math.atan2(east, north);
    const lat = radians(origin.lat), lng = radians(origin.lng);
    const next = Math.asin(Math.sin(lat) * Math.cos(angular) + Math.cos(lat) * Math.sin(angular) * Math.cos(bearing));
    const lon = lng + Math.atan2(Math.sin(bearing) * Math.sin(angular) * Math.cos(lat), Math.cos(angular) - Math.sin(lat) * Math.sin(next));
    return {lat: degrees(next), lng: ((degrees(lon) + 540) % 360) - 180};
  }
  function detect(navigatorObject) {
    return new Promise((resolve, reject) => {
      if (!navigatorObject.geolocation) return reject(new Error('Este dispositivo no ofrece geolocalización. Introduce las coordenadas.'));
      navigatorObject.geolocation.getCurrentPosition(position => resolve({
        lat: position.coords.latitude, lng: position.coords.longitude, accuracy_m: position.coords.accuracy,
      }), error => reject(new Error({1: 'Permiso rechazado. Puedes introducir tu ubicación manualmente.',
        2: 'Ubicación no disponible. Revisa la señal o corrige las coordenadas.',
        3: 'Se agotó el tiempo de espera. Reintenta o usa la corrección manual.'}[error.code] || 'No se pudo obtener la ubicación.')),
      {enableHighAccuracy: true, timeout: 12000, maximumAge: 0});
    });
  }
  const api = {detect, destination};
  if (typeof module !== 'undefined') module.exports = api;
  root.cvEmployment = api;
  if (!root.document) return;
  const $ = selector => root.document.querySelector(selector);
  let user = null, headers = null, session = 0, confirmed = null, anchor = null;
  const currentApplications = new Set();
  let marker = {x: 300, y: 160}, dragging = false, addressDirty = false;
  let liveMap=null, liveMarker=null, liveCircle=null, savedCircle=null;
  const panel = $('#employment-panel');
  if (!panel) return;
  const form = $('#employment-location-form'), message = $('#employment-status');
  const field = name => form.elements.namedItem(name);
  const status = text => { message.textContent = text; };
  async function useGenerator(offer, contact) {
    if (contact === undefined && offer.id) {
      try {contact=(await request(`offers/${offer.id}/contact`)).contact || {};}
      catch(error) {searchStatus(error.message); return;}
    }
    contact ||= {};
    if (offer.description_verified === false) {
      searchStatus('Esta oferta solo tiene un resumen. Abre el anuncio original, copia sus requisitos y pégalos en Descripción del puesto para adaptar tu CV.');
      return;
    }
    closeJobResults();
    const contactText=[contact.email ? `Correo de postulación: ${contact.email}` : '', contact.whatsapp ? `WhatsApp de postulación: ${contact.whatsapp}` : ''].filter(Boolean).join('\n');
    const text=`${offer.title} · ${offer.company || ''}\n\n${offer.description}`.slice(0,39000)+(contactText ? '\n\n'+contactText : '');
    const event=new root.CustomEvent('cv-employment-vacancy',{detail:{text,contact},cancelable:true});
    if (root.dispatchEvent(event)) {$('#job-text').value=text; $('#job-text').scrollIntoView({behavior:'smooth'}); $('#job-text').focus();}
  }
  async function request(path, method = 'GET', payload) {
    const ticket = session;
    if (!user || !headers) throw new Error('Inicia sesión para continuar.');
    const requestHeaders = await headers(path);
    if (ticket !== session) throw new Error('La sesi\u00f3n cambi\u00f3.');
    const response = await root.fetch('/api/employment/' + path, {method,
      headers: {...requestHeaders, 'Content-Type': 'application/json'},
      ...(payload === undefined ? {} : {body: JSON.stringify(payload)}), cache: 'no-store'});
    const data = await response.json();
    if (ticket !== session) throw new Error('La sesi\u00f3n cambi\u00f3.');
    if (!response.ok) throw new Error(data.error || 'No se pudo completar la operación.');
    return data;
  }
  function point() {return {lat: Number(field('lat').value), lng: Number(field('lng').value)};}
  function validPoint() {
    return field('lat').value !== '' && field('lng').value !== '' &&
      Math.abs(point().lat) <= 90 && Math.abs(point().lng) <= 180;
  }
  function draw(recenter = false) {
    const svg = $('#employment-map');
    if (!validPoint()) {svg.setAttribute('hidden', ''); if ($('#employment-map-live')) $('#employment-map-live').hidden=true; return;}
    if (root.L && $('#employment-map-live')) {
      svg.setAttribute('hidden',''); $('#employment-map-live').hidden=false;
      const center=point(), radius=Number(field('radius_m').value);
      if (!liveMap) {
        liveMap=root.L.map('employment-map-live').setView([center.lat,center.lng],13);
        root.L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{
          maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(liveMap);
        liveMarker=root.L.marker([center.lat,center.lng],{draggable:true,title:'Ubicación laboral: arrastra para corregir'}).addTo(liveMap);
        liveMarker.on('dragend',()=>{const next=liveMarker.getLatLng(); field('lat').value=next.lat.toFixed(4); field('lng').value=next.lng.toFixed(4);
          field('accuracy_m').value=100; addressDirty=false; draw(); status('Punto corregido. Pulsa Confirmar ubicación para guardarlo.');});
        liveCircle=root.L.circle([center.lat,center.lng],{radius,color:'#c17836',fillOpacity:0.08}).addTo(liveMap);
      }
      liveMarker.setLatLng([center.lat,center.lng]); liveCircle.setLatLng([center.lat,center.lng]).setRadius(radius);
      const same=confirmed && Math.abs(confirmed.lat-center.lat)<0.00005 && Math.abs(confirmed.lng-center.lng)<0.00005 && confirmed.radius_m===radius;
      liveCircle.setStyle({color:same?'#315d46':'#c17836'});
      if (savedCircle) {savedCircle.remove(); savedCircle=null;}
      if (confirmed && !same) savedCircle=root.L.circle([confirmed.lat,confirmed.lng],{radius:confirmed.radius_m,color:'#315d46',dashArray:'6 6',fillOpacity:0.03}).addTo(liveMap);
      liveMap.invalidateSize(); if (recenter) liveMap.fitBounds(liveCircle.getBounds(),{padding:[20,20],maxZoom:17});
      return;
    }
    svg.removeAttribute('hidden');
    if (recenter || !anchor) {anchor = point(); marker = {x:300, y:160};}
    $('#employment-marker').setAttribute('cx', marker.x);
    $('#employment-marker').setAttribute('cy', marker.y);
    const circle = $('#employment-radius');
    circle.setAttribute('cx', marker.x); circle.setAttribute('cy', marker.y);
    circle.setAttribute('r', 105);
    $('#employment-scale').textContent = `${Number(field('radius_m').value) / 1000} km desde el punto editable`;
    $('#employment-map-coordinates').textContent = `${point().lat.toFixed(4)}, ${point().lng.toFixed(4)}`;
  }
  function move(x, y) {
    const radius = Number(field('radius_m').value), metersPerPixel = radius / 105;
    marker = {x: Math.max(20, Math.min(580, x)), y: Math.max(20, Math.min(300, y))};
    const next = destination(anchor, (marker.x - 300) * metersPerPixel, (160 - marker.y) * metersPerPixel);
    field('lat').value = next.lat.toFixed(4); field('lng').value = next.lng.toFixed(4);
    field('accuracy_m').value = 100;
    addressDirty = false;
    status('Punto corregido manualmente. Pulsa Confirmar ubicación.'); draw();
  }
  function populate(data) {
    for (const name of ['country','region','city','reference','lat','lng','accuracy_m','radius_m']) field(name).value = data?.[name] ?? (name === 'radius_m' ? 10000 : name === 'accuracy_m' ? 100 : '');
    field('radius_km').value = Number(field('radius_m').value) / 1000;
    // Stored uncertainty includes the 16 m quantization bound; do not add it twice on roundtrip.
    if (data) field('accuracy_m').value = Math.max(0, data.accuracy_m - 16);
    field('allowed_countries').value = (data?.allowed_countries || []).join(',');
    field('allow_remote').checked = Boolean(data?.allow_remote);
    field('allow_travel').checked = Boolean(data?.allow_travel);
    if (field('public_place')) field('public_place').value='';
    addressDirty = false; anchor = null; draw(true);
    $('#employment-confirmed').textContent = data ? `Ubicación confirmada · distancia máxima ${data.radius_m / 1000} km` : 'Usa tu ubicación para comenzar.';
  }
  api.initialize = async function (nextUser, getHeaders) {
    if (user && nextUser?.uid === user.uid) { user = nextUser; headers = getHeaders; return; }
    root.dispatchEvent(new root.CustomEvent('cv-employment-session'));
    session++; user = nextUser; headers = getHeaders; confirmed = null; populate(null);
    currentApplications.clear();
    $('#employment-results').replaceChildren(); $('#employment-applications')?.replaceChildren();
    latestPublications=null; publicationDay=''; calendarMonth='';
    currentSearch=null;
    $('#employment-sources').replaceChildren();
    $('#employment-source-filter').value='';
    closeOfferContact(false);
    closeJobResults();
    $('#employment-results-open').hidden=true;
    $('#employment-results-status').textContent='';
    if ($('#employment-calendar')) $('#employment-calendar').hidden=true;
    $('#employment-geocode-results').replaceChildren();
    $('#employment-authorization-status').textContent = 'Sin autorización automática.';
    $('#employment-authorization-form').reset();
    if (liveMap) {liveMap.remove(); liveMap=null; liveMarker=null; liveCircle=null; savedCircle=null;}
    if ($('#employment-map-live')) $('#employment-map-live').hidden=true;
    $('#employment-location-button').disabled = !user;
    $('#employment-location-form').querySelectorAll('button,input').forEach(input => {input.disabled = !user;});
    if ($('.employment-login-link')) $('.employment-login-link').hidden=Boolean(user);
    if (!user) {status('Inicia sesión para guardar una ubicación privada.'); return;}
    const ticket = session;
    try {const data = await request('location'); if (ticket !== session) return; confirmed = data.location; populate(confirmed); status('Escribe un cargo o pulsa Ver últimas publicadas. Tu ubicación es opcional.');
      const scope = await request('authorization'); if (scope.authorization) $('#employment-authorization-status').textContent = `Simulación autorizada hasta ${scope.authorization.expires_at}. Límite diario ${scope.authorization.daily_limit}.`;
    }
    catch (error) {if (ticket === session) status(error.message);}
  };
  async function resolveCountry() {
    const center = point();
    const data = await request('reverse-geocode', 'POST', center);
    if (point().lat !== center.lat || point().lng !== center.lng) throw new Error('El punto cambió. Reintenta con la ubicación actual.');
    const result = data.results?.[0];
    if (!result || !/^[A-Z]{2}$/.test(result.country)) throw new Error('No se pudo identificar el país. Reintenta.');
    for (const name of ['country','region','city']) field(name).value = result[name] || '';
    field('allowed_countries').value = result.country;
    field('allow_remote').checked = true;
  }
  $('#employment-location-button').addEventListener('click', async () => {
    const ticket = session, button = $('#employment-location-button'); button.disabled = true;
    status('Esperando permiso y señal de ubicación…');
    try {const data = await detect(root.navigator); if (ticket !== session) return;
      for (const name of ['lat','lng','accuracy_m']) field(name).value = data[name];
      for (const name of ['country','region','city','reference','allowed_countries']) field(name).value = '';
      addressDirty = false; draw(true); status('Identificando país y ciudad…');
      await resolveCountry();
      if (ticket !== session) return;
      status('Ubicación lista. Elige la distancia en km y confirma para buscar empleos.');
    } catch (error) {if (ticket === session) status(error.message);}
    finally {if (ticket === session) button.disabled = !user;}
  });
  for (const name of ['country','region','city','reference']) field(name).addEventListener('input', () => {
    addressDirty = true; status('La dirección cambió. Localízala o corrige las coordenadas antes de confirmar.');
  });
  for (const name of ['lat','lng']) field(name).addEventListener('input', () => {
    addressDirty = false; field('accuracy_m').value = 100; draw(true);
  });
  field('radius_km').addEventListener('input', () => {field('radius_m').value = Number(field('radius_km').value) * 1000; draw(true); status('Radio editable. Pulsa Confirmar ubicación para usarlo en búsquedas.');});
  panel.querySelectorAll('[data-radius]').forEach(button => button.addEventListener('click', () => {
    field('radius_m').value = button.dataset.radius; field('radius_km').value = Number(button.dataset.radius) / 1000; draw(true);
    status('Radio editable. Pulsa Confirmar ubicación para guardarlo.');
  }));
  const svg = $('#employment-map'), pin = $('#employment-marker');
  const pointer = event => {const rect = svg.getBoundingClientRect(); move((event.clientX - rect.left) * 600 / rect.width, (event.clientY - rect.top) * 320 / rect.height);};
  pin.addEventListener('pointerdown', event => {event.preventDefault(); dragging = true; pin.setPointerCapture(event.pointerId);});
  pin.addEventListener('pointermove', event => {if (dragging) pointer(event);});
  for (const name of ['pointerup','pointercancel','lostpointercapture']) pin.addEventListener(name, () => {dragging = false;});
  pin.addEventListener('keydown', event => {
    const delta = {ArrowLeft: [-2,0], ArrowRight: [2,0], ArrowUp: [0,-2], ArrowDown: [0,2]}[event.key];
    if (delta) {event.preventDefault(); move(marker.x + delta[0], marker.y + delta[1]);}
  });
  $('#employment-geocode').addEventListener('click', async () => {
    const ticket = session, address = ['public_place','city','region'].map(name => field(name)?.value || '').filter(Boolean).join(', ');
    try {const data = await request('geocode', 'POST', {country:field('country').value, address});
      if (ticket !== session) return;
      const container = $('#employment-geocode-results'); container.replaceChildren();
      for (const result of data.results) {const button = root.document.createElement('button');
        button.type = 'button'; button.textContent = result.label;
        button.addEventListener('click', () => {field('lat').value = result.lat; field('lng').value = result.lng;
          for (const name of ['country','region','city']) if (result[name]) field(name).value=result[name];
          if (!field('allowed_countries').value && result.country) field('allowed_countries').value=result.country;
          field('accuracy_m').value = result.accuracy_m; addressDirty = false; draw(true); status('Resultado seleccionado. Revisa y confirma.');}); container.append(button);}
      status(data.results.length ? 'Selecciona el resultado correcto.' : 'No hay resultados verificables.');
    } catch (error) {if (ticket === session) status(error.message);}
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (addressDirty) {status('Localiza la dirección o corrige las coordenadas después del cambio.'); return;}
    if (!validPoint()) {status('Introduce latitud y longitud válidas.'); return;}
    const payload = {};
    for (const name of ['country','region','city','reference']) payload[name] = field(name).value;
    for (const name of ['lat','lng','accuracy_m','radius_m']) payload[name] = Number(field(name).value);
    payload.allowed_countries = field('allowed_countries').value.split(',').map(c => c.trim()).filter(Boolean);
    for (const name of ['allow_remote','allow_travel']) payload[name] = field(name).checked;
    try {await resolveCountry();
      for (const name of ['country','region','city']) payload[name] = field(name).value;
      payload.allowed_countries = [field('country').value]; payload.allow_remote = true;
      const data = await request('location','PUT',payload); confirmed = data.location; populate(confirmed);
      $('#employment-authorization-status').textContent = 'Sin autorización automática: la ubicación cambió.';
      status('Ubicación guardada. Las aprobaciones anteriores requieren nueva revisión.');}
    catch (error) {status(error.message);}
  });
  $('#employment-delete').addEventListener('click', async () => {
    try {await request('location','DELETE'); confirmed = null; populate(null);
      $('#employment-results').replaceChildren(); $('#employment-applications')?.replaceChildren();
    latestPublications=null; publicationDay=''; calendarMonth='';
    currentSearch=null;
    $('#employment-sources').replaceChildren();
    $('#employment-source-filter').value='';
    closeJobResults();
    $('#employment-results-open').hidden=true;
    $('#employment-results-status').textContent='';
    if ($('#employment-calendar')) $('#employment-calendar').hidden=true;
      $('#employment-authorization-status').textContent = 'Sin autorización automática.';
      status('Ubicación eliminada; permisos revocados.');}
    catch (error) {status(error.message);}
  });
  async function prepareCurrentApplication(path, payload) {
    const ticket = session;
    const item = await request(path, 'POST', payload);
    if (ticket !== session) throw new Error('La sesi\u00f3n cambi\u00f3.');
    if (item.id) currentApplications.add(item.id);
    await renderApplications();
  }
  async function renderApplications() {
    const container = $('#employment-applications');
    if (!container) return;
    const data = await request('applications'); container.replaceChildren();
    for (const item of data.applications.filter(item => currentApplications.has(item.id))) {const card = root.document.createElement('article');
      const label = root.document.createElement('p'); label.textContent = `${item.position || 'Candidatura'}${item.company ? ' · '+item.company : ''} · ${item.status} · ${item.result || 'Revisa antes de aprobar.'}`; card.append(label);
      if (item.url) {const link=root.document.createElement('a'); link.href=item.url; link.target='_blank'; link.rel='noopener noreferrer'; link.textContent='Continuar en la fuente original'; card.append(link);}
      if (item.status === 'PENDIENTE DE APROBACIÓN') {const check = root.document.createElement('input'); check.type = 'checkbox';
        const consent = root.document.createElement('label'); consent.append(check, ' He revisado y autorizo abrir esta candidatura en la fuente original.'); card.append(consent);
        const button = root.document.createElement('button'); button.type = 'button'; button.textContent = 'Aprobar y continuar en el portal';
        button.addEventListener('click', async () => {if (!check.checked) {status('Marca la autorización antes de continuar.'); return;}
          const popup=root.open('about:blank','_blank'); if (popup) popup.opener=null;
          if (!popup) {status('El navegador bloqueó la ventana. Permite ventanas emergentes y vuelve a aprobar; no se ha enviado la candidatura.'); return;}
          try {const accepted=await request(`applications/${item.id}/open-official`,'POST',{confirmed:true}); if (popup) popup.location.href=accepted.url;
            await renderApplications(); status('Completa la postulación en la fuente original. El envío aún no está confirmado.');}
          catch (error) {if (popup) popup.close(); status(error.message);}}); card.append(button);}
      if (item.status !== 'CANCELADA') {const cancel = root.document.createElement('button'); cancel.type = 'button'; cancel.textContent = 'Cancelar';
        cancel.addEventListener('click', async () => {try {await request(`applications/${item.id}/cancel`,'POST',{}); await renderApplications();} catch (error) {status(error.message);}}); card.append(cancel);}
      container.append(card);}
  }
  let latestPublications = null, publicationDay = '', calendarMonth = '';
  let currentSearch = null;
  let contactOffer = null, contactRevision = 0, returnToResults = false;
  const contactDialog = $('#employment-contact-dialog');
  function resetOfferContact() {
    contactRevision++; contactOffer=null;
    $('#employment-contact-email').value=''; $('#employment-contact-whatsapp').value='';
    $('#employment-contact-position').textContent=''; $('#employment-contact-description').textContent='';
    $('#employment-contact-source').textContent=''; $('#employment-contact-status').textContent='';
    $('#employment-contact-original').hidden=true; $('#employment-contact-original').removeAttribute('href');
    $('#employment-contact-save').disabled=true;
    $('#employment-contact-adapt').disabled=true;
  }
  function closeOfferContact(showResults=true) {
    const restore=showResults && returnToResults && currentSearch;
    returnToResults=false; resetOfferContact();
    if (contactDialog.open) contactDialog.close();
    if (restore) openJobResults();
  }
  contactDialog.addEventListener('cancel',event=>{event.preventDefault();closeOfferContact();});
  contactDialog.addEventListener('close',()=>{if (!contactDialog.open && contactOffer) closeOfferContact();});
  $('#employment-contact-close').addEventListener('click',()=>closeOfferContact());
  contactDialog.addEventListener('click',event=>{if(event.target===contactDialog) closeOfferContact();});
  async function openOfferContact(offer) {
    returnToResults=$('#employment-results-dialog').open;
    resetOfferContact(); contactOffer=offer;
    const revision=contactRevision;
    closeJobResults();
    $('#employment-contact-position').textContent=offer.title;
    $('#employment-contact-source').textContent=`${offer.source || 'Chiripas'}${offer.source_key==='rdtrabaja' ? ' · anuncio ' + offer.source_job_id : ''}`;
    $('#employment-contact-description').textContent=offer.description;
    const link=$('#employment-contact-original');
    if(trustedPortal(offer.url)) {link.href=offer.url; link.hidden=false;}
    link.textContent=offer.source_key==='rdtrabaja' ? 'Buscar este cargo en RD Trabaja (portal original)' : 'Abrir este anuncio en su portal original';
    $('#employment-contact-email').disabled=true; $('#employment-contact-whatsapp').disabled=true;
    $('#employment-contact-status').textContent='Cargando el contacto guardado…';
    contactDialog.showModal();
    try {
      const data=await request(`offers/${offer.id}/contact`);
      if(revision!==contactRevision) return;
      $('#employment-contact-email').value=data.contact?.email || '';
      $('#employment-contact-whatsapp').value=data.contact?.whatsapp || '';
      $('#employment-contact-status').textContent='Añade o actualiza el contacto de esta oferta.';
      $('#employment-contact-save').disabled=false;
      $('#employment-contact-adapt').disabled=false;
      $('#employment-contact-email').disabled=false; $('#employment-contact-whatsapp').disabled=false;
    } catch(error) {if(revision===contactRevision) $('#employment-contact-status').textContent=error.message;}
  }
  async function saveOfferContact(adapt=false) {
    if(!contactOffer || $('#employment-contact-save').disabled) return;
    if (!$('#employment-contact-form').reportValidity()) return;
    const revision=contactRevision, offer=contactOffer;
    $('#employment-contact-save').disabled=true; $('#employment-contact-adapt').disabled=true;
    $('#employment-contact-email').disabled=true; $('#employment-contact-whatsapp').disabled=true;
    try {
      const data=await request(`offers/${offer.id}/contact`,'PUT',{
        email:$('#employment-contact-email').value.trim(), whatsapp:$('#employment-contact-whatsapp').value.trim()});
      if(revision!==contactRevision) return;
      $('#employment-contact-email').value=data.contact.email; $('#employment-contact-whatsapp').value=data.contact.whatsapp;
      $('#employment-contact-status').textContent='Contacto guardado. Puedes adaptar tu CV desde esta ventana.';
      if (adapt) {closeOfferContact(false); await useGenerator(offer, data.contact);}
    } catch(error) {if(revision===contactRevision) $('#employment-contact-status').textContent=error.message;}
    finally {
      if(revision===contactRevision) {
        $('#employment-contact-save').disabled=false; $('#employment-contact-adapt').disabled=false;
        $('#employment-contact-email').disabled=false; $('#employment-contact-whatsapp').disabled=false;
      }
    }
  }
  $('#employment-contact-form').addEventListener('submit',event=>{event.preventDefault();saveOfferContact();});
  $('#employment-contact-adapt').addEventListener('click',()=>saveOfferContact(true));
  const sourceKey = offer => offer.source_key || offer.source || 'chiripas';
  function filteredSource(data) {
    const selected = $('#employment-source-filter').value;
    return selected ? data.offers.filter(offer => sourceKey(offer) === selected) : data.offers;
  }
  function trustedPortal(url) {
    try {
      const parsed = new URL(url);
      return parsed.protocol === 'https:' && !parsed.username && !parsed.password && !parsed.port &&
        ['chiripas.com','tuempleord.do','tuvacanterd.com','rdtrabaja.mt.gob.do','www.aldaba.com','do.computrabajo.com'].includes(parsed.hostname);
    } catch {return false;}
  }
  function renderSources(data) {
    const list = $('#employment-sources'); list.replaceChildren();
    for (const source of data.sources || []) {
      const item = root.document.createElement('div'); item.className = 'employment-source-row';
      const info = root.document.createElement('span');
      info.textContent = `${source.name}: ${source.status === 'ok' ? `${source.count} resultados${source.has_more ? ' · consulta el portal para ver más' : ''}` : source.status === 'external' ? 'consulta directa' : 'no disponible'}. ${source.message || ''}`;
      item.append(info);
      if (trustedPortal(source.url)) {
        const link = root.document.createElement('a'); link.href = source.url;
        link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = `Consultar ${source.name}`;
        item.append(link);
      }
      list.append(item);
    }
    $('#employment-sources-summary').hidden = !data.sources?.length;
    const select = $('#employment-source-filter'); select.replaceChildren();
    const all = root.document.createElement('option'); all.value = ''; all.textContent = 'Todas las fuentes con resultados'; select.append(all);
    const sources = new Map(data.offers.map(offer => [sourceKey(offer), offer.source || 'Chiripas']));
    for (const [key,name] of sources) {
      const option = root.document.createElement('option'); option.value = key; option.textContent = name; select.append(option);
    }
    select.value = '';
  }
  $('#employment-source-filter').addEventListener('change', () => {
    if (currentSearch) renderNationalJobs(currentSearch.data, currentSearch.latest, currentSearch.query);
  });
  const resultsDialog = $('#employment-results-dialog');
  function openJobResults() {
    if (!resultsDialog.open) resultsDialog.showModal();
    $('#employment-results-open').hidden = false;
  }
  function closeJobResults() {
    if (resultsDialog.open) resultsDialog.close();
  }
  function searchStatus(text) {
    status(text);
    $('#employment-results-status').textContent = text;
  }
  $('#employment-results-close').addEventListener('click', closeJobResults);
  $('#employment-results-open').addEventListener('click', openJobResults);
  resultsDialog.addEventListener('click', event => {
    if (event.target === resultsDialog) closeJobResults();
  });
  function publicationDate(value) {
    if (!value || !Number.isFinite(new Date(value).getTime())) return '';
    const parts = new Intl.DateTimeFormat('en-CA', {timeZone:'America/Santo_Domingo', year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(value));
    const get = name => parts.find(part => part.type === name).value;
    return `${get('year')}-${get('month')}-${get('day')}`;
  }
  function drawPublicationCalendar() {
    const calendar = $('#employment-calendar'); calendar.hidden = false;
    const offers = latestPublications ? filteredSource(latestPublications) : [];
    const dates = offers.map(offer => publicationDate(offer.published_at)).filter(Boolean).sort().reverse();
    const undated = offers.filter(offer => !publicationDate(offer.published_at)).length;
    $('#employment-calendar-undated').hidden = !undated;
    $('#employment-calendar-undated').textContent = `Ver ofertas sin fecha (${undated})`;
    calendarMonth ||= (dates[0] || publicationDate(new Date().toISOString())).slice(0,7);
    const [year, month] = calendarMonth.split('-').map(Number);
    $('#employment-calendar-month').textContent = new Intl.DateTimeFormat('es-DO',{month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(Date.UTC(year,month-1,1)));
    const grid = $('#employment-calendar-days'); grid.replaceChildren();
    const offset = (new Date(Date.UTC(year,month-1,1)).getUTCDay()+6)%7;
    for (let i=0;i<offset;i++) {const blank=root.document.createElement('span'); blank.setAttribute('aria-hidden','true'); grid.append(blank);}
    const count = new Date(Date.UTC(year,month,0)).getUTCDate();
    for (let day=1;day<=count;day++) {
      const key = `${calendarMonth}-${String(day).padStart(2,'0')}`;
      const total = dates.filter(date => date === key).length;
      const button = root.document.createElement('button'); button.type='button'; button.className='employment-calendar-day';
      button.textContent = total ? `${day} · ${total}` : String(day);
      button.setAttribute('aria-label',`${day} de ${$('#employment-calendar-month').textContent}: ${total} publicaciones disponibles`);
      button.setAttribute('aria-pressed',String(publicationDay===key));
      if (total) button.classList.add('has-publications');
      button.addEventListener('click',()=>{publicationDay=key; renderNationalJobs(latestPublications,true,'');});
      grid.append(button);
    }
  }
  function changePublicationMonth(delta) {
    const [year,month]=calendarMonth.split('-').map(Number);
    const next=new Date(Date.UTC(year,month-1+delta,1));
    calendarMonth=`${next.getUTCFullYear()}-${String(next.getUTCMonth()+1).padStart(2,'0')}`;
    drawPublicationCalendar();
  }
  function renderNationalJobs(data,latest,query) {
    const container=$('#employment-results'); container.replaceChildren();
    const available=filteredSource(data);
    const offers=latest && publicationDay ? available.filter(offer=>publicationDay === 'undated' ? !publicationDate(offer.published_at) : publicationDate(offer.published_at)===publicationDay) : available;
    if (latest) drawPublicationCalendar(); else $('#employment-calendar').hidden=true;
        for (const offer of offers) {
          const card = root.document.createElement('article');
          const title = root.document.createElement('h3'); title.textContent = offer.title;
          const company = root.document.createElement('p'); company.textContent = offer.company || 'Empresa indicada en la oferta original';
          const source = root.document.createElement('p'); source.className = 'employment-source-badge'; source.textContent = `Fuente: ${offer.source || 'Chiripas'}`;
          const date = root.document.createElement('p'); date.textContent = offer.published_at ? `Publicada: ${new Date(offer.published_at).toLocaleDateString('es-DO',{timeZone:'America/Santo_Domingo'})}` : 'Fecha no informada por la fuente';
          const description = root.document.createElement('details');
          const summary = root.document.createElement('summary'); summary.textContent = offer.description_verified === false ? 'Ver información disponible' : 'Ver descripción y requisitos';
          const text = root.document.createElement('p'); text.textContent = offer.description; description.append(summary,text);
          const link = root.document.createElement('a'); link.textContent = `${offer.source_link_search ? 'Buscar esta vacante en' : 'Ver vacante en'} ${offer.source || 'Chiripas'}`;
          if (offer.source_link_home) link.textContent = 'Abrir RD Trabaja y buscar el cargo';
          if (offer.source_key==='rdtrabaja') link.textContent='Ver este anuncio y añadir contacto';
          if (trustedPortal(offer.url)) link.href = offer.url;
          link.target = '_blank'; link.rel = 'noopener noreferrer'; link.className = 'employment-source';
          link.addEventListener('click',event=>{
            if(offer.source_key==='rdtrabaja' || !trustedPortal(offer.url)) event.preventDefault();
            openOfferContact(offer);
          });
          const adapt = root.document.createElement('button'); adapt.type = 'button'; adapt.className = 'button button-secondary'; adapt.textContent = offer.description_verified === false ? 'Añadir requisitos y adaptar CV' : 'Adaptar mi CV'; adapt.addEventListener('click',()=>useGenerator(offer));
          const contact=root.document.createElement('button'); contact.type='button'; contact.className='button button-secondary'; contact.textContent='Datos de contacto';
          contact.addEventListener('click',()=>openOfferContact(offer));
          card.append(title,company,source,date,description,link,adapt,contact); container.append(card);
        }
        if (!offers.length) {
          const empty = root.document.createElement('p');
          empty.textContent = data.sources?.filter(source=>source.status!=='external').every(source=>source.status==='unavailable')
            ? 'No se pudieron consultar las fuentes integradas. Reintenta o abre sus portales.'
            : latest ? (publicationDay === 'undated' ? 'No hay ofertas sin fecha en esta selección.' : publicationDay ? `No hay publicaciones disponibles para el ${publicationDay}.` : 'No hay vacantes disponibles en las fuentes consultadas en este momento.') : `No encontramos vacantes para «${query}». Prueba otro cargo o Ver últimas publicadas.`;
          container.append(empty);
        }
        searchStatus(`${offers.length} vacantes ${publicationDay === 'undated' && latest ? 'sin fecha' : publicationDay && latest ? 'del ' + publicationDay : latest ? 'en los listados recientes' : 'encontradas'} en RD.${data.partial ? ' Algunas fuentes no respondieron; consulta su estado arriba.' : ''} Revisa la ciudad y disponibilidad en la oferta original.`);
  }
  $('#employment-calendar-prev')?.addEventListener('click',()=>changePublicationMonth(-1));
  $('#employment-calendar-next')?.addEventListener('click',()=>changePublicationMonth(1));
  $('#employment-calendar-all')?.addEventListener('click',()=>{publicationDay=''; renderNationalJobs(latestPublications,true,'');});
  $('#employment-calendar-undated')?.addEventListener('click',()=>{publicationDay='undated'; renderNationalJobs(latestPublications,true,'');});
  let searching = false;
  async function searchJobs(latest = false) {
    if (searching) return;
    const query = latest ? '' : $('#employment-query').value.trim();
    if (!latest && !query) {searchStatus('Escribe el nombre de una vacante o pulsa Ver últimas publicadas.'); $('#employment-query').focus(); return;}
    searching = true;
    openJobResults();
    const buttons = [$('#employment-search-button'), $('#employment-latest')].filter(Boolean);
    buttons.forEach(button => {button.disabled = true;});
    const container = $('#employment-results'); container.replaceChildren();
    currentSearch = null;
    $('#employment-sources').replaceChildren();
    $('#employment-sources-summary').hidden = true;
    $('#employment-source-filter').value = '';
    $('#employment-calendar').hidden=true;
    if (latest) latestPublications=null;
    searchStatus('Consultando las fuentes autorizadas…');
    try {const data = await request('search','POST',{query,source:'rd',latest});
      if (data.national) {
        if (latest) latestPublications = data;
        currentSearch = {data, latest, query}; renderSources(data);
        renderNationalJobs(data, latest, query);
        return;
      }
      for (const offer of data.offers) {const card = root.document.createElement('article');
        const title = root.document.createElement('h3'); title.textContent = `${offer.title} · ${offer.company || ''}`;
        const info = root.document.createElement('p'); info.textContent = `${offer.mode} · ${offer.geography.distance_m === null ? 'Remoto permitido' : `${offer.geography.distance_m} m ±${offer.geography.uncertainty_m} m`} · compatibilidad ${offer.compatibility.score ?? 'sin evaluar'}`;
        const description = root.document.createElement('p'); description.textContent = offer.description;
        const link = root.document.createElement('a'); link.textContent = 'Fuente original'; link.href = offer.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        const documents = root.document.createElement('button'); documents.type = 'button'; documents.textContent = 'Adaptar con el generador de CV';
        documents.addEventListener('click', async () => {try {useGenerator(await request(`offers/${offer.id}/details`));} catch(error) {searchStatus(error.message);}});
        const prepare = root.document.createElement('button'); prepare.type = 'button'; prepare.textContent = 'Preparar candidatura';
        prepare.addEventListener('click', async () => {try {await prepareCurrentApplication('applications',{offer_id:offer.id});} catch (error) {searchStatus(error.message);}});
        const automatic = root.document.createElement('button'); automatic.type = 'button'; automatic.hidden=true; automatic.textContent = 'Simular con autorización automática';
        automatic.addEventListener('click', async () => {try {await prepareCurrentApplication('automatic-simulation',{offer_id:offer.id});} catch (error) {searchStatus(error.message);}});
        card.append(title,info,description,link,documents,prepare,automatic); container.append(card);}
      const reviewable=data.unverified.filter(offer=>offer.geography.location_eligible).length;
      searchStatus(`${data.offers.length+reviewable} ofertas compatibles con la ubicación (${reviewable} requieren revisar requisitos); ${data.excluded.length} excluidas; ${data.unverified.length-reviewable} con datos sin verificar.`);
      const reasons = {fuera_del_radio:'Fuera del radio',pais_no_autorizado:'País no autorizado',
        ubicacion_no_verificable:'Ubicación no verificable',ubicacion_ambigua:'Ubicación ambigua',
        limite_geografico_ambiguo:'Precisión insuficiente en el límite del radio',pais_remoto_no_verificado:'País de contratación remota sin verificar',
        desplazamiento_desconocido:'Desplazamientos sin verificar',modalidad_ambigua:'Modalidad sin verificar',
        oferta_vencida:'Oferta vencida',desplazamiento_no_autorizado:'Desplazamientos no autorizados'};
      for (const offer of [...data.excluded,...data.unverified]) {
        const card = root.document.createElement('article'), title = root.document.createElement('h3'), reason = root.document.createElement('p');
        title.textContent = `${offer.title} · ${offer.company || ''}`;
        reason.textContent = `Postulación bloqueada: ${reasons[offer.geography.reason] || 'Requiere revisión'}${offer.geography.distance_m === null ? '' : ` · ${offer.geography.distance_m} m ±${offer.geography.uncertainty_m} m`}`;
        const link=root.document.createElement('a'); link.href=offer.url; link.target='_blank'; link.rel='noopener noreferrer'; link.className='employment-source'; link.textContent=`Fuente original: ${offer.source}`;
        card.append(title,reason,link);
        if (offer.source==='HiringCafe' && offer.source_country && confirmed?.allowed_countries.includes(offer.source_country)) {
          const detailsButton=root.document.createElement('button'); detailsButton.type='button'; detailsButton.textContent='Ver requisitos completos';
          const full=root.document.createElement('p');
          detailsButton.addEventListener('click',async()=>{try {const detail=await request(`offers/${offer.id}/details`); full.textContent=detail.description;} catch(error) {searchStatus(error.message);}}); card.append(detailsButton,full);
          const input=root.document.createElement('input'); input.value=`${offer.company}, ${(offer.location_text || '').split(',')[0]}`; input.maxLength=250;
          const inputLabel=root.document.createElement('label'); inputLabel.textContent='Centro de trabajo público que aparece en la oferta'; inputLabel.append(input); card.append(inputLabel);
          const locate=root.document.createElement('button'); locate.type='button'; locate.textContent='Localizar centro de trabajo';
          const places=root.document.createElement('div');
          locate.addEventListener('click',async()=>{try {const result=await request(`offers/${offer.id}/places`,'POST',{place:input.value}); places.replaceChildren();
            if (!result.results.length) {searchStatus('No se encontró el centro de trabajo. Usa su dirección pública exacta.'); return;}
            result.results.forEach((place,index)=>{
              const label=root.document.createElement('label'), checked=root.document.createElement('input'); checked.type='checkbox';
              label.append(checked,` Confirmo que ${place.label} corresponde al centro de trabajo publicado.`);
              const confirm=root.document.createElement('button'); confirm.type='button'; confirm.textContent='Confirmar ubicación de la vacante';
              confirm.addEventListener('click',async()=>{try {const proof=await request(`offers/${offer.id}/location`,'POST',{index,confirmed:checked.checked});
                searchStatus(proof.geography.eligible ? `Centro confirmado: ${proof.geography.distance_m} m ±${proof.geography.uncertainty_m} m. Busca de nuevo para preparar la candidatura.` : `Candidatura bloqueada: ${proof.geography.reason} · ${proof.geography.distance_m ?? 'sin distancia'} m.`);
                if (proof.geography.eligible) $('#employment-search-form').requestSubmit();
              } catch(error) {searchStatus(error.message);}}); places.append(label,confirm);
            });
          } catch(error) {searchStatus(error.message);}}); card.append(locate,places);
        }
        if (offer.geography.location_eligible) {
          reason.textContent=`Compatible con tu ubicación${offer.geography.distance_m === null ? ' y horario según la fuente' : `: ${offer.geography.distance_m} m ±${offer.geography.uncertainty_m} m`}. Revisa los requisitos completos antes de postular.`;
          const details=root.document.createElement('details'), summary=root.document.createElement('summary'), description=root.document.createElement('p');
          summary.textContent='Ver descripción y requisitos'; description.textContent=offer.description; details.append(summary,description); card.append(details);
          const salary=root.document.createElement('p'); salary.textContent=offer.salary ? `Salario publicado: ${offer.salary.minimum}${offer.salary.maximum ? '–'+offer.salary.maximum : ''} ${offer.salary.currency || ''} (${offer.salary.period || 'periodo sin verificar'})` : 'Salario no informado por la fuente'; card.append(salary);
          const published=root.document.createElement('p'); published.textContent=offer.published_at ? `Publicada: ${new Date(offer.published_at).toLocaleDateString('es')}` : 'Fecha no publicada'; card.append(published);
          const documents=root.document.createElement('button'); documents.type='button'; documents.className='button button-secondary'; documents.textContent='Analizar y adaptar mi CV';
          documents.addEventListener('click',async()=>{try {useGenerator(await request(`offers/${offer.id}/details`));} catch(error) {searchStatus(error.message);}}); card.append(documents);
          const check=root.document.createElement('input'); check.type='checkbox'; const review=root.document.createElement('label'); review.className='employment-review';
          review.append(check,' Revisé país, horario y desplazamientos y confirmo que cumplo esos requisitos.'); card.append(review);
          const prepare=root.document.createElement('button'); prepare.type='button'; prepare.className='button button-primary'; prepare.textContent='Preparar candidatura supervisada';
          prepare.addEventListener('click',async()=>{if (!check.checked) {searchStatus('Revisa los desplazamientos antes de preparar la candidatura.'); return;}
            try {await prepareCurrentApplication('applications',{offer_id:offer.id,reviewed_no_travel:true}); searchStatus('Candidatura preparada para tu aprobación.');}
            catch(error) {searchStatus(error.message);}}); card.append(prepare);
        }
        container.append(card);
      }
    } catch (error) {searchStatus(error.message);}
    finally {searching = false; buttons.forEach(button => {button.disabled = false;});}
  }
  $('#employment-search-form').addEventListener('submit', event => {event.preventDefault(); searchJobs();});
  $('#employment-latest')?.addEventListener('click', () => {publicationDay=''; calendarMonth=''; searchJobs(true);});
  $('#employment-revoke').addEventListener('click', async () => {
    try {await request('authorization','DELETE'); $('#employment-authorization-status').textContent = 'Sin autorización automática.'; status('Autorización revocada.');} catch (error) {status(error.message);}
  });
  $('#employment-authorization-form').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget, payload = {};
    const value = name => form.elements.namedItem(name);
    for (const name of ['titles','countries','modes','sources','excluded_companies']) payload[name] = value(name).value.split(',').map(s => s.trim()).filter(Boolean);
    for (const name of ['minimum_score','minimum_salary','daily_limit','start_hour','end_hour']) payload[name] = Number(value(name).value);
    for (const name of ['currency','expires_at']) payload[name] = value(name).value;
    for (const name of ['confirmed','use_cover_letter']) payload[name] = value(name).checked;
    try {const scope = await request('authorization','PUT',payload);
      $('#employment-authorization-status').textContent = `Simulación autorizada hasta ${scope.expires_at}; máximo ${scope.daily_limit} por día, horario de Santo Domingo.`;
      status('Autorización de simulación guardada. Puedes revocarla inmediatamente.');
    } catch (error) {status(error.message);}
  });
})(typeof window !== 'undefined' ? window : globalThis);
