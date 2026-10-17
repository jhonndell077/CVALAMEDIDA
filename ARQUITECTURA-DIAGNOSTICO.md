# Arquitectura y Diagnóstico Inteligente — informe de entrega

Proyecto: CV a la Medida. Rama: `feat/arquitectura-diagnostico`.

## Resultado

Módulo `/admin/arquitectura`, enlazado desde Conexiones y el mapa funcional existente. Conserva la jerarquía Usuario → Google Authentication → Banco central → Drive / Telegram / PDF → Diagnóstico y añade el diagrama técnico conectado, selección bidireccional, detalles por etapa, alertas agrupadas, historial filtrable, zoom y desplazamiento.

Se completaron los pendientes de la primera entrega: historial compartido en el bucket privado existente; IDs de operación propagados a trabajos y reintentos; señales OAuth del navegador; autenticación básica independiente de conceder Drive/Gmail; observación de etapas de Firebase Auth, PDF, Drive, Vertex, Storage, Tasks, Telegram y Gmail. Los servicios sin evidencia permanecen sin verificar. No se importan retrospectivamente logs de Google Cloud.

DESPLIEGUE_PENDIENTE

## Arquitectura auditada y reutilización

- Firebase Hosting sirve dos sitios (`cvalamedida` y `cv-a-la-medida-jhonn`) y dirige API/Telegram a Cloud Functions.
- `main.api` y `main.telegram_worker` ejecutan Flask, región us-central1, runtime desplegado Python 3.13.
- Firebase Admin verifica identidad y revocación; las rutas administrativas exigen propietario antes de cargar cuentas o Drive.
- El banco profesional está en Google Drive, con ETag, escritura condicional y confirmación posterior. No se encontró Firestore.
- ReportLab genera PDF. El archivo utiliza Drive o Cloud Storage según proveedor configurado. Generar no equivale a guardar.
- Vertex AI realiza análisis; Telegram usa webhook, Cloud Tasks, JobStore Cloud Storage y Secret Manager. Gmail y Web Push ya existían.
- Telegram ya tenía idempotencia por update_id y reservas/concesiones duraderas. Se conservaron estos mecanismos.

No se encontró `Arquitectura diagrama deseado..pdf` en las búsquedas del espacio de trabajo, Desktop, Downloads y Documents. El diseño sigue la estructura textual entregada por el usuario; no se afirma haber comparado las dos páginas originales.

## Evidencia, correlación y retención

Los eventos guardan sólo IDs, componente y servicio permitidos, ruta registrada sin parámetros, instante, duración, etapa, resultado, código permitido y confirmación. No guardan usuarios, correos, CV, cuerpos, querystrings, tokens, URL del bot, contraseñas ni textos de errores.

`X-Correlation-ID` identifica la solicitud. `X-CV-Operation-ID` acepta UUID/32hex y se conserva en trabajos. Telegram usa operación SHA256 derivada del update y correlación UUID. La restauración sucede después de los controles de identidad existentes. Un ContextVar conserva el lote entre contextos Flask anidados de exportación.

El historial compartido utiliza el bucket privado existente `cv-a-la-medida-jhonn-telegram-private`, objeto `diagnostics/architecture-v1.json`. No se crearon buckets ni se alteró IAM. Se activa en Cloud Functions mediante K_SERVICE/FUNCTION_TARGET; las pruebas locales no acceden a cloud.

Retención lógica: una hora, máximo 400 eventos compartidos. Lecturas filtran vencidos; el próximo guardado reemplaza físicamente los registros vencidos. No se añadió borrado programado ni lifecycle al bucket. Escritura consolidada por solicitud, generaciones condicionales, reintentos acotados y timeout por operación. Si Storage falla, la aplicación conserva su resultado normal y el panel muestra explícitamente que sólo dispone de evidencia local. Si se agotan conflictos puede faltar un lote del historial compartido; su ausencia no es prueba de éxito.

Un HTTP correcto del backend sólo acredita su etapa. PDF, subida y lectura posterior tienen resultados separados; un fallo de Drive no convierte la generación exitosa en una generación fallida. La tarjeta funcional puede señalar que el flujo completo quedó afectado y el detalle distingue etapas. Resolver una incidencia exige éxito posterior de la misma operación, servicio y etapa.

Los reportes OAuth sólo aceptan códigos fijos, sesión Firebase y orígenes permitidos, con límite por usuario. Son señales **no confirmadas por el proveedor**, no pruebas de caída de Drive. Autenticarse en Google ya no requiere conceder Drive/Gmail; estos permisos se solicitan en la acción de conexión.

## Interfaz y simulaciones

Hay cuatro escenarios locales explícitos: PDF/Drive 403, OAuth, Telegram y sincronización/conflicto. No se envían al backend ni alteran producción. Se verificaron en navegador la selección y la simulación PDF, y el principal en viewport móvil 390×844. Se corrigió su centrado inicial. Esto no equivale a probar todos los dispositivos físicos ni todos los gestos.

