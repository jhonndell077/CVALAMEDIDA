# Supervisor de arquitectura por cuenta

## Implementación

Los eventos nuevos incorporan accountKey, SHA256 del UID obtenido exclusivamente de identidad verificada en backend o contexto de trabajo autorizado. No se admite identidad del payload ni parámetros para atribuir eventos. No se guardan UID, email, tokens, CV ni texto de respuestas Google. Los eventos anteriores y las etapas sin identidad permanecen Sin atribución; no se migran a la cuenta administrativa.

GET administrativo /api/admin/architecture permite account=<referencia64hex> y account=unattributed, con autorización previa a lectura. El backend aplica el filtro; mantiene resúmenes globales de cuentas y contadores explícitos de alcance. Configuración incluye Ver diagnóstico por usuario: calcula la referencia localmente usando el UID ya disponible en esa vista administrativa. El selector conserva acceso a Todas las cuentas, Sin atribución y referencias observadas.

Alertas agrupadas por cuenta y etapa. Un éxito de otra cuenta no resuelve un fallo. Un reintento de la misma cuenta puede confirmar recuperación sólo para el mismo componente, servicio y etapa; HTTP genérico requiere misma ruta. Recibir telemetría no acredita funcionamiento del proveedor. Las señales de navegador siempre están sin confirmación del proveedor. Los motivos permitidos de Google sobreviven al almacenamiento y tienen acciones correctivas específicas.

El navegador comunica apertura pendiente, bloqueo/cancelación y falta de confirmación OAuth, y fallos de red de rutas instrumentadas. Cola únicamente en memoria, máximo 12 señales y cinco minutos, sin persistencia de datos personales, sin sondeos. Reintenta al recuperar conexión o recibir otra señal y descarta pendientes al cambiar de cuenta. La revisión detectó y corrigió una pérdida de señales por saturación durante envío. También se corrigió la emisión de errores al diálogo Mis datos desde las funciones globales reales.

## Validación

487 pruebas Python y 276 JavaScript (763) aprobadas con scripts/verify_release.py --output tmp/account-supervisor-final. Cobertura Python 82,4 %. Fixtures, red bloqueada y sin operaciones reales de sincronización, generación, cambios de cuenta, mensajes o cobros. Casos de dos usuarios, suplantación, acceso no autorizado, eventos legados, workers, motivos seguros, recepción de telemetría, recuperación, saturación y cambio de cuenta mientras hay token o envío pendiente. Revisión de seguridad adicional de solo lectura, dos defectos corregidos con regresiones.

## Alcance y costos

La retención continúa siendo una hora y 400 eventos compartidos; no es un historial completo ni una garantía de capturar todo fallo. Un fallo anterior al inicio de sesión o sin conectividad puede no llegar. Cerrar la pestaña descarta señales en memoria. Los eventos antiguos no permiten reconstruir identidad retroactivamente. La falta de eventos no demuestra salud.

Se reutiliza el bucket privado existente, sin cambios IAM, reglas, credenciales o dependencias. Cambiar de filtro lee la ventana existente; no sondea servicios de usuarios. Las señales del navegador agregan solicitudes y escrituras diagnósticas acotadas, con límite de 12 por minuto y cuenta en el receptor. El refresco automático administrativo sigue siendo opcional, cada 60 segundos mientras la vista está visible. Los costos posibles son invocaciones de Functions y operaciones de Cloud Storage existentes. No hay escaneo externo, importación de Cloud Logging, reparación automática ni comprobación activa de Drive desde los diagramas.

Archivos principales: architecture_diagnostics.py, diagnostic_store.py, diagnostic_stages.py, client_diagnostics.py, app.py, static/admin-architecture.html/.js/.css, static/client-supervisor.js, static/app.js, static/drive.js, static/index.html y pruebas asociadas.


## Comprobación publicada

Firebase confirmó ambas funciones y ambos sitios Hosting. Se verificó la sesión administrativa, el selector y la acción Ver diagnóstico de la cuenta afectada, sin cambios administrativos: cero eventos atribuidos no se marcó como salud confirmada. Una carga normal de la app con la sesión administrativa existente produjo eventos nuevos con referencia de cuenta verificada (26 atribuidos observados en la comprobación global), mientras los eventos legados se conservaron sin atribución. No se inició sincronización, autorización Drive, generación ni mensajes. Se ajustó la etiqueta Referencias en el selector para no llamar cuentas con señales a una selección sin eventos.
