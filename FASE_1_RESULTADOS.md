# Fase 1 — S01 y S02

Estado: corregido en local, pendiente de despliegue y verificación. No se ejecutaron operaciones contra producción. No se avanzó a Fase 2 ni se modificaron concurrencia o maxInstances.

## Hallazgos confirmados y correcciones

- S01: la eliminación podía dejar mantenimiento sin resultado terminal. Se registra fallo confirmado con código, etapa, correlationId y fecha. La recuperación validada conserva recibo y permite repetir la confirmación sin volver a modificar la cuenta. Commit local `be2d0e7` (`fix(S01)`).
- S02: save y prepare no compartían la exclusión de admisión y administración. Se incorpora reserva común por cuenta con CAS, titular y TTL; comprobación de mantenimiento antes de cada efecto protegido; exclusión de carreras y conservación de resultados inciertos. Segundo commit local `fix(S02)`.

Archivos de implementación: `account_writes.py`, `admin_user_actions.py`, `job_runtime.py`, `background_jobs.py`, `user_accounts.py`, `onboarding.py`, `app.py`, `drive_bank.py`, `telegram_accounts.py`, `telegram_bot.py`, `web_notifications.py`. S01 también incorpora la recuperación administrativa preparada en `admin_usage.py` y `static/admin-architecture.js`. Procedimiento: `DIAGNOSTICO_BLOQUEO_ADMINISTRATIVO.md`.

## Regresiones y verificación

Se reprodujeron antes del cambio las escrituras de onboarding/preparación bajo mantenimiento, las carreras con eliminación y la falta de evidencia terminal/repetición idempotente. Las regresiones pasan con la corrección.

Pruebas nuevas: `test_phase1_recovery.py` (3), `test_phase1_write_barrier.py` (5), `test_phase1_account_races.py` (3), `test_account_writes.py` (16) y `offline-harness.test.cjs` (1). Se adaptaron dos fixtures existentes al nuevo contrato de reserva/conflicto y el test HTTP del monitor usa solicitudes en memoria. No se prueba producción.

Resultado de la batería completa: **359 JS + 588 Python = 947 aprobadas**, sin omisiones ni fallos. Línea base: 358 + 561 = 919. Incremento: 28. Cobertura Python: **83,29 %**, frente a 82,96 % (+0,33 puntos). El ejecutor bloquea red en ambos runtimes y exige cobertura mínima 82,96 %.

Comando reproducible desde el repositorio:

```powershell
.\venv\Scripts\python.exe scripts/verify_release.py --output tmp/phase1-final-verification
git diff --check
```

Evidencia local: `tmp/phase1-final-verification/release-summary.json`, `python-summary.json`, `node-tests.txt`, `python-tests.txt`, `coverage.txt` y `coverage.json`. Es evidencia de fixtures locales, no de servicios desplegados.

## Riesgos y siguientes pasos humanos

La lista real de bloqueos antiguos no se consultó: usar únicamente las consultas de lectura y la selección de campos del diagnóstico. No imprimir documentos completos de planes, claves, tokens ni datos de CV. Revisar identidad, plan original, etapa y resultado externo; una marca antigua o resultado incierto no se desbloquean automáticamente.

Persistencia indisponible, cierre abrupto durante un efecto y coexistencia con versiones anteriores siguen exigiendo evidencia/manualidad. La reserva incierta conserva exclusión aunque venza su plazo. La excepción de cierre terminal solo registra evidencia, no autoriza más efectos. No se restauran credenciales revocadas ni se reinician cuotas.

IAM efectivo, cuota Vertex, backlog/edad de Tasks, lifecycle/expiración física, CI y costos siguen pendientes. El diagnóstico contiene comandos humanos exactos de inventario y describe los marcadores que deben resolverse sin inferir valores. No se ensayaron servicios externos.

Publicación pendiente de autorización futura; no ejecutar despliegues durante esta fase. Revisar diferencias y commits locales, conservar evidencia y confirmar Fase 2 antes de continuar. El cotejo de Hosting/API y la reversión corresponden a Fase 5.
