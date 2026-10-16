# Vista de conexiones del administrador

URL: https://cvalamedida.web.app/admin/conexiones (también en el segundo dominio configurado).

Iniciar sesión mediante el botón Google con la cuenta propietaria original del proyecto. No solicita permisos de Drive ni Gmail. La página sirve una interfaz estática; los datos actuales se obtienen de `/api/admin/connections`, que verifica el token de Firebase con revocación y exige el correo propietario en el servidor. Una cuenta distinta recibe 403; sin sesión, 401. Si no existe propietario configurado, el acceso se rechaza.

La página consulta cada 60 segundos mientras está visible. La API acredita únicamente que atendió la solicitud y validó al administrador; el navegador comprueba además el HTTP de la portada. La verificación no invoca modelos ni envía mensajes. Son solicitudes reales al backend y pueden generar consumo de infraestructura. No se modifican controles presupuestarios.

Drive, Vertex, Tasks, Storage, worker, Telegram, Gmail y Push conservan la etiqueta «sin verificar»; las relaciones dibujadas describen la arquitectura auditada, no tráfico observado. El presupuesto y las revisiones que figuran en el diagrama son evidencia histórica fechada. Esta entrega publica el monitor existente y no añade observabilidad autenticada de todas las integraciones.

Cerrar sesión limpia la vista; respuestas de una sesión anterior no pueden restaurarla. No se conserva un estado verde cuando vence la lectura. La identidad y los tokens nunca se incluyen en respuestas de diagnóstico ni se guardan en archivos propios del monitor. Firebase gestiona la sesión en el dispositivo.

Pruebas: 365 backend con red bloqueada y 80,68 % de cobertura; 161 JavaScript. Incluyen rechazo de usuarios, ausencia de configuración del propietario, no lectura del banco para administrar, respuestas tardías y cierre de sesión. El acceso interactivo desde un móvil requiere que su titular complete Google; no se han usado cuentas ajenas.

Reversión: código anterior `13176a7f8bbd4b31e74abbf0478a8ccf76705524`; conservar configuración y evidencias del despliegue. Para revertir la función o Hosting, seleccionar la revisión/versión anterior compatible o desplegar el código anterior mediante el procedimiento habitual. No eliminar usuarios ni datos para revertir esta vista.

Publicación confirmada: página y recursos HTTP 200; diagnóstico sin sesión HTTP 401. En el navegador integrado, la sesión propietaria ya existente fue aceptada y mostró web/API disponibles. No se extrajeron tokens ni se hizo un nuevo inicio de sesión. Firebase confirmó la publicación de `api` y ambos Hosting. Evidencia local: `tmp/admin-connections-verification/published-checks.json` y `tmp/admin-connections-deploy.txt`.


## Sondas autenticadas incorporadas

El panel añade comprobaciones de identidad Firebase, lectura de metadatos del banco Drive con su cuenta de servicio, listado de metadatos Storage, estado RUNNING de Cloud Tasks, salud autenticada del worker, generación Vertex sintética y Telegram getMe/getWebhookInfo. Las lecturas se conservan cinco minutos por proceso; Vertex quince minutos. Las fechas y el alcance se muestran por tarjeta. La generación es breve pero facturable y utiliza el mismo modelo configurado. No se envían documentos personales a la prueba. El monitor no acredita un flujo completo de generación/entrega de CV.

El botón «Verificar Drive y Gmail» renueva la autorización Google del propietario, solicita los mismos alcances de lectura de Drive/envío Gmail usados por la aplicación y verifica identidad y permiso efectivo sin enviar correo. Después consulta metadatos de banco y archivo con OAuth. El archivo no debe comprobarse con la cuenta de servicio del banco, porque esa cuenta no necesita acceso al archivo personal.

Push solo se marca correcto después de recibir una confirmación de la página administradora correspondiente a una notificación real. El botón pide permiso del navegador, utiliza una suscripción registrada del mismo administrador y envía una prueba a ese único endpoint. No admite destinatarios arbitrarios ni reenvía automáticamente una respuesta incierta. El service worker muestra una notificación diferenciada y devuelve el nonce a la página; la recepción con la aplicación cerrada sigue siendo otra prueba. El permiso requiere interacción del titular del dispositivo. Si no se concede, el resultado permanece pendiente.

