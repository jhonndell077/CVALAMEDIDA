# GitHub y Firebase — CVALAMEDIDA

Repositorio privado: https://github.com/jhonndell077/CVALAMEDIDA

## Desde el móvil

Inicia sesión en GitHub, abre el repositorio y edita el archivo que quieras. Guarda el cambio con un commit en `main`. También puedes usar un cliente Git móvil para hacer `git push origin main`.

Cada push normal a `main` ejecuta **Actions → Deploy CVALAMEDIDA**: verifica el frontend y pruebas locales del backend, y publica todas las funciones y los dos sitios Hosting. Si una prueba falla, no publica. Puedes ver el resultado en Actions. Pushes a otras ramas no publican producción.

## Deploy directo desde este equipo

Conserva los comandos Firebase existentes, pero para sincronizar también GitHub usa `./Deploy.ps1` desde la carpeta del proyecto, o el botón del banco. El script comprueba que `main` incluya todos los cambios de GitHub, registra un commit, publica `functions,hosting` y luego hace push. Si hay cambios nuevos del móvil, se detiene antes de publicar: integra primero con `git pull` y resuelve cualquier conflicto.

El commit del deploy local contiene `[skip ci]`. GitHub lo guarda sin volver a desplegar, evitando un ciclo infinito. Un comando Firebase escrito directamente en la terminal puede publicar, pero no puede inferir ni subir cambios a GitHub: usa el script o el banco para la sincronización de ida y vuelta.

## Datos privados y autenticación

`data/`, documentos, fotos privadas, temporales y credenciales quedan fuera del repositorio. La configuración inicial necesaria se restaura en el runner desde el secreto cifrado `CV_BOOTSTRAP_DATA`. La fotografía blanca de tests se borra antes de desplegar.

GitHub se autentica por OIDC sin claves privadas descargables. La identidad solo acepta el ID de este repositorio, su propietario, la rama `main` y eventos push o ejecución manual. La cuenta de despliegue tiene permisos de publicación y puede actuar como las cuentas de ejecución existentes. No se crearon claves JSON. Las acciones están fijadas a commits concretos.

El historial Git anterior sigue conservado en la rama local previa; GitHub comienza con una instantánea limpia que excluye antiguos temporales privados. No hagas `git push --all` de las ramas locales antiguas.
