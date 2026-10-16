# CV a la medida

## Verificación y operación desde la auditoría de octubre de 2026

Antes de publicar, ejecuta `venv/Scripts/python.exe scripts/verify_release.py` (o el Python preparado con `requirements.txt` y `requirements-dev.txt`). El gate ejecuta todas las pruebas Python y JavaScript con datos de arranque copiados a un directorio descartable y red bloqueada; exige cobertura Python de al menos 80 %. `Deploy.ps1` y GitHub Actions usan este mismo gate. Las dependencias directas verificadas están fijadas en `requirements.txt`; los rangos anteriores se conservan en `requirements.in`.

Las postulaciones Gmail reservan un intento por UID e identificador mediante una escritura atómica de GCS. Un resultado incierto requiere conciliación y no se reenvía automáticamente. Los trabajos web y las operaciones directas comparten diez cupos pendientes por cuenta; esto no representa una cuota mensual ni un límite financiero. El historial permite continuar con `cursor`/`next_cursor`.

`/api/health` distingue modelo configurado de disponibilidad verificada. Los permisos Google se comprueban mediante `/api/google/grant`; sin `gmail.send` no se habilita envío. Un borrador no acredita un archivo archivado. Consulta [privacidad y permisos](static/privacy.html).

La política de GCS conserva trabajos temporales web/Telegram 30 días y artefactos temporales dos días, con soft delete de siete días. Los registros de cuenta, vinculación, claves y reservas Gmail deben quedar fuera del borrado general de `jobs/`. No reviertas a lectores anteriores de metadatos sin preservar soporte de identidades `v2:` y las reservas de envío.


Aplicación web para analizar una vacante contra el banco profesional de cada
cuenta y generar un CV en PDF o Word. Conserva el banco original del propietario
como cuenta heredada y permite configurar bancos independientes. Mantiene Ollama como
opción local y añade un despliegue administrado con Firebase Hosting, Firebase
Cloud Functions y Gemini en Vertex AI.

## Modo local

Requiere Python 3.10 o posterior, Ollama en `127.0.0.1:11434` y un modelo
instruct instalado. Para procesar anuncios escaneados o imágenes, se necesita
un modelo local con visión.

Desde PowerShell, en esta carpeta:

```powershell
C:\python314\python.exe -m pip install -r requirements.txt
C:\python314\python.exe app.py
```

Abre `http://127.0.0.1:8765`. En local, el análisis usa Ollama. Al exportar,
el CV final se envía a Google Drive con tu autorización.

## Modo Firebase y Vertex AI

El proyecto Firebase dedicado es `cv-a-la-medida-jhonn`. La app usa:

- Firebase Hosting para servir la interfaz.
- Cloud Functions de segunda generación, Python 3.13, para el backend.
- Firebase Authentication con Google y correo verificado. `CV_MULTI_ACCOUNT=1`
  activa cuentas independientes; cada cuenta debe conectar su propio Drive.
  Con `CV_MULTI_ACCOUNT=0`, `CV_ALLOWED_EMAILS` limita los correos autorizados.
- Gemini 3.8 Flash mediante Vertex AI. La cuenta de servicio de la función
  necesita el rol `Vertex AI User` (`roles/aiplatform.user`).