Se añadió el rol personalizado `cvConnectionQueueObserver`, con un único permiso `cloudtasks.queues.get`, únicamente sobre la cola `cv-telegram` para `cv-runtime`. Se conservaron todas las vinculaciones previas y respaldos de la política con etag en `tmp/integrations-monitor-verification/`. No concede lectura del contenido de tareas ni administración de la cola. Reversión: retirar solo esa vinculación y el rol cuando no tenga otros usos; no restaurar ciegamente políticas antiguas.

La primera sonda Vertex rechazó MINIMAL; se corrigió a LOW, ya utilizado por el flujo de la aplicación. La primera sonda Drive intentaba leer el archivo usando la identidad del banco y obtuvo 404; se separó del chequeo OAuth del administrador. No se cambiaron permisos sobre las carpetas para acomodar el monitor. Los tres cortes presupuestarios permanecían CONFIGURED durante la revisión; no se incrementaron ni levantaron.

Validación de esta fase: 383 pruebas backend con red bloqueada y 81,23 % de cobertura; 164 JavaScript. Los fixtures comprueban sanitización de errores, autorización por propietario, caducidad/caché, cola pausada, contratos del worker/modelo, destinos Push registrados y ausencia de verde antes del acuse de recepción. Las pruebas de servicios reales se documentan separadamente después del despliegue.

Resultado desplegado 16/10/2026 17:29 (hora local): diez comprobaciones positivas en la sesión propietaria, incluyendo metadatos de banco y archivo con OAuth y permiso Gmail. Push quedó esperando autorización del navegador; no se atribuye entrega. Se pidió al titular que complete el permiso y la prueba desde su dispositivo. El acceso sin credenciales a diagnóstico y salud del worker devuelve 401. Evidencia local: `tmp/integrations-monitor-verification/published-result.json`. El éxito de estos alcances no es una prueba integral de procesamiento/entrega de CV.


## Corrección del acuse Push en páginas suspendidas

Las capturas aportadas por el administrador acreditaron que la notificación llegó, mientras el diagrama seguía pendiente. El protocolo anterior dependía de un `postMessage` hacia la página, un nonce guardado solo en memoria del proceso durante 90 segundos y un resultado de cinco minutos. El cambio elimina esas dependencias para el registro principal.

El envío reserva un objeto privado `jobs/admin-push-receipt-<hash-del-uid>.json` mediante precondición de generación. Contiene el hash de una capacidad aleatoria de 32 bytes, la correlación y fechas; nunca el token sin hash. El service worker muestra la notificación y envía su acuse directamente al servidor, sin requerir una pestaña abierta ni una sesión Firebase accesible en segundo plano. La capacidad solo autoriza confirmar ese registro, vence a los 15 minutos, se compara en tiempo constante y no permite leer datos administrativos. El endpoint acepta únicamente POST JSON con dos campos y limita solicitudes a 30 por minuto por proceso; las demás rutas administrativas mantienen autenticación Firebase.

El acuse se guarda con control de concurrencia, es idempotente y sobrevive a reinicios. El monitor lee el registro persistente en cada consulta y muestra fecha de recepción durante 24 horas; después solicita otra prueba. Eso representa evidencia de la última recepción, no disponibilidad ininterrumpida. Al pulsar una notificación se reintenta guardar el acuse si fuera necesario. No se reenvía la notificación al reintentar el acuse.

El frontend espera a que el service worker actualizado esté activo antes de probar y evita que la respuesta tardía del envío reemplace un éxito confirmado por «esperando recepción». El grupo Canales identifica expresamente qué componente falta, por ejemplo «Falta: Gmail», para no atribuir a Push una autorización Google caducada.

Validación: 387 pruebas backend aprobadas, cobertura 81,42 % con red bloqueada; 167 JavaScript aprobadas. Incluyen página ausente, vaciado de memoria del proceso, reintentos, confirmación repetida, token erróneo/caducado, conflicto de generación, límites de ingreso y activación del worker. Las notificaciones antiguas no contenían la nueva capacidad y no se registran retroactivamente como prueba automática: hace falta una nueva prueba del dispositivo después de recargar la vista. La captura del titular es evidencia humana de la entrega anterior, separada del nuevo protocolo automatizado.
