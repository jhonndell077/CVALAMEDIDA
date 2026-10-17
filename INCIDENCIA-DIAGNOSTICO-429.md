# Corrección del diagnóstico HTTP 429

La captura aportada registra una respuesta HTTP 429 en http-backend, correlación `e578729bc54b4b79a759d6465479950f`. Confirma una solicitud limitada, no una caída de Cloud Functions ni fallos de Firebase Authentication o del generador PDF. Aunque la vista inicial no mostraba eventos, tras recargar la versión publicada se recuperó el historial compartido: endpoint `/api/background/jobs`, fecha `2026-10-17T12:35:09.303849+00:00`, operación `ad247d92-1f60-407f-a48a-c5d5efb88d2d`. La misma solicitud tiene identidad Firebase validada y lecturas Storage completadas. No hay evidencia de ejecución fallida del generador PDF.

Ese endpoint puede responder 429 al admitir tareas por concurrencia (diez trabajos pendientes) o cuotas por período. La telemetría histórica no conserva el motivo específico; no hay evidencia suficiente para elegir entre ellos. El límite de señales del navegador corresponde a otro endpoint y no explica esta solicitud. No se desactivaron ni ampliaron límites.

## Cambios

- Se eliminó la propagación de errores entre componentes por compartir operación. La correlación enlaza evidencia, pero no demuestra causalidad.
- HTTP 429 conserva código, confirmación, correlación y respuesta original, y se clasifica como advertencia de solicitud limitada. También se interpretan correctamente eventos anteriores guardados como error.
- Alertas e historial exponen endpoint y evidencia para investigar futuros incidentes. No se declara éxito al retirar una atribución incorrecta: sin evidencia propia corresponde No verificado.
- Los enlaces administrativos al módulo apuntan a `https://cvalamedida.web.app/admin/arquitectura`.
- Google Cloud confirmó el guardado del origen JavaScript `https://cvalamedida.web.app` en el cliente OAuth existente, autorizado por el usuario. Se volvió a abrir el formulario y se comprobó su persistencia. No se cambiaron secretos, scopes ni redirecciones. Evidencia local: `tmp/origen-oauth-guardado.png`.

## Validación y límites

Verificador existente `scripts/verify_release.py`: 431/431 pruebas Python y 219/219 JavaScript aprobadas; cobertura Python 81,56 %. Fixtures y red bloqueada en backend; revisión especializada sin bloqueantes. Resultados en `tmp/diagnostics-429-final`. No se envían mensajes Telegram ni se modifican datos de usuarios. La sincronización real del usuario requiere un nuevo intento; no se acredita mediante estas pruebas locales.

Sin nuevas dependencias ni servicios. El volumen y la retención de telemetría permanecen iguales; siguen aplicando los costos existentes de Functions y Cloud Storage.

## Publicación

Firebase confirmó la actualización de api y telegram_worker y ambos sitios Hosting. Build `20261017T124359Z-156c6cbf`. Comprobación posterior: archivos JS y enlaces HTML idénticos a los probados, salud HTTP 200 y administración sin sesión HTTP 401 en ambos sitios. Evidencia: `tmp/diagnostics-429-smoke.json`. El módulo autenticado publicado muestra el incidente original en amarillo y Google operativo con su propia evidencia.