La función no guarda el anuncio completo. Las postulaciones se registran en CV GENERADOS de Drive con puesto, destinatario, canal, fecha y enlace privado del CV. El listado muestra los 100 eventos más recientes. Google solicita los permisos drive.readonly, drive.file y gmail.send juntos al iniciar sesión o sincronizar. Se reutiliza la misma autorización para ambos servicios, sin forzar prompt=consent. Si los tokens caducan o se recarga la página, la sincronización obtiene una autorización nueva con la cuenta iniciada y reutiliza los permisos ya concedidos; el backend verifica la cuenta, genera y archiva el PDF, y envía un mensaje MIME con el destinatario revisado, el puesto como asunto, el mensaje y el PDF adjunto. Solo registra `gmail_accepted` cuando Google devuelve un identificador de mensaje (aceptación por Gmail, no garantía de entrega al destinatario). Usa un identificador por intento y un registro previo en Drive para evitar repetir envíos confirmados o inciertos; la función mantiene `max_instances=1` y `concurrency=1`. Un fallo de actualización del historial después del envío se muestra como advertencia sin reenviar el correo. WhatsApp abre el chat con texto preparado y requiere adjuntar el PDF y completar el envío; su estado enviado es una confirmación del usuario. Los tokens de Gmail y Drive se guardan solo en memoria, nunca en almacenamiento del navegador. El análisis envía a Vertex AI el
texto de la vacante y evidencias laborales relevantes; los datos de contacto no
se incluyen en ese prompt. El paquete conserva el banco original del propietario para compatibilidad.
En modo multicuenta cada solicitud o tarea usa un perfil aislado, construido
con el banco de la cuenta autenticada, para crear el documento final.

Los PDF y DOCX se guardan en Google Drive, en la carpeta **CV GENERADOS**
(`13LPPV7i7FycIGAqjokJPKsfbt2h6Ahk9`), tanto en local como en Firebase.
La configuración heredada está en `data/archive_config.json`. En modo
multicuenta, **Conectar Google Drive** prepara Banco de Datos y CV Generados
en el Drive de la sesión autenticada; permite elegir carpetas existentes.
La carpeta indicada arriba corresponde únicamente a la cuenta heredada. Se solicita `drive.readonly` para leer documentos existentes y `drive.file` para los archivos creados o compartidos con la aplicación. El primer permiso permite leer todo Drive; el recorrido habitual usa la carpeta de banco configurada. El token dura aproximadamente una hora, permanece en memoria y debe
reconectarse al recargar o vencer. No se guardan credenciales permanentes.

Al exportar, el backend valida la cuenta y la capacidad de añadir archivos, sube
el documento y verifica su carpeta mediante una lectura posterior. Solo entonces
ofrece la descarga y el enlace **CV guardado en Drive**. Si Drive falla, muestra
el error y no informa un guardado exitoso. Los CV exportados no alimentan el banco.
Para recuperar el comportamiento anterior de archivo local/Cloud Storage, define
`CV_ARCHIVE_PROVIDER=legacy`.

Antes del primer despliegue:

1. Vincula una cuenta de facturación al proyecto para habilitar Firebase
   Functions y Vertex AI. El consumo de Gemini y de los servicios de nube puede
   generar cargos según el uso.
2. En Firebase Console, habilita el proveedor **Google** en Authentication.
3. En Google Cloud Console, habilita la API de Vertex AI y concede
   `roles/aiplatform.user` a la cuenta de servicio de ejecución de la función.
4. Habilita Google Drive API y Google Picker API (ya habilitadas).
5. La autorización de Drive se abre en `cv-a-la-medida-jhonn.firebaseapp.com`,
   el origen ya permitido en el cliente OAuth de Firebase. La ventana devuelve
   el token únicamente a los orígenes de la aplicación y a localhost:8765,
   comprobando origen, ventana y nonce. No requiere añadir orígenes OAuth.
   Si el consentimiento está en pruebas, incluye la cuenta autorizada como
   usuario de prueba.
6. Desde PowerShell, en esta carpeta, despliega Hosting y todas las funciones declaradas en `main.py` (`api` y `telegram_worker` actualmente):

   ```powershell
   ./Deploy.ps1
   ```

   Este comando usa `firebase deploy --only functions,hosting --project cv-a-la-medida-jhonn`. No limita la publicación a `api`: Firebase descubre todas las funciones mediante el manifiesto generado en el predeploy. También publica los dos sitios Hosting configurados. El botón **Publicar · confirmar** del banco aplica este mismo alcance para CV A LA MEDIDA y muestra el comando antes de ejecutarlo.

La configuración del servidor para usar Gemini con endpoint `global`, la
lista de correo permitida y la autenticación están en `main.py`. No publiques
una función distinta que omita `verify_google_identity`.

## Flujo de uso

