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

## Cierre adicional solicitado — 20-oct-2026

Se ejecutó compatibilidad local con el código histórico real de `background_jobs.py` del commit `6232e11`, conservado en `tests/fixtures/background_jobs_6232e11.txt`. `tests/test_phase2_mixed_versions.py` comprueba:

1. Worker anterior produce un fallo de revisión del banco y la API actual añade la categoría de recuperación y una correlación estable, sin modificar ni reejecutar la tarea.
2. Worker actual produce un fallo de autorización y la API anterior conserva los campos que lee el cliente antiguo.
3. Ambas APIs leen un resultado completado sin volver a despacharlo.

Resultado final: 363 JS + 600 Python = **963 aprobadas**, cero fallos/errores/omitidas, cobertura **83,51 %**, red bloqueada. Evidencia: `tmp/phase2-mixed-verification/`. Es una prueba de interoperabilidad del módulo de tareas con dependencias actuales simuladas; no certifica imágenes completas de Functions ni revisiones desplegadas.

Se revisaron únicamente resúmenes locales preexistentes: `tmp/server-audit-rejection-codes.json` contiene seis coincidencias de `job_account_maintenance` en una muestra de 300 líneas; `tmp/server-audit-logs-summary.json` documenta el alcance temporal de esa muestra. Apoya la existencia del rechazo administrativo, pero no identifica el intento de la fotografía, su usuario, HTTP o correlación. No hay evidencia suficiente para atribuir el error genérico de Drive fotografiado a una causa concreta. No se inventa ni se da por recuperado ese intento. Su identificación exige una captura sanitizada del intento o una consulta humana de solo lectura como la descrita arriba; no se consultó producción en este cierre.

Para revisar la nueva evidencia local:

```powershell
Get-Content tmp/phase2-mixed-verification/release-summary.json
Get-Content tmp/phase2-mixed-verification/python-summary.json
Get-Content tmp/server-audit-rejection-codes.json
Get-Content tmp/server-audit-logs-summary.json
```
