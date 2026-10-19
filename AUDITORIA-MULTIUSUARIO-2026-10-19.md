# Diagnóstico final: usuarios simultáneos y dispositivos

**Actualización posterior:** H09, H10 y H11 ya se corrigieron localmente. Este documento conserva la evidencia de la revisión anterior. El estado actual y las pruebas ampliadas están en [AUDITORIA-EXHAUSTIVA-2026-10-19.md](./AUDITORIA-EXHAUSTIVA-2026-10-19.md).

Fecha: 19 de octubre de 2026. Alcance: código y servidor locales, cuentas ficticias, proveedores simulados y navegador Chromium. Revisión de solo lectura sobre la aplicación: no se corrigieron los problemas nuevos ni se publicó nada.

**Dictamen de la revisión anterior, antes de corregir:** se reprodujeron tres defectos pendientes, pese a que la suite existente pasaba.

## Hallazgos confirmados

### H09 — Alta: se descuenta un CV cuando la solicitud falla

- Reproducción: cuenta ficticia sin consumos; `POST /api/draft` con `{}` a la ruta real mediante cliente Flask aislado.
- Resultado: HTTP 400 y consumo diario igual a 1. No se produjo ningún CV.
- Causa: `background_jobs.py:27` reserva cupo antes de validar la solicitud. `job_runtime.py:123` registra el consumo; el cierre de la petición libera la concurrencia, pero no revierte la cuota.
- Impacto: un error de validación puede volver a agotar el plan sin una creación exitosa. Es un caso residual relacionado con los hallazgos originales 4 y 5.
- Corrección propuesta: separar la reserva temporal del consumo definitivo; confirmar el cargo al generar el resultado y liberar la reserva al fallar antes de producirlo. Mantener idempotencia para reintentos y solicitudes concurrentes.
- Evidencia: `tmp/revision-final-2026-10-19/multiusuario.json`, campo `invalid_draft`.

### H10 — Alta: dos primeros ingresos simultáneos duplican carpetas

- Reproducción: dos dispositivos simulados llaman a `user_accounts.prepare` para una misma cuenta nueva. Ambos consultan Drive antes de que exista la primera carpeta. Drive y el almacenamiento son simulaciones en memoria; no se crearon carpetas reales.
- Resultado: dos carpetas «Banco de Datos», dos «CV Generados» y dos de cada sección. Una preparación termina correctamente y la otra falla con `PreconditionFailed`.
- Causa: el control de versión se aplica al guardar el registro de la cuenta, después de crear las carpetas externas (`user_accounts.py:133` y `:156`). No evita que ambas preparaciones realicen esos efectos.
- Impacto: sincronización inicial fallida o ambigua. Una consulta posterior por nombre puede encontrar varias carpetas y exigir selección manual.
- Corrección propuesta: reservar la preparación por UID antes de crear carpetas, persistir sus avances y permitir reanudarla idempotentemente desde el segundo dispositivo.
- Evidencia: `tmp/revision-final-2026-10-19/carrera-primer-ingreso.json`.

### H11 — Media: volver a Básico puede omitir el aviso de cambio de plan

- Reproducción: Básico → Pro → Básico, cerrando cada aviso, en una misma sesión simulada.
- Resultado: bienvenida Básico presente; aviso Pro presente; aviso de regreso a Básico ausente.
- Causa: la clave de deduplicación utiliza la asignación o la cadena `basic` y los límites (`static/subscription-notices.js:11`). Al volver al Básico anterior, la clave ya está marcada como vista.
- Impacto: el usuario puede no enterarse de que sus límites volvieron a reducirse. El hallazgo original 7 no está cerrado para todas las transiciones.
- Corrección propuesta: versionar todos los cambios de plan en el servidor, incluido el retorno al plan predeterminado, o detectar la transición confirmada aunque el plan de destino se haya visto antes.
- Evidencia: `tmp/revision-final-2026-10-19/avisos-plan.json`.

## Simulación de varios equipos

Se ejecutaron 36 sesiones independientes simuladas: 12 cuentas ficticias y 3 clientes por cuenta. No son equipos físicos ni sesiones reales de Google.