**Empleo inteligente (RD):** escribe un cargo y pulsa **Buscar vacantes**, o usa **Ver últimas publicadas** para ver las publicaciones de las cuatro fuentes de RD configuradas, ordenadas por fecha. La consulta general no necesita GPS ni sincronizar el banco de CV. Puedes abrir la oferta original y pulsar **Adaptar mi CV**; la ciudad y disponibilidad se revisan en la fuente. Las fuentes muestran su procedencia y sus fallos parciales; la ubicación sigue siendo opcional. Las fuentes globales dejaron de estar disponibles en la búsqueda activa. El agregador consulta Chiripas, TuEmpleoRD, RD Trabaja y TuVacanteRD, con caché de quince minutos por consulta, hasta 50 resultados por fuente y 200 en total. Aldaba y Computrabajo son enlaces externos; no abarca todos los portales de RD.

1. Inicia sesión con la cuenta de Google autorizada.
2. Pega una vacante o adjunta PDF, DOCX, TXT, PNG o JPG.
3. Revisa requisitos, brechas, evidencias y plantilla sugerida.
4. Genera la vista previa y descarga el CV en PDF o DOCX.

Se admiten adjuntos de hasta 10 MB y PDF de hasta 12 páginas; los PDF
escaneados admiten hasta 3 páginas de imagen. Los periodos laborales no constan
en el banco maestro y se advierten en el CV. Los datos personales, estudios,
cursos, referencias y fotografía se conservan desde
`data/master_profile.json`. La selección de experiencia, competencias y
proyectos se valida contra ese banco; al consolidar funciones, cada una
permanece atribuida a su empleador original.

## Progreso y trabajo en segundo plano

En la web alojada, la sincronización, el análisis, la vista previa del CV,
el guardado de información, las exportaciones y las postulaciones se envían
a una cola persistente del servidor. Tras guardar la solicitud, cerrar la
página no cancela el trabajo. Al volver con la misma cuenta y navegador,
la interfaz recupera los procesos y sus resultados sin ejecutarlos otra vez.
Las exportaciones guardadas pueden abrirse en Drive o descargarse desde
«Tus procesos»; la descarga al dispositivo requiere que la página esté abierta.

El indicador muestra de 1 a 100 según etapas completadas y, durante la
sincronización, archivos procesados. No utiliza temporizadores para simular
progreso. La IA no informa un porcentaje interno: el indicador permanece
en la etapa correspondiente hasta recibir su respuesta. «Continuar en
segundo plano» cierra el modal y mantiene el trabajo en el servidor.

«Activar notificaciones» solicita permiso y registra Web Push mediante un
service worker. El servidor avisa al completar un proceso al 100%; los fallos permanecen en el panel, incluso
sin una pestaña abierta, cuando el navegador y el dispositivo permiten push.
No se incluye contenido privado del banco en las notificaciones. La entrega
no condiciona la conservación del resultado. El navegador guarda únicamente
IDs de procesos; las credenciales temporales necesarias para Drive/Gmail se
cifran en el almacenamiento privado del servidor, caducan en una hora y se
retiran del proceso al completarlo o fallar. Los envíos externos cuyo resultado
se perdió no se repiten automáticamente.

Para reducir consultas repetidas, los archivos de Drive se reutilizan por
ID y huella de contenido (el índice siempre se vuelve a leer), las consultas
GET del perfil comparten una caché de 15 segundos, la fotografía solo se
convierte al cambiar y un banco sin cambios no vuelve a escribir su índice.
Los procesos que generan contenido consultan el inventario actualizado;
los documentos nuevos y modificados se leen antes del análisis.

## Lectura del banco de Drive

Con el proveedor Drive activo, la web sincroniza el banco y sus subcarpetas
antes de analizar cada vacante. Lee notas de texto, PDF, Word DOCX, imágenes,
hojas XLSX, presentaciones PPTX y archivos OpenDocument. Google Docs y
presentaciones nativas se exportan a PDF para conservar imágenes y texto.
Los archivos nuevos o modificados se procesan de uno en uno; los hechos de
archivos retirados dejan de utilizarse. Los formatos no admitidos, archivos
ilegibles o que superan los límites aparecen como pendientes de revisión.