La actualización automática es opcional cada 60 segundos y sólo consulta evidencia existente con sesión, pestaña visible y modo real; se pausa en demos y al salir. La vista respeta movimiento reducido y ofrece foco visible.

## Sincronización e idempotencia

Cerrar Datos comparte el guardado manual pendiente, guarda los cambios y sincroniza sólo lo necesario. No cierra ni anuncia confirmación si quedan pendientes, aparece un conflicto o falla el guardado. Conserva datos para recuperar. Los cambios de cuenta y época de sesión invalidan solicitudes/respuestas anteriores, incluso durante la renovación del token.

Experiencias manuales con IDs de operación distintos no se fusionan sólo por título/empleador, incluso sin fechas. Reintentar el mismo ID sigue siendo idempotente; contenido incompatible para el mismo ID se rechaza. La deduplicación documental existente se conserva. No se migraron ni eliminaron registros.

## Verificación final

Comando existente: `venv/Scripts/python.exe scripts/verify_release.py --output tmp/architecture-final-deploy`.

| Control | Resultado |
| --- | --- |
| Python | 429/429 aprobadas, sin fallos, errores u omisiones |
| JavaScript | 203/203 aprobadas, sin fallos u omisiones |
| Cobertura Python con ramas | 81.60%, supera mínimo existente 80% |
| Sintaxis y locks | Aprobados por el verificador del proyecto |
| pip-audit del lock runtime | Sin vulnerabilidades conocidas; no se instalaron dependencias |
| Revisión de seguridad | Sin bloqueantes en acceso, sanitización, persistencia y restauración de trazas |
| Diff | git diff --check aprobado |

El backend se prueba en copia temporal con sockets y descubrimiento de credenciales bloqueados. Mocks/fixtures cubren acceso no autorizado, sesión sin Drive, OAuth, Drive/PDF, Telegram, Tasks, almacenamiento compartido, reintentos, conflictos, cambio de cuenta, fallos de telemetría y recuperación. La suite local usa Python 3.14.2; Firebase construye el runtime Python 3.13 del proyecto.

Evidencia: `tmp/architecture-final-deploy/{python-summary.json,python-tests.txt,node-tests.txt,coverage.json,release-summary.json}` y `tmp/functional-map-test-evidence.json` vinculada a la fuente. Los archivos temporales se excluyen de publicación. No existen scripts TypeScript/build/lint específicos: se usaron los controles de sintaxis y verificación disponibles.

## Costos y límites operativos

No se agregaron dependencias ni servicios. La nueva persistencia sí añade operaciones Storage: por lote normal, reload, download si existe y upload; por consulta administrativa, reload y download. Conflictos pueden repetir operaciones hasta el límite definido. Functions añade uso de CPU/memoria/tiempo; la actualización opcional añade hasta una consulta por minuto mientras sea elegible. No se añaden consultas Firestore, sondas Vertex ni mensajes Telegram. Los costos de los flujos normales continúan.

No se verificaron configuraciones completas OAuth/Google Cloud mediante consola: los dominios solicitados figuran en listas locales permitidas, pero no se concluye compatibilidad ni incompatibilidad de orígenes, redirect URIs, cliente, scopes o IAM por esa sola presencia. Se confirmó mediante CLI la existencia de funciones/runtime y sitios de Hosting. La comprobación de salud y acceso posterior al deploy no sustituye un flujo real autenticado de PDF, Drive o Telegram. No se ejecutaron esos flujos sobre usuarios/datos reales.

El módulo no repara, borra usuarios/documentos, cambia credenciales/reglas ni reinicia servicios. La autorización de despliegue fue explícita: “Termina y Desplegalo”. No incluye un push a GitHub; el despliegue se realiza desde la rama revisada con Firebase CLI, sin ejecutar el script que obliga main y push automático.

## Archivos cambiados

- `ARQUITECTURA-DIAGNOSTICO.md`
- `analysis_jobs.py`
- `app.py`
- `architecture_diagnostics.py`
- `background_jobs.py`
- `client_diagnostics.py`
- `diagnostic_stages.py`
- `diagnostic_store.py`
- `distributed_diagnostics.py`
- `drive_bank.py`
- `firebase.json`
- `job_runtime.py`
- `profile_records.py`
- `static/admin-architecture.css`
- `static/admin-architecture.html`
- `static/admin-architecture.js`
- `static/admin-connections.html`
- `static/admin-functionality.html`
- `static/app.js`
- `static/background.js`
- `static/data-panel.js`
- `static/drive-auth.js`
- `static/drive.js`
- `telegram_bot.py`
- `tests/admin-architecture.test.cjs`
- `tests/audit-frontend-regressions.test.cjs`
- `tests/consolidated-close.test.cjs`
- `tests/frontend-trace.test.cjs`
- `tests/test_architecture_diagnostics.py`
- `tests/test_client_diagnostics.py`
- `tests/test_diagnostic_stages.py`
- `tests/test_diagnostic_store.py`
- `tests/test_distributed_diagnostics.py`
- `tests/test_profile_records.py`
