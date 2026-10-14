# GitHub y Firebase — CVALAMEDIDA

Repositorio privado: https://github.com/jhonndell077/CVALAMEDIDA

## Desde el móvil

Inicia sesión en GitHub, abre el repositorio y edita el archivo que quieras. Guarda el cambio con un commit en `main`. También puedes usar un cliente Git móvil para hacer `git push origin main`.

El workflow está preparado para verificar el frontend y pruebas locales del backend, y publicar todas las funciones y los dos sitios Hosting desde el runner de este PC. Actualmente está desactivado: GitHub bloquea el inicio de los trabajos por facturación, incluso cuando el runner propio aparece conectado. Por ahora un push no publica automáticamente.

## Deploy directo desde este equipo

Conserva los comandos Firebase existentes, pero para sincronizar también GitHub usa `./Deploy.ps1` desde la carpeta del proyecto, o el botón del banco. El script comprueba que `main` incluya todos los cambios de GitHub, registra un commit, publica `functions,hosting` y luego hace push. Si hay cambios nuevos del móvil, se detiene antes de publicar: integra primero con `git pull` y resuelve cualquier conflicto.

El commit del deploy local contiene `[skip ci]`. GitHub lo guarda sin volver a desplegar, evitando un ciclo infinito. Un comando Firebase escrito directamente en la terminal puede publicar, pero no puede inferir ni subir cambios a GitHub: usa el script o el banco para la sincronización de ida y vuelta.

## Datos privados y autenticación

`data/`, documentos, fotos privadas, temporales y credenciales quedan fuera del repositorio. La configuración inicial necesaria se restaura en el runner desde el secreto cifrado `CV_BOOTSTRAP_DATA`. La fotografía blanca de tests se borra antes de desplegar.

GitHub se autentica por OIDC sin claves privadas descargables. La identidad solo acepta el ID de este repositorio, su propietario, la rama `main` y eventos push o ejecución manual. La cuenta de despliegue tiene permisos de publicación y puede actuar como las cuentas de ejecución existentes. No se crearon claves JSON. Las acciones están fijadas a commits concretos.

El historial Git anterior sigue conservado en la rama local previa; GitHub comienza con una instantánea limpia que excluye antiguos temporales privados. No hagas `git push --all` de las ramas locales antiguas.

## Runner en este PC

El runner privado `CVALAMEDIDA-PC`, con etiqueta `cvalamedida`, está instalado y conectado. Se inicia al iniciar sesión en Windows. El PC necesita estar encendido, conectado y con la sesión del usuario abierta. Reutiliza Python, Node y Firebase instalados; no instala dependencias globales. Su checkout está separado del proyecto de trabajo y la configuración privada del job se elimina al terminar. La conexión del runner no elimina el bloqueo de facturación de la cuenta.

Se preparó un ejecutor local alternativo en la carpeta de trabajo de este chat, pero no está activo ni validado mediante un despliegue: la revisión automática de permisos rechazó configurar su arranque persistente. El Deploy directo mediante `Deploy.ps1` y el banco sigue siendo la vía disponible; conserva la sincronización con GitHub. El script incluye un bloqueo Windows para impedir dos ejecuciones simultáneas del script.