Una nota como «Fui camarero en Farah Modern Kitchen» aporta el cargo y el
empleador aunque no detalle funciones ni fechas. Se complementa con las
funciones y fechas documentadas del mismo cargo y empleador. Por autorización
del usuario, Gemini genera hasta cuatro funciones habituales de cada puesto
cuando faltan funciones o son escasas; las guarda con origen
`generada_por_puesto` y el analizador puede seleccionarlas para el CV.
Las funciones documentadas tienen prioridad. No genera fechas, empleadores,
cifras, idiomas, herramientas específicas ni logros. Un empleador desconocido se muestra como «Empleador no
indicado». Documentos e imágenes dentro de proyectos se leen individualmente;
el código se agrupa como evidencia de proyectos. Los CV generados, dependencias
y archivos de credenciales se excluyen del banco profesional.

`data/master_profile.json` es el perfil local y heredado. En modo multicuenta,
el perfil activo se construye a partir del banco de Drive propio de cada cuenta. Incluye
datos de contacto, estudios, cursos, referencias, habilidades con sus fuentes,
experiencias con funciones identificadas y proyectos. La aplicación no permite
que el modelo invente registros: el análisis solo puede seleccionar los IDs ya
existentes en ese archivo y el servidor los vuelve a validar antes de redactar
o exportar.

Al crear un CV, la aplicación selecciona las funciones y habilidades relevantes,
conserva cada función junto a su empleador y aplica la plantilla recomendada
para gastronomía, administración, retail o perfil técnico. Esa selección se
mantiene igual en la vista previa, el PDF y el documento Word.
La fotografía `data/hoja_de_vida.jpeg` se utiliza de forma consistente en todos
los CV. El modelo recibe el catálogo de cursos y solo puede seleccionar cursos
documentados que sean pertinentes para la vacante; por ejemplo, excluye cursos
de alimentos en puestos de oficina, salvo que el anuncio los solicite.

En modo local, el panel **Mi árbol de información** permite explorar y editar
datos personales, experiencia y funciones, habilidades, estudios, cursos,
proyectos y referencias. **Guardar cambios** actualiza
`data/master_profile.json`, de modo que el perfil modificado se utiliza en
futuros CV. Las experiencias nuevas requieren un identificador único y al menos
una función. En Firebase el árbol es de solo lectura: el perfil se amplía
añadiendo documentos al banco de Drive.

El panel **Mapa de conocimiento profesional** permite registrar localmente
documentos históricos PDF, DOCX y TXT. Cada archivo se identifica por su nombre
local y SHA-256; las cargas sin cambios no se reprocesan y las modificaciones
añaden una revisión sin eliminar las anteriores. El mapa se almacena en
`data/knowledge_map.json`, separado del banco maestro. Los fragmentos extraídos
son evidencia pendiente de validación, pueden incluir referencias candidatas a
IDs ya conocidos y nunca se incorporan automáticamente a `master_profile.json`
ni al CV. Este mapa local sigue siendo independiente de la ingesta del banco
de Drive, que sí incorpora hechos legibles mediante Gemini.

## Pruebas

```powershell
C:\python314\python.exe -m unittest discover -s tests -v
node --check static\app.js
```

## Estado de publicación (7 de octubre de 2026)

Blaze está habilitado y el servidor Python está desplegado en Cloud Functions
de segunda generación. Los endpoints del perfil requieren la cuenta autorizada.
El banco de Drive es la fuente obligatoria del servidor: si falla su acceso,
no se usa el perfil local como sustituto. El banco
no se publica como archivo estático. La cuenta de ejecución es `cv-runtime`,
con permisos de Vertex AI y lectura de Firebase Authentication. Gemini respondió
a una solicitud real. El consentimiento y la carga real en Drive requieren
conectar Google Drive desde la aplicación.

