# Fase 2 — S05, S06, S07

Estado: corregido en local, pendiente de despliegue y verificación. Fecha: 20-oct-2026.
No se ejecutaron consultas ni cambios contra producción ni llamadas reales a proveedores.

## Cambios

- S06: `error_contract.py`, `drive_error_details.py`, `user_accounts.py`, `onboarding.py`, `drive_bank.py`, `app.py`. Contrato aditivo con code, stage, operationId, correlationId, retryable, safeNextAction, externalOutcome y buildId. Traductor común para GET, POST, PATCH y subida. Solo una autorización confirmada vencida/revocada invalida el permiso; 403/404 ambiguos conservan la incertidumbre sobre acceso o existencia.
- S07: `background_jobs.py`, `job_runtime.py`, `static/background.js`. Consulta de tarea conserva errorCode, categoría de recuperación, etapa y correlación; los errores duraderos usan mensajes seguros. Los resultados externos desconocidos requieren revisión antes de repetir.
- S05: `static/drive.js`, `static/app.js`, `static/onboarding.js`. Mensajes de un catálogo seguro, HTTP/correlación conservados ante HTML/cuerpo vacío/JSON incompleto, distinción entre comprobar acceso y preparar carpetas, borradores conservados ante account_write_busy con indicación de reintento.

## Pruebas y evidencia

Pruebas nuevas: `tests/test_phase2_drive_contract.py` (5 pruebas, matriz de métodos y motivos), `tests/test_phase2_task_contract.py` (4), `tests/phase2-client-errors.test.cjs` (3), y una prueba de presentación de error de tarea en `tests/background-completion.test.cjs`. Se adaptaron las expectativas antiguas de `tests/test_session_repair_backend.py` y `tests/drive_accounts.test.js` para aceptar metadatos aditivos y rechazar texto sin clasificar.

Ejecución final: `scripts/verify_release.py`, red bloqueada, copia desechable, 363 JS + 597 Python = 960 aprobadas; cero fallos, errores u omitidas. Cobertura de Python con ramas: 83,51 %, frente al mínimo de 82,96 % (+0,55 puntos). Frente a la línea base solicitada de 919 pruebas: +41. Frente al cierre real de Fase 1 de 947: +13.

Evidencia local: `tmp/phase2-final-verification/release-summary.json`, `python-summary.json`, `coverage.txt`, `node-tests.txt`, `python-tests.txt`. La revisión delegada no pudo completarse por límite de uso del agente; se completó revisión local y comprobación de diff.

## Riesgos y evidencia pendiente

- No se acredita el comportamiento desplegado ni la causa del error fotografiado. Faltan HTTP, code y correlationId del intento afectado.
- En un despliegue parcial, un worker antiguo seguirá produciendo menos metadatos; el servidor nuevo normaliza fallos antiguos y conserva los campos anteriores. No se han ensayado binarios desplegados de versiones mixtas.
- IAM, cuotas Vertex, backlog de Cloud Tasks, lifecycle, CI y costos continúan pendientes de evidencia y fuera de esta fase.
- No se tocó la reserva de escrituras, las marcas administrativas ni las cuotas.

## Pasos humanos de solo lectura (no ejecutados)

Desde la raíz del repositorio, revisar commits y evidencia local:

```powershell
git log -3 --oneline
git diff 6232e11..HEAD --stat
Get-Content tmp/phase2-final-verification/release-summary.json
Get-Content tmp/phase2-final-verification/python-summary.json
Get-Content tmp/phase2-final-verification/coverage.txt
```

Para investigar el intento fotografiado, obtener del panel Red del dispositivo únicamente estado HTTP, code, stage, operationId, correlationId y buildId. No exportar encabezados Authorization, tokens, cuerpos de CV ni un HAR sin sanitizar.

Consulta de registros HTTP, solo por el humano, con proyección que evita contenido de solicitudes:

```powershell
gcloud logging read 'resource.type="cloud_run_revision" AND httpRequest.status>=400' --project=cv-a-la-medida-jhonn --freshness=1h --limit=100 --format='table(timestamp,resource.labels.service_name,httpRequest.status,trace)'
```

Si el intento ocurrió fuera de esa ventana, ajustar el período a su fecha real. Una ausencia de filas no demuestra recuperación. Para la revisión de bloqueos antiguos y demás consultas de infraestructura, seguir los comandos documentados en `DIAGNOSTICO_BLOQUEO_ADMINISTRATIVO.md`, sin borrar marcas por antigüedad.

No avanzar a Fase 3 ni publicar hasta confirmación del usuario.
