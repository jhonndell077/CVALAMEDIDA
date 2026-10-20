# Cierre global de sesiones de la aplicación — 20-oct-2026

Acción solicitada explícitamente por el propietario: invalidar las sesiones anteriores para que cada usuario vuelva a entrar con las mejoras publicadas.

## Alcance y mecanismo

`session_policy.py` fija `REAUTHENTICATE_AFTER=1792497230`: **20-oct-2026 07:53:50, Santo Domingo** (11:53:50 UTC). Todas las identidades Firebase verificadas cuyo `auth_time` sea anterior, ausente o inválido reciben HTTP 401, código `session_reauthentication_required`, antes de cargar la cuenta o acceder a Drive/Storage. Un token renovado conserva el auth_time original y no elude el corte. Se mantiene `check_revoked=True`.

La fecha permanece fija durante despliegues normales. No se deriva del buildId ni se adelanta automáticamente. Inicios de sesión realizados desde esa fecha siguen siendo válidos. Modificar el corte es una nueva acción administrativa, no un mantenimiento rutinario.

El cliente recibe el corte desde `/api/health`. Antes de restaurar una sesión comprueba sus claims mediante el SDK de Firebase, cierra las antiguas y limpia la vista privada con el mismo procedimiento de salida existente. Una respuesta tardía de otra identidad no cierra la cuenta actual.

El cierre es de **CV a la Medida**: no cierra Gmail/Google en el navegador, no revoca permisos OAuth ni desconecta Telegram. No elimina cuentas, bancos, archivos, recibos, historial, planes, cuotas o marcas administrativas. No requiere enumerar usuarios ni leer almacenes de autenticación. Los procesos ya en ejecución no se purgan como parte de este cierre.

Una pestaña antigua o un equipo desconectado no puede limpiarse remotamente de forma instantánea: el servidor rechaza su siguiente acceso autenticado y, al cargar la versión nueva, el cliente cierra la sesión anterior. Esto no equivale a borrar datos locales arbitrariamente ni a revocar globalmente las sesiones de otros productos de Google.

## Verificación previa

`scripts/verify_release.py`, con red bloqueada: **371 JavaScript + 606 Python = 977 aprobadas**, cobertura **83,53 %**, cero fallos/errores/omitidas. Evidencia: `tmp/global-session-close-verification/`.

Regresiones en `tests/test_session_policy.py` y `tests/session-policy.test.cjs`: múltiples cuentas, tokens renovados tras el corte, claims ausentes/inválidos, nuevo acceso permitido, limpieza de interfaz privada, ausencia de bucle de cierre y aislamiento ante respuestas tardías de otra identidad.

El resultado de publicación y las comprobaciones reales se registran en `tmp/global-session-close-live/`.
