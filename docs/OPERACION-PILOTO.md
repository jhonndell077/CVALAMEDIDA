# Operación del piloto de CV A LA MEDIDA

Objetivo confirmado: diez usuarios simultáneos y US$20 mensuales. El procesamiento
pesado utiliza cola; las pruebas de concurrencia locales no certifican el tiempo
de espera de diez trabajos reales en Google Cloud.

Estado de cierre actualizado: 515 pruebas locales aprobadas. El primer despliegue
falló el arranque; después del cambio autorizado a US$20, el reintento terminó
correctamente. Las últimas revisiones listas son `api-00097-xeq` y
`telegram-worker-00070-cig`, ambas Functions `ACTIVE`. Los caps quedaron
`CONFIGURED`. No se presenta la correlación temporal como una causa raíz probada
del primer fallo ni como una prueba de todas las integraciones reales.

## Límites y síntomas

- Diez procesos nuevos al día UTC y cincuenta al mes UTC por cuenta; diez
  pendientes como máximo. Una solicitud directa cuenta como un proceso.
- Un mismo identificador durable no consume otra unidad por sus reintentos.
  Terminar un proceso libera pendiente, pero no devuelve consumo diario/mensual.
- HTTP 429 con `period_quota_exceeded` incluye `Retry-After`. El usuario puede
  consultar resultados existentes. No se borran contadores para permitir reenvíos.
- Si se alcanza un spend cap, Google puede detener nuevas solicitudes a ese
  servicio. No levantar el cap automáticamente ni desactivar facturación para
  sortearlo. Revisar gasto y presupuesto primero; conservar acceso al historial
  cuando los servicios correspondientes sigan disponibles.
- `delivery_started` con lease vigente representa actividad. No se reenvía Gmail
  ni Telegram solo por observar ese estado. Una confirmación incierta requiere
  conciliación; no se elimina la reserva para forzar un segundo envío.

## Presupuestos configurados

Presupuesto de proyecto: US$20. Caps independientes: Vertex US$15, Cloud Run US$2,
Functions US$1. El presupuesto global anterior de la cuenta de facturación se
conservó. No se cambiaron permisos IAM. Destinatarios administrativos comprobados
como la cuenta propietaria antes de crear las nuevas alertas.

Los servicios no cubiertos, gastos fijos y solicitudes en curso pueden facturarse.
La demora de enforcement también puede causar exceso. El margen orientativo de
US$2 para otros servicios no es un corte. Un mes de uso y sus costes reales
deben medirse antes de aumentar carga o cuotas.

## Banco documental y revisión humana

Los cuatro avisos del último sync real no se ocultaron. Abrir cada documento
referenciado en el banco y contrastar nombre completo, fechas y procedencia. Si
una edición o exclusión antigua coincide con varios registros, seleccionar el
registro preciso en la interfaz actual y conservar evidencia de la decisión.
No borrar documentos, modificar fechas por inferencia ni aprobar tareas sugeridas
por IA como si estuvieran documentadas.

## Recuperación

Los backups privados se encuentran en el prefijo ya documentado en la auditoría.
No incluyen autorización para reemplazar masivamente el banco actual. Antes de
restaurar, inventariar origen, versión, destino y versión actual; conservar cambios
posteriores y usar precondiciones de generación o ETag según almacenamiento.

El ensayo del 16 de octubre restauró una configuración de cuenta respaldada hacia
un prefijo aislado: misma huella y tamaño; un segundo restore con generación
antigua fue rechazado con 412 y conservó el cambio posterior. Solo se eliminó el
objeto exacto creado para la prueba. No acredita un restore de todos los tipos de
datos, la recuperación total de un proyecto ni los tiempos RTO/RPO de un desastre.

Mantener fuera del lifecycle temporal las cuentas, vínculos, claves, suscripciones
y reservas Gmail. La compatibilidad con identidades `v2:` debe conservarse al
revertir código; no reactivar la antigua regla general que borraba `jobs/`.

## Solicitudes de eliminación por cuenta

La eliminación administrativa requiere identificar y verificar al titular y el
UID; suspender nuevas admisiones; conciliar trabajos y envíos inciertos; preparar
un inventario revisable de registros exclusivamente suyos y una copia privada si
corresponde conservarla. Definir por escrito qué se elimina y qué se retiene por
integridad, recuperación o solicitudes del titular.

Separar Drive del almacenamiento aplicativo: los archivos del Drive pertenecen al
usuario, y borrar su cuenta Firebase no borra esos documentos. Revocar únicamente
su autorización Google y su vínculo Telegram; retirar sus suscripciones Push con
actualizaciones condicionales. Las claves compartidas, presupuestos, bucket,
proyecto y datos de otras cuentas se excluyen de la operación. No se implementó
un borrado masivo ni una garantía de eliminación automática por cuenta en esta fase.

## Publicación y revisión de dependencias

Instalar runtime y herramientas desde sus locks con hashes. `scripts/verify_release.py`
comprueba coherencia de locks, sintaxis, frontend, backend aislado y cobertura.
`pip-audit` es una revisión adicional de avisos conocidos, no un análisis de todas
las rutas explotables. Los flujos local y CI bloquean publicación si falla.

Pillow 12.3.0 sustituye 11.3.0. La resolución universal fija las transitivas para
Python 3.13 o posterior y se probó en un entorno limpio Python 3.13.14 Windows;
el despliegue Linux conserva la comprobación final de build. No se afirma una
matriz de todos los sistemas operativos y versiones de Python.

## Condiciones externas para abrir el piloto

Verificar el estado real de la aplicación OAuth y los requisitos de sus scopes.
Completar alta, consentimiento parcial, revocación y recuperación con una segunda
cuenta Google controlada. Probar popup en navegador real y Push en móvil con la
app cerrada; conservar navegador, versión, fecha y resultado. El titular realiza
el acceso interactivo y no comparte contraseñas ni tokens con el informe.

El titular confirmó que no dispone de segunda cuenta y móvil para estas pruebas.
Se mantienen no realizadas, sin sustituirlas por cuentas de terceros o simular
una aprobación real de Google.

No se presenta la aprobación de Google, la calidad de documentos ambiguos o la
recepción en un dispositivo no disponible como un fallo corregido en código.