En Windows, `generate_manifest.py` genera `functions.yaml` desde el SDK antes
del despliegue para evitar un fallo de lanzamiento de activate.bat de la CLI.
Las imágenes del servidor en Artifact Registry se eliminan después de 7 días;
esta política no afecta al banco ni a los CV de Drive. El consumo de Blaze
y Gemini se factura según el uso.

El `index.html` de la carpeta principal es un acceso a la web publicada. El
index real de la aplicación está en `static/index.html`; abrir ese archivo
directamente no inicia el backend.

## Banco de Datos en Drive

Carpeta: https://drive.google.com/drive/folders/1eu2R3UR_7U6c3iNUD4oLNdCfDGjR-48d

Migrados `perfil_base.json`, fotografía y los tres CV originales. `LEEME.txt`
describe la lógica y `indice_banco.json` conserva el estado, huellas, hechos
extraídos y origen por archivo. `data/bank_config.json` fija carpeta e IDs.
El índice se actualiza en su archivo existente, propiedad del usuario.

`main.py` activa `CV_BANK_PROVIDER=drive`. `drive_bank.py` recorre la carpeta y
subcarpetas, compara huellas, lee imágenes/PDF con Gemini y Word/texto/Excel
con sus lectores. También exporta documentos nativos de Docs/Sheets/Slides.
Límites: 20 MB, 40 páginas PDF, 120 000 caracteres y 1000 archivos en el inventario.
No sigue accesos directos externos. Formatos incompatibles quedan para revisión.

Al iniciar sesión, antes de analizar y con «Sincronizar banco», la interfaz
solicita procesar un documento por petición hasta terminar. Los duplicados
se combinan; cada hecho conserva su archivo de origen. Al retirar o cambiar
un archivo se excluyen sus hechos anteriores. Los datos del perfil inicial
se corrigen en `perfil_base.json`; no desaparecen al retirar un CV original.
Los datos ambiguos o de otro titular generan avisos. No se inventan hechos.

El servidor `cv-runtime` obtiene credenciales temporales de `cv-bank` mediante
IAM Credentials, sin claves privadas. Solo se le concede Token Creator sobre
esa cuenta. Para activar la lectura y escritura del índice debe compartirse
la carpeta como Editor con `cv-bank@cv-a-la-medida-jhonn.iam.gserviceaccount.com`.
No se añaden permisos al resto de Drive. El despliegue usa una instancia y una
petición concurrente para evitar escrituras simultáneas sobre el índice.

Verificación: 37 pruebas unitarias y una lectura real de certificado ficticio
en imagen con Vertex AI (no añadido al banco real). Hosting y API publicados
con el nuevo destino. El usuario autorizó y se aplicó el acceso Editor de
`cv-bank` a la carpeta. Los tres CV originales se leyeron con Gemini usando
la identidad `cv-runtime`; la escritura y relectura del índice, el perfil
validado y la fotografía se verificaron contra Drive. No quedan documentos
pendientes. Los avisos de fechas o titulaciones ausentes se conservan en el
índice para revisión. El permiso temporal de diagnóstico se retiró al terminar.

## Corrección del análisis de vacantes con Vertex AI

La solicitud original con `analysis_output_schema()` produjo un error real
400 INVALID_ARGUMENT al analizar una imagen JPEG de prueba. El mismo análisis
se completó después de simplificar el esquema con `vertex_response_schema()`.
Se conservan estructura, campos obligatorios y clasificaciones pequeñas; se
retiran restricciones de texto y enumeraciones extensas de IDs del banco.
Los IDs disponibles siguen en el contexto del modelo y `sanitize_analysis()`
valida las selecciones contra el perfil. Ollama conserva su esquema original.
Validación: 38 pruebas y análisis real de una imagen de vacante con Gemini.

## Conectar el guardado al sincronizar

El inicio de sesión de Google solicita `drive.file` y reutiliza el permiso
devuelto para comprobar CV GENERADOS. «Sincronizar banco y conectar Drive»
abre la autorización desde el clic, comprueba el destino y después sincroniza.
La exportación también solicita reconectar cuando no hay token vigente, antes
de generar, guardar y descargar PDF/Word. El token permanece en memoria.
La primera autorización puede requerir seleccionar CV GENERADOS en Picker.
Validado con `node tests/drive-flow.test.cjs` y comprobación de sintaxis de JS.

