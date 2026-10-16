# Plan de reestructuración y cierre del piloto

Fecha: 2026-10-16. Base: `ab2f210e4d15e92cd187b25237e0496a768c4bae`.
Objetivo confirmado: hasta **10 usuarios simultáneos**.
Presupuesto objetivo confirmado: **US$5 mensuales**.

## Resultado esperado

Conservar los recorridos corregidos de Google, Drive, IA, exportación, Gmail y
Telegram; completar controles operativos y acreditar el piloto con evidencias.
Una aprobación externa o una prueba pendiente no se cierra con una modificación
de documentación. Las 503 pruebas del cierre anterior son la línea base, no el
resultado de esta fase.

## Orden de ejecución

| Etapa | Cambio concreto | Archivos / área | Aceptación |
|---|---|---|---|
| 1. Admisión | Unificar vacantes y callbacks Gmail de Telegram; añadir límites diarios y mensuales por cuenta, atómicos e idempotentes | `job_runtime.py`, nuevo módulo de política, `background_jobs.py`, `telegram_bot.py` | Carreras y reintentos no superan límites ni cuentan dos veces; HTTP 429 informa vencimiento; sin nuevas llamadas externas tras rechazo |
| 2. Banco | Clasificar los cuatro avisos reales; separar conflicto de identidad, fechas, notas y exclusiones antiguas | `drive_bank.py`, `profile_deletions.py`, `profile_edits.py`, interfaz del banco | Cada aviso tiene motivo y acción; ningún dato se elimina para ocultar el aviso; decisiones de contenido ambiguo quedan para su titular |
| 3. Recuperación | Inventario y ensayo de restauración selectiva en almacenamiento aislado; política por categoría | Herramientas administrativas y documentación | Huellas iguales tras restaurar; versiones posteriores se conservan; cuentas, vínculos, claves y reservas Gmail no entran en borrado temporal |
| 4. Dependencias y entrega | Revisar transitivas, reproducibilidad para Python 3.13 y gate común | `requirements*`, `scripts/verify_release.py`, workflow, `Deploy.ps1` | Sin vulnerabilidades críticas/altas explotables sin tratamiento; instalación limpia reproducible; gate impide publicar fallos |
| 5. Identidad externa | Verificar consentimiento, publicación, scopes, popup, cuenta Google independiente, permisos parciales y revocación | Google Auth Platform, `static/drive.js`, `user_accounts.py`, onboarding | Evidencia real con segunda cuenta controlada; datos separados; rechazo y recuperación explicados al usuario |
| 6. Piloto | Carga sintética aislada de diez identidades, fallo de proveedor, reintentos y recuperación de cola | Harness local y entorno de prueba; `main.py`, Cloud Tasks si la medición justifica ajuste | Cero fugas entre cuentas; cero envíos duplicados; solicitudes rápidas y espera de cola medidas por separado; sin prometer tiempos de IA no medidos |
| 7. Navegador y Push | Desktop/móvil, consentimiento interactivo y notificación con aplicación cerrada | Frontend, service worker, suscripciones | Evidencias por navegador/dispositivo; si Push falla, el resultado sigue recuperable en historial |
| 8. Publicación | Respaldar cambios de configuración, publicar versión verificada y comprobar el sitio | Firebase Functions y ambos Hosting | Código y publicación identificados; smoke acotado sin contactar terceros; reversión documentada |

## Diseño de la primera etapa

- Mantener el máximo existente de diez pendientes por cuenta.
- Añadir, como política conservadora tras confirmar US$5/mes, 10 admisiones nuevas
  por día UTC y 50 por mes UTC y cuenta. Son límites de trabajo, no importes de dinero.
  Las operaciones directas y en cola comparten el mismo registro durable.
- Identificadores repetidos no consumen otra unidad; las continuaciones de un
  trabajo admitido conservan su admisión. El registro se actualiza mediante CAS.
- Un rechazo por cuota informa el periodo y cuándo puede intentarse nuevamente.
- La política se configura por variables de entorno; valores inválidos bloquean
  admisión en vez de desactivar silenciosamente los límites. No se reinician
  contadores existentes durante un despliegue.
- Los comandos informativos del bot y la consulta de resultados permanecen
  disponibles al alcanzar un límite.

## Capacidad y costos

