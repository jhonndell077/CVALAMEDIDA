# Correcciones y segunda revisión exhaustiva

Fecha: 19 de octubre de 2026. Proyecto: CV a la medida.

**Resultado:** los tres defectos del diagnóstico anterior están corregidos y cuentan con pruebas permanentes. La verificación local integral pasa. La revisión ampliada no detectó nuevos bloqueantes en los escenarios ejecutados. Esto no certifica las integraciones reales ni todos los dispositivos.

## 1. Estado de los defectos anteriores

| Hallazgo | Corrección | Comprobación |
| --- | --- | --- |
| H09: errores que consumían CV | Las peticiones fallidas devuelven su reserva mediante una actualización atómica e idempotente. También se liberan los lugares de concurrencia, incluso si falla la creación del registro del trabajo. | 25 solicitudes inválidas consecutivas devolvieron HTTP 400 y consumieron 0 CV diarios y 0 mensuales. Las solicitudes exitosas conservan su consumo y respetan el límite. |
| H10: carpetas duplicadas al iniciar desde dos equipos | La preparación toma una reserva exclusiva por UID en el almacenamiento compartido antes de crear carpetas. Se renueva durante las llamadas a Drive y se libera al terminar o fallar. El segundo navegador espera y reintenta la preparación con las credenciales ya concedidas. | Dos clientes de la misma cuenta no crean un segundo banco. Tras esperar/reintentar, reutilizan el registro y las carpetas de la primera sesión. |
| H11: aviso ausente al volver a Básico | El servidor publica una versión del estado de límites, incluido el retorno al plan heredado. El cliente detecta la transición aunque el plan de destino ya se haya visto. | Básico → Pro → Básico vuelve a mostrar los límites correctos; una consulta posterior sin cambios no repite el aviso. |

También se corrigió un caso relacionado: renovar el token de la misma cuenta ya no elimina ni vuelve a crear un aviso sin leer. La bienvenida se marca como reconocida cuando el usuario la cierra.

## 2. Reglas de cupo verificadas

- Una petición de generación inválida no deja consumo ni lugares ocupados en la cola.
- Un CV exitoso sigue consumiendo una creación. El cuarto se rechaza cuando el límite configurado es tres.
- Un trabajo web fallido devuelve su reserva; recibir de nuevo el mismo trabajo no devuelve otro CV.
- Treinta y seis devoluciones concurrentes de una misma reserva no reducen el consumo de otro CV completado.
- Una devolución de ayer no reduce el consumo de hoy; una reserva del mes anterior no reduce el consumo del mes actual.
- Las devoluciones están separadas por UID, incluso si dos cuentas usan el mismo identificador de operación.
- Una reserva de petición directa vencida se recupera cuando se revisa la cola.
- Si falla la protección de credenciales antes de guardar el trabajo en segundo plano, no se reserva un CV. La consulta previa de capacidad tampoco consume cupo.
- Una sesión de Drive vencida antes de que el trabajador genere el CV devuelve la reserva.
- En Telegram, los fallos de análisis o guardado sin un CV recuperable devuelven la reserva. Si el CV ya está en Drive y se pierde la confirmación de entrega, se conserva un solo consumo y no se repite el envío automáticamente.

El saldo contempla las reservas de trabajos en curso para evitar superar el límite con solicitudes simultáneas. El código no reconstruye ni reinicia consumos históricos de producción.

## 3. Preparación simultánea del banco

- La exclusión es compartida entre instancias del servidor, no solamente un bloqueo de Python en memoria.
- Las llamadas de preparación renuevan la reserva antes de consultar o modificar Drive.
- Si se pierde la reserva, esa preparación no puede confirmar el registro ni liberar una reserva tomada por otra instancia.
- Si una preparación falla después de crear la primera carpeta, el siguiente intento reutiliza esa carpeta.
- Una reserva abandonada vence después de tres minutos sin renovación y permite continuar la preparación.
- El navegador reintenta solamente el conflicto específico `account_setup_in_progress`, hasta ocho veces. No repite la ventana de Google ni convierte errores distintos en un bucle de reintentos.
- Si el usuario cierra sesión mientras espera, el intento anterior se cancela antes de enviar otra petición.

Si la preparación sigue ocupada al terminar la espera limitada, el usuario recibe un mensaje para volver a sincronizar. No se promete una espera ilimitada ni se crean carpetas paralelas para resolverla.

## 4. Simulación ampliada de equipos y usuarios

Se ejecutaron **120 sesiones independientes simuladas**, correspondientes a **30 cuentas y cuatro clientes por cuenta**, con hasta 40 tareas simultáneas. Cada cliente usó su propio cliente HTTP de prueba. Se usaron identidades ficticias, almacenamiento en memoria y proveedores simulados; la red externa estaba bloqueada.