El selector usa una clave exclusiva `CV - Google Drive Picker`, restringida a
`picker.googleapis.com` y `drive.googleapis.com`, con los dominios de la aplicación,
`https://docs.google.com/*` y los dos orígenes locales del puerto 8765.
La clave automática de Firebase excluía Picker y causaba «The API developer key
is invalid»; conserva sus restricciones originales y se usa solo para Firebase.

## Reemplazar la fotografía

La versión en Drive busca `hoja_de_vida.jpeg` por nombre directamente dentro
de Banco de Datos, en lugar de conservar el ID del archivo original. Puedes
eliminar la anterior y subir otra con el mismo nombre: se lee de nuevo al
sincronizar, previsualizar o exportar. JPEG o PNG se detectan por su contenido;
el servidor convierte la foto a JPEG para los documentos. Debe haber una sola
imagen con ese nombre. Ausencias, duplicados e imágenes dañadas generan avisos
con instrucciones para resolverlos. Las fotos de subcarpetas no sustituyen la
foto principal. El perfil base y el índice siguen identificándose por su ID.
Validación: 42 pruebas, incluido el reemplazo con un ID nuevo.

## Indicador de espera

`static/loading.js` gestiona una ventana flotante compartida para cargas y
operaciones: «Analizando», «Generando Hoja de vida», sincronización, conexión
a Drive, guardado y exportación. Durante la espera bloquea los controles del
fondo y conserva la operación principal si hay tareas anidadas. Al terminar
o fallar restaura los controles y el foco. Respeta el movimiento reducido y
anuncia el estado a lectores de pantalla. Las pruebas de JavaScript cubren
concurrencia, fallos y restauración del estado (`node tests/loading.test.cjs`).

Las llamadas a Vertex usan el endpoint global y `vertex_retry.py`: hasta tres intentos para errores 429 o 503, con esperas crecientes de 2 y 4 segundos más una variación aleatoria. Cada intento tiene un límite de 45 segundos y los reintentos internos del SDK se desactivan para no multiplicar solicitudes. Los errores 400, 401 y 403 no se reintentan. Si persiste la saturación, la API devuelve 503 con una explicación en español y la interfaz conserva la vacante. Esto mejora los fallos temporales; no aumenta las cuotas ni garantiza capacidad reservada.

## Aviso de actualización

Cada despliegue de Firebase Hosting ejecuta `python generate_version.py` y publica
un identificador nuevo en el HTML y en `static/version.json`. La app compara la
versión cargada en cada pestaña al abrir, cada minuto, al recuperar el foco y al
volver a estar en línea. Si hay cambios muestra «Nueva actualización disponible»
con el botón Actualizar. La recarga requiere pulsar ese botón y no se ejecuta
mientras haya una operación de carga activa. Los datos no guardados en la página
se pierden al recargar. Las visitas posteriores desde ese navegador también
avisan si cambió la versión desde la última actualización aceptada. La primera
visita no muestra un aviso falso. El almacenamiento local guarda solo la versión,
sin credenciales ni información del banco. Los errores de red no interrumpen la app.

## Bot privado de Telegram

`telegram_bot.py` acepta chats privados y valida su propietario. En modo
multicuenta cada usuario vincula y confirma su propio Telegram; el modo heredado
conserva el ID configurado. `job_runtime.py` proporciona almacenamiento
persistente y envío de tareas tanto para la web como para Telegram. El webhook valida el secreto de Telegram y coloca cada mensaje
en Cloud Tasks con un ID estable. `telegram_worker` genera el CV sin bloquear el
webhook ni la app. Los trabajos se guardan en un bucket privado con escritura
condicional por generación; los archivos temporales expiran a los dos días y los
registros de trabajo a los treinta. Al terminar se elimina el mensaje original y
el PDF temporal; el PDF definitivo queda en CV GENERADOS y se entrega al propietario.