Diez sesiones simultáneas no significan diez análisis de IA simultáneos. Se medirá
la aceptación HTTP, el tiempo en cola y el procesamiento. Se conserva inicialmente
concurrencia uno por instancia por el uso de PDF y memoria; escalar instancias y
despachos exige antes comprobar consistencia, memoria y presupuesto.

El usuario confirmó US$5 mensuales. Se aplica un presupuesto de proyecto por ese
importe y spend caps separados: Vertex US$3, Cloud Run US$1 y Functions US$0,50.
Quedan US$0,50 de margen orientativo para otros servicios, sin corte nativo total
para todas esas categorías. Las alertas ordinarias no detienen por sí mismas el
gasto y el corte de spend caps tiene demora y permite terminar solicitudes en
curso. Por tanto, no se promete una factura total matemáticamente limitada a US$5.
Los destinatarios administrativos se verifican como la cuenta propietaria antes
de crear alertas. Los límites de trabajos tampoco equivalen a importes de dinero.

## Reestructuración de código

Aplicar cambios pequeños por responsabilidad, comenzando por la política de
admisión. No reescribir de una vez `app.py`, `telegram_bot.py` ni `drive_bank.py`.
Extraer módulos solo con contratos y regresiones. Conservar identidades `v2`,
precondiciones Drive, reservas Gmail y compatibilidad de trabajos existentes.

## Evidencia y reversión

Cada corrección funcional sigue RED → implementación → GREEN. Después se ejecuta
el gate integral existente y se revisa el diff y la exposición de secretos. La
reversión de un despliegue no borra contadores, claves, reservas ni datos del banco.
Los respaldos personales permanecen privados; los informes contienen conteos,
categorías y resultados, no tokens ni contenido personal innecesario.

## Dependencias externas que deben quedar visibles

- Google decide la aprobación de scopes sensibles/restringidos. No se sustituye
  esa aprobación activando una casilla o creando usuarios Firebase artificiales.
- Una segunda cuenta Google y un dispositivo de prueba deben estar bajo control
  del usuario; no se usan cuentas de terceros ni se crean identidades ficticias
  para afirmar un onboarding real.
- La atribución o fecha de un documento ambiguo necesita evidencia o decisión de
  su titular; no se inventa para obtener cero avisos.
- Una protección GitHub no disponible en el plan actual se informa; no se contrata.

## Fuentes primarias consultadas

- [Google: verificación de scopes restringidos](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)
- [Firebase: instancias y concurrencia](https://firebase.google.com/docs/functions/manage-functions)
- [Cloud Billing: presupuestos y alertas](https://docs.cloud.google.com/billing/docs/how-to/budgets)
- [Cloud Billing: spend caps](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps)

## Seguimiento

La etapa 1 está implementada y verificada localmente. Se corrigió también la
liberación prematura de un cupo cuando Telegram aún estaba en `delivery_started`
con lease vigente. Las pruebas cubren diez cuentas simultáneas y cuotas por periodo.

La etapa 3 tiene un ensayo real selectivo aprobado sobre una configuración de
cuenta respaldada y un runbook de operación. No se acredita recuperación total
ni eliminación automática por cuenta. La etapa 4 tiene locks con hashes, Pillow
12.3.0, instalación limpia en Python 3.13 y revisión de avisos conocidos sin
hallazgos en runtime ni herramientas al cierre.

Las etapas 2, 5 y 7 mantienen las decisiones del titular, la aprobación OAuth y
los dispositivos/cuenta independiente como pendientes explícitos. La etapa 6
acredita aislamiento concurrente local, pero no latencia y costo de carga real
en nube. Publicar correcciones no elimina esas condiciones de apertura.

Ver el informe `REESTRUCTURACION-PILOTO.md` de la carpeta de auditoría para el
resultado del despliegue y la evidencia. El runbook está en `OPERACION-PILOTO.md`.

**Bloqueo del cierre desplegado:** 515 pruebas locales aprobadas, incluido arranque
de ambos entry points con Functions Framework sin red. La publicación Linux no
superó el health check de contenedor; no hay causa definitiva aislada. Google
conserva como últimas revisiones listas `api-00095-say` y
`telegram-worker-00068-nic`. Los caps Vertex y Functions pasaron a `ENFORCED` por
consumo acumulado. No se levantan ni se amplía el presupuesto por inferencia.
La rama de correcciones se conserva separada de `main` hasta cerrar publicación
y verificaciones. La facturación bruta de caps no prueba gasto neto exacto.
