# Corrección del diagnóstico HTTP 429

La captura aportada registra una respuesta HTTP 429 en http-backend, correlación `e578729bc54b4b79a759d6465479950f`. Confirma una solicitud limitada, no una caída de Cloud Functions ni fallos de Firebase Authentication o del generador PDF. El evento original ya no estaba en el historial administrativo disponible al revisar; su retención es una hora y 400 eventos. No se pudo recuperar el endpoint ni determinar cuál límite produjo aquella respuesta.

El código contiene límites de concurrencia (diez trabajos pendientes), cuotas por período y límite de señales del navegador. No hay evidencia suficiente para atribuir este caso a uno de ellos; no se desactivaron ni ampliaron límites.

## Cambios

- Se eliminó la propagación de errores entre componentes por compartir operación. La correlación enlaza evidencia, pero no demuestra causalidad.
- HTTP 429 conserva código, confirmación, correlación y respuesta original, y se clasifica como advertencia de solicitud limitada. También se interpretan correctamente eventos anteriores guardados como error.
- Alertas e historial exponen endpoint y evidencia para investigar futuros incidentes. No se declara éxito al retirar una atribución incorrecta: sin evidencia propia corresponde No verificado.
- Los enlaces administrativos al módulo apuntan a `https://cvalamedida.web.app/admin/arquitectura`.
- Google Cloud confirmó el guardado del origen JavaScript `https://cvalamedida.web.app` en el cliente OAuth existente, autorizado por el usuario. Se volvió a abrir el formulario y se comprobó su persistencia. No se cambiaron secretos, scopes ni redirecciones. Evidencia local: `tmp/origen-oauth-guardado.png`.

## Validación y límites

Se utiliza el verificador existente `scripts/verify_release.py`, con fixtures y red bloqueada en backend; revisión especializada sin bloqueantes. Los resultados definitivos se guardan en `tmp/diagnostics-429-final`. No se envían mensajes Telegram ni se modifican datos de usuarios. La sincronización real del usuario requiere un nuevo intento; no se acredita mediante estas pruebas locales.

Sin nuevas dependencias ni servicios. El volumen y la retención de telemetría permanecen iguales; siguen aplicando los costos existentes de Functions y Cloud Storage.