La configuración `cv-telegram-config` está en Secret Manager y contiene el token
BotFather, ID propietario, secreto del webhook y autorización OAuth de Drive.
No se publica en Hosting. El servidor usa el mismo cliente Google de la app.
En el panel Telegram se autoriza Drive mediante el modelo de código de Google;
solo se solicita `drive.file`, `openid` y `email`. Se valida el correo propietario
y el acceso a la carpeta antes de activar el guardado en segundo plano. No usa el
token temporal del navegador para generar CV desde Telegram. Google puede exigir
renovar una autorización revocada o caducada.

Formatos: texto, JPG/PNG/WebP, PDF, DOCX y TXT; máximo 10 MB por adjunto y los límites
de lectura de la app. Cada mensaje produce un CV. Si hay documentos nuevos
pendientes en Banco de Datos, el bot pide sincronizarlos en la app antes de continuar.
Los comandos `/start`, `/ayuda` y `/estado` explican el uso y la conexión. Nunca
postula al empleador sin que el propietario pulse el botón de envío. Un envío con respuesta incierta de Telegram
no se repite automáticamente; el enlace de Drive permite recuperar el documento.

### Postular desde el CV de Telegram

Los nuevos PDF incluyen botones de Gmail y WhatsApp con los contactos detectados
en la vacante. Si no hay contacto, el botón informa que falta; no inventa datos.
Gmail pone el título de la vacante como asunto, redacta la postulación y adjunta
el PDF exacto guardado en Drive. El propietario autoriza cada envío pulsando el
botón. Requiere que la autorización renovable ya concedida incluya `gmail.send`;
si falta, Google exige autorizar Gmail con la cuenta propietaria en la app.

Los clics llegan como `callback_query`, se validan contra el chat privado y se
procesan en la cola. El destinatario se obtiene del trabajo original, no del
contenido libre del callback. Una reserva persistente por CV y destinatario
previene duplicados, incluso cuando la respuesta de Gmail es incierta. Los
registros de envío se guardan en CV GENERADOS con el mismo formato del historial
web. Los trabajos y botones dependen de la retención de trabajos de 30 días.

WhatsApp abre `wa.me` con el número y el texto de postulación ya preparados.
El propietario debe adjuntar el PDF recibido en Telegram y pulsar Enviar en
WhatsApp; no se presenta como envío automático ni se confirma falsamente en el
historial. No se hace público el PDF de Drive. Para envío real por API de WhatsApp
haría falta configurar WhatsApp Business Platform por separado.


## Estructura del backend

| Archivo | Responsabilidad |
| --- | --- |
| `main.py` | Entradas de Firebase y configuración del entorno alojado. |
| `app.py` | Núcleo Flask, proveedores de IA, lectura y validación del banco e integraciones. |
| `profile_routes.py` | Rutas de cuentas, registro inicial, perfil y banco profesional. |
| `resume_routes.py` | Rutas de análisis, vista previa, exportación y postulaciones. |
| `cv_analysis.py` | Selección validada de información, plantillas y borrador del CV. |
| `cv_documents.py` | Generación de PDF y Word con el diseño existente. |
| `account_context.py` | Estado del banco aislado por solicitud o tarea mediante ContextVar. |
| `user_accounts.py` | Propiedad, preparación de carpetas y ciclo de vida del contexto de cuenta. |
| `job_runtime.py` | Almacenamiento privado, escritura condicional y despacho autenticado de tareas. |
| `background_jobs.py`, `analysis_jobs.py` | Procesamiento y recuperación de operaciones web. |
| `telegram_bot.py`, `telegram_accounts.py` | Mensajes, vinculación y operaciones de Telegram. |

Los servicios reciben el núcleo explícitamente. Las funciones públicas de
`app.py` mantienen sus firmas y las rutas HTTP conservan sus métodos, respuestas
y autenticación. Los valores de banco/perfil se resuelven desde el contexto
actual; una cuenta ya no sustituye los valores globales de otra ni necesita
mantener un bloqueo durante toda la solicitud. Al terminar o fallar una operación
se restaura el contexto anterior. Los límites actuales de instancias y
concurrencia de Firebase se conservan.

