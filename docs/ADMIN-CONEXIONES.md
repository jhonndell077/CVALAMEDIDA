# Vista de conexiones del administrador

URL: https://cvalamedida.web.app/admin/conexiones (también en el segundo dominio configurado).

Iniciar sesión mediante el botón Google con la cuenta propietaria original del proyecto. No solicita permisos de Drive ni Gmail. La página sirve una interfaz estática; los datos actuales se obtienen de `/api/admin/connections`, que verifica el token de Firebase con revocación y exige el correo propietario en el servidor. Una cuenta distinta recibe 403; sin sesión, 401. Si no existe propietario configurado, el acceso se rechaza.

La página consulta cada 60 segundos mientras está visible. La API acredita únicamente que atendió la solicitud y validó al administrador; el navegador comprueba además el HTTP de la portada. La verificación no invoca modelos ni envía mensajes. Son solicitudes reales al backend y pueden generar consumo de infraestructura. No se modifican controles presupuestarios.

Drive, Vertex, Tasks, Storage, worker, Telegram, Gmail y Push conservan la etiqueta «sin verificar»; las relaciones dibujadas describen la arquitectura auditada, no tráfico observado. El presupuesto y las revisiones que figuran en el diagrama son evidencia histórica fechada. Esta entrega publica el monitor existente y no añade observabilidad autenticada de todas las integraciones.

Cerrar sesión limpia la vista; respuestas de una sesión anterior no pueden restaurarla. No se conserva un estado verde cuando vence la lectura. La identidad y los tokens nunca se incluyen en respuestas de diagnóstico ni se guardan en archivos propios del monitor. Firebase gestiona la sesión en el dispositivo.

Pruebas: 365 backend con red bloqueada y 80,68 % de cobertura; 161 JavaScript. Incluyen rechazo de usuarios, ausencia de configuración del propietario, no lectura del banco para administrar, respuestas tardías y cierre de sesión. El acceso interactivo desde un móvil requiere que su titular complete Google; no se han usado cuentas ajenas.

Reversión: código anterior `13176a7f8bbd4b31e74abbf0478a8ccf76705524`; conservar configuración y evidencias del despliegue. Para revertir la función o Hosting, seleccionar la revisión/versión anterior compatible o desplegar el código anterior mediante el procedimiento habitual. No eliminar usuarios ni datos para revertir esta vista.

Publicación confirmada: página y recursos HTTP 200; diagnóstico sin sesión HTTP 401. En el navegador integrado, la sesión propietaria ya existente fue aceptada y mostró web/API disponibles. No se extrajeron tokens ni se hizo un nuevo inicio de sesión. Firebase confirmó la publicación de `api` y ambos Hosting. Evidencia local: `tmp/admin-connections-verification/published-checks.json` y `tmp/admin-connections-deploy.txt`.