| Prueba | Resultado |
| --- | --- |
| 180 consultas de perfil con solicitudes solapadas | Cada cliente recibió únicamente la identidad de su cuenta; no se mezclaron perfiles en el escenario probado. |
| 216 intentos de reserva concurrentes | Cada una de las 12 cuentas admitió exactamente 3 generaciones, según el límite configurado. |
| Sincronización tras agotar el cupo | Admitida para las 12 cuentas sin consumir otra creación. |
| Restauración del contexto de cuenta | Correcta al finalizar las solicitudes. |
| Preparación inicial desde dos clientes de la misma cuenta | Fallo H10 reproducido. |

También pasaron las pruebas existentes de cambio de cuenta durante respuestas pendientes, resultados privados, propiedad de trabajos, contextos anidados y expiración de permisos. Esto no demuestra la capacidad máxima de producción ni reemplaza una prueba de carga con servicios desplegados.

## Navegador y dispositivos

| Escenario | Observación |
| --- | --- |
| Móvil, 375 × 812 | Sin desbordamiento horizontal; logotipos cargados; botones flotantes dentro de pantalla; diálogo Datos sin desbordamiento horizontal y con cierre accesible. |
| Tableta, 768 × 1024 | Sin desbordamiento horizontal; botones flotantes dentro de pantalla; diálogo Datos ocupa el área disponible y abre/cierra. |
| Escritorio, 1440 × 900 | Sin desbordamiento horizontal; logotipos y controles flotantes visibles. |
| Primer ingreso móvil con cuenta y permisos simulados | Bienvenida Básico con 3 CV diarios/30 mensuales; oculta los pasos hasta cerrar el aviso. Gmail desaparece al completarse; Drive termina la verificación y cierra el diálogo. |

Las mediciones son de Chromium con tamaños de pantalla emulados. No se probaron iPhone/Safari, Android físico, teclado virtual, redes móviles ni navegación táctil real. No existe una línea base visual comparativa para acreditar ausencia de regresiones. No se ejecutó axe ni una auditoría WCAG completa.

Durante la revisión, una carga del servidor local mostró «Ollama no está disponible». No se generó un CV real ni se autorizó Google o Telegram. El servidor `127.0.0.1:8765` está en modo local, sin autenticación multiusuario: no equivale al entorno Firebase/Vertex publicado ni puede abrirse desde otro equipo usando su propio `127.0.0.1`.

## Verificación ECC

Se utilizó `verification-loop` y la guía de `browser-qa`, adaptadas al entorno local. La comprobación es manual; no es un hook automático.

| Fase | Resultado |
| --- | --- |
| Sintaxis | Python analizado y JavaScript comprobado por `scripts/verify_release.py`. |
| Tipado y lint | No ejecutados como análisis dedicados; el proyecto no ofrece esos scripts en `tests/package.json`. No se instalaron herramientas. |
| JavaScript | 311/311 pruebas aprobadas. |
| Python | 512/512 pruebas aprobadas, sin omitidas. |
| Cobertura backend | 82,64 %, con ramas, por encima del umbral del 80 %. |
| Aislamiento de pruebas Python | Copia temporal, red bloqueada, sin credenciales ni modificaciones de datos originales. |
| Revisión de diff | `git diff --check` sin errores de espacios. Los cambios previos del usuario se conservaron. |

Que la suite pase no invalida H09–H11: son escenarios adicionales reproducidos fuera de la suite existente. El siguiente paso es corregirlos y convertir sus reproducciones en regresiones permanentes antes de cerrar la revisión.

## Evidencia y reproducción

- Suite integral: `venv/Scripts/python.exe scripts/verify_release.py --output tmp/revision-final-2026-10-19`.
- Sesiones concurrentes y fallo de cuota: `venv/Scripts/python.exe tmp/revision-final-multiusuario.py`.
- Carrera de preparación: `venv/Scripts/python.exe tmp/revision-final-carreras.py`.
- Transición de planes: `node tmp/revision-final-avisos.cjs`.
- Resultados completos: `tmp/revision-final-2026-10-19/python-summary.json`, `release-summary.json`, `python-tests.txt`, `node-tests.txt` y `coverage.txt`.
- Capturas: `movil-375.png`, `tableta-768.png`, `escritorio-1440.png` y `bienvenida-movil-simulada.png`, en la misma carpeta de evidencia.

No se leyeron almacenes de autenticación, claves privadas o tokens para esta revisión. No se contactó a otros usuarios, no se enviaron correos y no se modificaron Firebase, cuentas, permisos ni contadores reales.