## Pruebas

Desde esta carpeta, con las dependencias de Python instaladas:

```powershell
python -m unittest discover -s tests -p "test_*.py"
npm ci --prefix tests
npm --prefix tests test
```

`tests/package.json` y `tests/package-lock.json` fijan las dependencias de las pruebas de
interfaz; no se requieren para servir la aplicación ni se despliegan en Firebase.
Se mantienen dentro de `tests/` para que Firebase identifique la raíz como un
backend de Python y no como una función de Node.js.
Las pruebas cubren documentos, análisis, autorización, propiedad de procesos,
dos cuentas simultáneas, restauración de contextos, registro inicial, vista
previa sin guardar, Drive, Gmail, Telegram y recuperación de procesos.

## Postulación automática

En la web, **Crear y enviar mi CV** prepara la vista previa y envía el mensaje
con el PDF adjunto al primer correo detectado en la vacante. No hay botón
«Enviar por Gmail». Telegram entrega el PDF en el chat y después ejecuta el
mismo envío al primer correo de postulación detectado. Ambos canales conservan
la autorización de la cuenta, el archivo en Drive y el registro de Gmail;
los envíos confirmados o inciertos no se repiten automáticamente. Si falta
correo o autorización, se informa el motivo. WhatsApp conserva su flujo actual.

## GitHub y publicación automática

Repositorio privado: https://github.com/jhonndell077/CVALAMEDIDA. Un push a main activa pruebas y publica todas las funciones y Hosting. El Deploy local directo se conserva: ./Deploy.ps1 publica y luego sincroniza GitHub sin repetir CI. Consulta GITHUB-Y-DEPLOY.md para cambios desde el móvil, datos privados y errores de sincronización.

## Piloto y controles de operación (2026-10-16)

El piloto tiene como objetivo diez sesiones simultáneas. Los trabajos pesados se
procesan en cola; esta cifra no promete diez análisis de IA simultáneos.

La admisión durable aplica por cuenta tanto a operaciones web directas/en cola
como al bot y sus botones Gmail. `CV_DAILY_JOB_LIMIT` y `CV_MONTHLY_JOB_LIMIT`
permiten ajustar la política: sus valores iniciales son 10 procesos nuevos por
día UTC y 50 por mes UTC, además de diez pendientes. Cero cierra admisiones
nuevas; los trabajos ya admitidos y las consultas de resultados siguen disponibles.
Los reintentos con el mismo identificador conservan su admisión. Las continuaciones
del worker no consumen otra unidad. Los rechazos por periodo devuelven HTTP 429,
`code=period_quota_exceeded` y `Retry-After`. Los contadores comienzan a registrar
admisiones con esta versión; no reconstruyen el consumo anterior a su activación.

Presupuesto objetivo autorizado: **US$5/mes**. Se configuraron presupuesto por
proyecto y spend caps para Vertex (US$3), Cloud Run (US$1) y Functions (US$0,50).
El corte puede pausar nuevas solicitudes y los importes están sujetos a demora
de medición; otros servicios siguen acumulando gastos. No es una garantía de
factura total exacta. No se elevó el máximo de instancias para esta fase.

`requirements.in` y `requirements-dev.in` contienen las dependencias directas
fijadas; los `.txt` son locks transitivos universales con hashes. Instalar por
separado con `python -m pip install --require-hashes -r requirements.txt` y el
equivalente para `requirements-dev.txt`. Regenerar con `uv pip compile` usando
`--universal --python-version 3.13 --generate-hashes`. El gate comprueba su
coherencia; CI y `Deploy.ps1` también revisan avisos conocidos con pip-audit.

El [plan de reestructuración](docs/PLAN-REESTRUCTURACION.md) conserva las etapas y
sus criterios de aceptación. La aprobación Google externa, una segunda cuenta
real controlada y la recepción Push en dispositivos no se acreditan con fixtures.
