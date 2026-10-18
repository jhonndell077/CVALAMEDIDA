# Conexión de cuentas nuevas y ventana Mis datos

Las capturas acreditan inicio de sesión, pero no acreditan conexión de Drive ni preparación del banco. La interfaz mostraba instrucciones de inicio de sesión aunque ya existía sesión, y los errores del proceso estaban fuera del diálogo modal. Se corrigieron ambos problemas: estado de sesión explícito y errores dentro de Mis datos, con limpieza al cambiar de cuenta. No se cambian permisos ni se evitan las comprobaciones de identidad y propiedad de Drive.

Revisión de código: sincronización solicita autorización de Google directamente desde el gesto del usuario y luego prepara las carpetas de su propia cuenta; no necesita Telegram. Las pruebas existentes verifican el inicio síncrono del popup, la ausencia de dependencia de Telegram, la creación con fixtures y el cambio de cuenta. Se añadió un caso para sesión iniciada sin Drive y errores visibles dentro del diálogo.

Consulta de solo lectura de Google Cloud: OAuth en producción, usuarios externos, 8 de 100 cupos. No existe evidencia de bloqueo por modo de pruebas o agotamiento de ese límite. La página Centro de verificación devolvió error de carga; no se pudo confirmar su estado. No se cambiaron clientes, permisos, cuentas ni configuración OAuth.

No se reprodujo el intento concreto del teléfono ajeno ni se autorizaron permisos en nombre de esa persona. La causa de su sincronización fallida sigue sin determinarse hasta disponer del mensaje de Google o del error del intento. No se presenta esta corrección de visibilidad como prueba de que su acceso a Drive ya funcione.

Verificación local con scripts/verify_release.py, fixtures y red bloqueada; sin generar CV, sincronizar, modificar datos ni consumir cupos reales. La publicación contiene únicamente los cambios de interfaz y el manifiesto generado.

Resultado: 475 pruebas Python y 258 JavaScript aprobadas (733), cobertura 82,14 %. Hosting publicado en ambos dominios, build 20261018T012954Z-c6e6d708. Archivos publicados comparados con los probados. Se comprobó en la app publicada una sesión iniciada sin conexión Drive, sin pulsar sincronización ni crear carpetas reales. Captura: tmp/datos-conexion-publicado.png.


## Botón móvil: Google no abre

El usuario confirmó que no se abre ninguna ventana de Google. Se sustituyó la delegación mediante click sintético al botón oculto por una función de sincronización compartida invocada directamente desde el botón flotante. La autorización se inicia antes de abrir los cuadros de carga, tanto en sincronización como en el conector Drive. Esto evita depender de un botón oculto/inert y del cambio de capa modal para iniciar el popup. No se cambian permisos, cuentas ni configuración de Google.

Nuevas pruebas: el botón flotante invoca la acción sin click sintético con Mis datos abierto; OAuth arranca antes de la interfaz de carga; pulsaciones repetidas no duplican la operación. Suite completa: 475 Python + 260 JavaScript (735), todas aprobadas, cobertura Python 82,14 %, con red bloqueada. No se probó una autorización real en Safari/iPhone ni se sincronizaron datos reales. La corrección del recorrido de apertura no acredita por sí sola la concesión de permisos ni la sincronización completa en ese dispositivo.

Publicación confirmada de la corrección móvil: 20261018T013530Z-bb7a01c0. Cuatro archivos publicados coinciden con los probados.


## Capturas con rechazo de Google

El nuevo mensaje fotografiado procede del traductor genérico de HTTPError de drive_request: cualquier 403/404, incluso de userinfo, se convertía en un problema para guardar en CV GENERADOS. Por tanto la captura no permite concluir almacenamiento lleno ni falta de permiso de una carpeta concreta. La sesión Firebase sigue siendo independiente.

Se corrigió la clasificación: inspección acotada de 16 KiB de respuesta JSON, únicamente motivos de una lista permitida, sin registrar respuestas completas, tokens, nombres o identificadores. Distingue almacenamiento lleno, permisos insuficientes, permiso de archivo/carpeta, API no configurada, límites de Google y causa desconocida. La comprobación userinfo se observa en etapa OAuth en lugar de atribuirla al guardado. Se conservan las validaciones de identidad y los controles de acceso existentes. No se concede ningún permiso adicional.

Fuente técnica: https://developers.google.com/workspace/drive/api/guides/handle-errors . Consulta administrativa del historial no mostró un evento confirmado del intento fotografiado; no se reconstruye ni se inventa su causa. El siguiente intento podrá mostrar el motivo permitido si Google lo proporciona; en ausencia de evidencia se conserva Causa no determinada.

Pruebas: 478 Python + 260 JavaScript (738), todas aprobadas, cobertura 82,29 %, red bloqueada. Casos de razón confirmada, rechazo de identidad, causa desconocida, aislamiento de texto privado y propagación del código seguro en el wrapper real. Sin operaciones reales sobre la cuenta afectada. La corrección mejora el diagnóstico y no acredita que el acceso a Drive de esa persona haya sido reparado.

Publicación confirmada de api, telegram_worker y Hosting: 20261018T015116Z-258f69b3. Versión pública comparada. Sin probar operaciones reales de Drive.