| Escenario | Volumen | Resultado |
| --- | --- | --- |
| Consulta de perfiles con solicitudes solapadas | 480 peticiones | Cada cliente recibió la identidad y el perfil de su cuenta. No se observaron mezclas. |
| Reserva concurrente de generaciones | 600 intentos | Las 30 cuentas admitieron exactamente 5 generaciones cada una, según el límite de la prueba. |
| Sincronización después de agotar el límite | 30 cuentas | Permitida sin otra creación consumida. |
| Generación inválida reiterada | 25 peticiones | Todas devolvieron 400; consumo diario y mensual igual a cero. |
| Restauración del contexto de cuenta | Al terminar las solicitudes | Correcta. |
| Mezcla de solicitudes exitosas y fallidas de una cuenta | Prueba permanente con varios hilos | El consumo coincide con el número de respuestas exitosas y no supera el límite. |

Los nombres de dispositivo en las cabeceras HTTP son etiquetas sintéticas. No acreditan haber ejecutado Safari o Android reales. Esta prueba verifica invariantes de concurrencia y aislamiento; no mide la capacidad máxima del alojamiento de producción.

## 5. Navegador y tamaños de pantalla

Se usó Chromium con el HTML, CSS y módulos reales de bienvenida/verificación/formulario, servidos en un entorno temporal que simula los permisos y las respuestas de guardado. No se usaron credenciales reales ni se escribieron archivos en Drive.

| Tamaño | Bienvenida dentro de pantalla | Desbordamiento horizontal |
| --- | --- | --- |
| 320 × 568, móvil pequeño | Sí | No |
| 375 × 812, móvil | Sí | No |
| 667 × 375, móvil horizontal | Sí | No |
| 768 × 1024, tableta | Sí | No |
| 1440 × 900, escritorio | Sí | No |

En el flujo móvil se comprobó:

1. La bienvenida del Básico muestra cupos y saldo.
2. Al cerrar el aviso aparecen las verificaciones.
3. Gmail desaparece al completar su paso.
4. Drive cierra la verificación y abre el formulario inicial.
5. En 320 píxeles, formulario y vista previa no desbordan horizontalmente.
6. La vista previa refleja el nombre ficticio editado antes de guardar y permite seguir editando.
7. Guardar cierra el formulario. La confirmación de guardado y consolidación queda visible.
8. La navegación por teclado alcanza los controles posteriores a la confirmación.

La consola del escenario móvil no presentó errores ni advertencias capturados. No hay una línea base visual comparativa; no se acredita ausencia de toda regresión visual. No se ejecutó un escáner axe ni una auditoría WCAG completa.

## 6. Verificación integral

Se aplicó la guía ECC `verification-loop` mediante el script existente del proyecto, sin instalar herramientas ni publicar.

| Comprobación | Resultado |
| --- | --- |
| Sintaxis Python y JavaScript | Aprobada |
| Suite JavaScript | **316/316 aprobadas** |
| Suite Python | **533/533 aprobadas**, sin omitidas |
| Cobertura del backend, con ramas | **82,73 %**, supera el umbral de 80 % |
| Entorno Python de la suite | Copia desechable; red bloqueada; sin credenciales; sin modificar datos originales |
| Revisión de espacios del diff | Sin errores |
| Búsqueda acotada de patrones de claves privadas en fuentes revisadas | Sin coincidencias; no se leyeron almacenes de autenticación |
| Tipado y lint dedicados | No ejecutados: no se instalaron herramientas ni se inventaron scripts ajenos al proyecto |

Las advertencias de Vertex, envío y fallos de proveedores que aparecen en el registro de pruebas corresponden a escenarios simulados con red bloqueada.

## 7. Límites del diagnóstico y validación restante

No quedaron defectos bloqueantes reproducidos sin corregir en esta batería. Siguen sin acreditarse:

- Autorización y renovación reales de Google, Drive y Telegram con varias cuentas de prueba.
- iPhone/Safari, Android físico, teclado virtual, instalación PWA y comportamientos del sistema operativo al suspender la app.
- Carga con las latencias, permisos, capacidad y servicios reales del alojamiento publicado.
- Accesibilidad completa y métricas de experiencia de campo.

El servidor `127.0.0.1:8765` usa el modo local y no equivale al entorno Firebase/Vertex. No se cambió la configuración de producción, no se reiniciaron consumos reales y no se realizó un despliegue.

## 8. Evidencia reproducible

- Regresiones nuevas: `tests/test_first_login_hardening.py`, y ampliaciones en `tests/drive_accounts.test.js`, `tests/subscription-notices.test.cjs` y `tests/test_plan_catalog.py`.
- Suite completa: `venv/Scripts/python.exe scripts/verify_release.py --output tmp/revision-exhaustiva-2026-10-19`.
- Simulación ampliada: `venv/Scripts/python.exe tmp/auditoria-exhaustiva-sesiones.py`.
- Resultados: `tmp/revision-exhaustiva-2026-10-19/release-summary.json`, `python-summary.json`, `python-tests.txt`, `node-tests.txt`, `coverage.txt`, `sesiones.json` y `pantallas.json`.
- Capturas: `bienvenida-movil.png` y `guardado-movil.png`, en la misma carpeta de evidencia.

Los cambios previos del proyecto se conservaron. Los hallazgos originales y su evidencia anterior permanecen en `AUDITORIA-MULTIUSUARIO-2026-10-19.md`, marcado como histórico.
