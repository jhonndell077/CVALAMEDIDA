# Configuración de cuentas y consumos

Se añade Configuración al centro de Arquitectura y Diagnóstico Inteligente en `https://cvalamedida.web.app/admin/arquitectura#configuracion`.

## Alcance

El administrador consulta las cuentas de Firebase Authentication por páginas y el consumo de procesos de cada cuenta. Las barras representan cupo disponible, con valores numéricos de consumido, límite y restante. No representan dinero, tokens del modelo ni facturación de Google Cloud. Los períodos son UTC y la interfaz muestra las fechas de renovación.

Permite cambiar límites diarios y mensuales generales y excepciones por cuenta. Restablecer la herencia vuelve a los límites generales. Cero significa bloquear nuevos procesos; no significa ilimitado. Los cambios no reinician contadores ni cancelan trabajos admitidos. Un límite inferior al consumo actual deja cero disponible hasta la renovación o un nuevo ajuste.

Se conserva el criterio existente: admisión cuenta procesos, incluso si posteriormente fallan; un mismo identificador ya contado no vuelve a consumir cupo. Web y Telegram utilizan el mismo control de admisión. El máximo de diez trabajos simultáneos es independiente del cupo diario o mensual.

## Seguridad y persistencia

Las rutas `/api/admin/usage` y `/api/admin/usage/limits` validan la identidad Firebase y la autorización del administrador en backend antes de acceder a datos. Las escrituras exigen origen permitido, encabezado de petición y valores enteros acotados. Los cambios de generación se rechazan como conflicto para evitar sobrescribir ajustes de otro administrador.

La configuración se almacena en objetos dedicados del bucket privado existente mediante JobStore. No se modifican credenciales, reglas, identidades de Firebase ni bancos de datos de usuarios. No se exponen hashes de contraseña, tokens ni registros completos del proveedor. La lista de cuentas es una consulta administrativa manual y paginada, sin sondeos continuos.

## Requisitos y costos

La cuenta de ejecución necesita permiso para listar usuarios de Firebase Authentication y leer/escribir los objetos de configuración del bucket existente. No se amplía IAM automáticamente. Un error de permisos debe mostrarse como consulta no disponible, nunca como lista vacía o consumo cero.

No se añaden dependencias ni servicios. La consulta administrativa realiza lecturas acotadas de Authentication y Cloud Storage; guardar límites añade escrituras. La admisión lee la configuración compartida para aplicar cambios a web y bot. Estas operaciones pueden incrementar el costo existente de almacenamiento y funciones según uso.

## Validación

Verificador existente `scripts/verify_release.py --output tmp/admin-usage-final`: 444 pruebas Python y 227 JavaScript aprobadas, cobertura Python 81,72 %. Pruebas con fixtures y red bloqueada; no se cambian cuotas reales ni cuentas reales para probar. La revisión especializada cerró los hallazgos de contrato de encabezados y cambio a simulación durante espera de token; sin bloqueantes restantes.

## Comprobación publicada

Firebase confirmó funciones api y telegram_worker y ambos sitios Hosting. Consulta administrativa con sesión existente: cinco cuentas registradas cargadas con consumos reales; no se guardaron límites ni se alteraron cuentas para verificar. Los archivos HTML/JS/CSS publicados coincidieron con los probados; API sin sesión HTTP 401 y salud HTTP 200. Evidencia local en `tmp/admin-usage-smoke.json` y `tmp/configuracion-consumo-publicado.png`.

Se comprobó también el diseño a 390 píxeles y se corrigió el desbordamiento de la representación accesible del medidor. Los cambios de cuotas se probaron únicamente con almacenes simulados; no se afirma una escritura de prueba sobre producción.
