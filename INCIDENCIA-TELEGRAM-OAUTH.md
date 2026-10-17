# Incidencia Telegram / OAuth — 17 de octubre de 2026

## Evidencia

Las capturas del usuario muestran Google bloqueando la autorización con `400: origin_mismatch` y el panel funcional mostrando Telegram operativo.

La revisión de solo lectura de Google Cloud Auth Platform del proyecto confirmó que el único cliente web listado tiene los orígenes `https://cv-a-la-medida-jhonn.web.app` y `https://cv-a-la-medida-jhonn.firebaseapp.com` (además de localhost), pero falta `https://cvalamedida.web.app`. No se leyeron ni cambiaron secretos. No se guardaron modificaciones en Google Cloud.

Según la [documentación de Google para errores OAuth](https://developers.google.com/identity/oauth2/web/guides/error), el modo popup requiere que los dominios que inician el flujo estén en los orígenes JavaScript autorizados. El código que falla ocurre en Google antes de que la app obtenga un código de autorización; no demuestra un fallo de Firebase Authentication ni de la Bot API de Telegram.

## Brechas corregidas en la aplicación

1. El flujo `static/telegram.js` no enviaba al motor de diagnóstico la autorización fallida. Ahora notifica inicio pendiente, códigos permitidos de rechazo, cierre y timeout con componente Telegram y operación estable entre reintentos.
2. Las advertencias del navegador tenían `confirmed:false`, y el panel las descartaba. Ahora se muestran amarillas, con evidencia y causa pendiente de verificación. No se inventa origin_mismatch cuando Google sólo informa cierre de popup.
3. Un HTTP 200 o una verificación de identidad no demuestra el flujo Telegram completo. El panel no presenta esos requisitos previos como éxito integral.
4. Las rutas de vinculación/autorización Telegram ahora están inventariadas. Confirmar el acceso y persistencia reales de Drive emite éxito de la etapa de autorización en la misma operación, permitiendo resolver la advertencia.
5. Cada intento tiene su CodeClient y callbacks asociados. Las respuestas tardías no pueden completar ni cancelar intentos posteriores. El timeout de espera a Google se detiene antes del procesamiento de backend.
6. La telemetría no captura códigos OAuth de autorización, tokens, descripciones libres, cuentas ni CV; sólo una lista fija de códigos y metadatos permitidos. Si falla, no sustituye el error original.

## Pruebas

Verificador existente: `venv/Scripts/python.exe scripts/verify_release.py --output tmp/telegram-oauth-diagnostics-final`.

- Python: 430/430 aprobadas.
- JavaScript: 215/215 aprobadas.
- Cobertura Python: 81.56%, supera el mínimo existente 80%.
- Mocks y red bloqueada en backend; sin mensajes Telegram ni cambios de usuarios/datos de producción.
- Revisión especializada: sin bloqueantes tras corregir callbacks tardíos y distinguir pendiente de fallo.

## Configuración OAuth aplicada con autorización

Tras la instrucción explícita del usuario, se guardó únicamente `https://cvalamedida.web.app` como origen adicional del cliente web existente. Google confirmó el guardado y el formulario reabierto conserva ese origen. No se creó otro cliente ni se cambiaron secretos, scopes o redirecciones. La sincronización real del usuario sigue pendiente de un nuevo intento.

## Despliegue confirmado

Corrección publicada en ambas funciones y ambos sitios de Hosting. Firebase CLI confirmó `Deploy complete`, código 0. Build `20261017T044052Z-82ece164`.

Comprobación posterior en ambos sitios: telegram.js y admin-architecture.js coinciden byte a byte con la versión probada; salud HTTP 200; API administrativa sin sesión HTTP 401. Evidencia en `tmp/telegram-diagnostics-smoke.json`.

La configuración OAuth se guardó después de este despliegue, con la autorización posterior del usuario. Evidencia local: `tmp/origen-oauth-guardado.png`.

