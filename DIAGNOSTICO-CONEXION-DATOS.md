# Conexión de cuentas nuevas y ventana Mis datos

Las capturas acreditan inicio de sesión, pero no acreditan conexión de Drive ni preparación del banco. La interfaz mostraba instrucciones de inicio de sesión aunque ya existía sesión, y los errores del proceso estaban fuera del diálogo modal. Se corrigieron ambos problemas: estado de sesión explícito y errores dentro de Mis datos, con limpieza al cambiar de cuenta. No se cambian permisos ni se evitan las comprobaciones de identidad y propiedad de Drive.

Revisión de código: sincronización solicita autorización de Google directamente desde el gesto del usuario y luego prepara las carpetas de su propia cuenta; no necesita Telegram. Las pruebas existentes verifican el inicio síncrono del popup, la ausencia de dependencia de Telegram, la creación con fixtures y el cambio de cuenta. Se añadió un caso para sesión iniciada sin Drive y errores visibles dentro del diálogo.

Consulta de solo lectura de Google Cloud: OAuth en producción, usuarios externos, 8 de 100 cupos. No existe evidencia de bloqueo por modo de pruebas o agotamiento de ese límite. La página Centro de verificación devolvió error de carga; no se pudo confirmar su estado. No se cambiaron clientes, permisos, cuentas ni configuración OAuth.

No se reprodujo el intento concreto del teléfono ajeno ni se autorizaron permisos en nombre de esa persona. La causa de su sincronización fallida sigue sin determinarse hasta disponer del mensaje de Google o del error del intento. No se presenta esta corrección de visibilidad como prueba de que su acceso a Drive ya funcione.

Verificación local con scripts/verify_release.py, fixtures y red bloqueada; sin generar CV, sincronizar, modificar datos ni consumir cupos reales. La publicación contiene únicamente los cambios de interfaz y el manifiesto generado.

Resultado: 475 pruebas Python y 258 JavaScript aprobadas (733), cobertura 82,14 %. Hosting publicado en ambos dominios, build 20261018T012954Z-c6e6d708. Archivos publicados comparados con los probados. Se comprobó en la app publicada una sesión iniciada sin conexión Drive, sin pulsar sincronización ni crear carpetas reales. Captura: tmp/datos-conexion-publicado.png.
