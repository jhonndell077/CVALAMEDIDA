# Acciones administrativas por usuario

Tres controles en Configuración: Reiniciar, Eliminar datos y Eliminar usuario. La interfaz solicita una vista previa y exige escribir el UID exacto antes de una ejecución. Los planes duran dos minutos, están vinculados al administrador, usuario y acción y sólo pueden utilizarse una vez. El backend valida identidad administrativa, origen, estado y versión de la cola.

## Alcance real

- Reiniciar pone a cero los contadores diario y mensual. Conserva límites, datos, trabajos pendientes y recibos de idempotencia. No cancela trabajos ni elimina documentos.
- Eliminar usuario elimina el UID de Firebase Authentication, revoca sesiones y la vinculación Telegram, y bloquea nuevas admisiones para ese UID. Es el equivalente a eliminar la identidad en Firebase, no un borrado de todos sus datos. Drive y los registros internos se conservan y la vista previa lo indica. La cuenta administrativa está protegida; los trabajos activos bloquean la eliminación.
- Eliminar datos muestra los requisitos pendientes y bloquea el borrado integral. El repositorio no ofrece un inventario exhaustivo de archivos exclusivos de la app: las carpetas de Drive son seleccionables por cada usuario, los CV existentes carecen de una marca de propiedad de aplicación y no existe una barrera de escrituras que cubra todas las operaciones ya iniciadas. Eliminar sólo el registro local dejaría datos externos y puede reactivar el banco heredado. No se simula éxito ni se borran carpetas potencialmente mixtas.

Los correos enviados y archivos/mensajes entregados por Telegram no desaparecen por eliminar el UID. La implementación no intenta borrarlos.

## Requisitos pendientes para eliminar todos los datos

Se necesita un inventario verificable por UID de archivos propios, autorización Drive del propietario, bloqueo persistente de escrituras de toda la cuenta y limpieza reanudable con evidencia de cada etapa. Sin ello no se habilita la acción integral. No se amplían permisos IAM ni se leen credenciales para esta revisión. La cuenta de ejecución necesita permisos Firebase Authentication para revocar sesiones y eliminar usuarios; un error de permisos se informa sin afirmar eliminación.

## Fallos y pruebas

La eliminación entre Storage y Authentication no es una transacción: un error puede dejar revocaciones o bloqueo de admisión aplicados. Se informa como resultado parcial, permite consultar otra vez y no se afirma que todo se completó. Los planes expirados no pueden ejecutarse aunque sus objetos sigan en el bucket privado; no se cambia la política de ciclo de vida del bucket.

Pruebas únicamente con identidades, colas y proveedores simulados. No se reinician ni eliminan cuentas o datos reales durante la verificación.

Verificador `scripts/verify_release.py --output tmp/admin-actions-final`: 455 pruebas Python y 234 JavaScript aprobadas; cobertura Python 81,83 %. Revisión especializada final sin bloqueantes dentro del alcance descrito. El borrado integral de datos permanece expresamente pendiente.
