# Planes por usuario — DOP y gestión manual

Configuración añade el botón Plan en cada cuenta. Permite asignar una modalidad, una tarifa mensual en pesos dominicanos y límites diarios/mensuales personalizados. No modifica el consumo ya registrado ni realiza cobros.

El catálogo inicial propone Básico (10 diarios/50 mensuales), Plus (20/200), Pro (50/500) y configuración personalizada. Son plantillas editables de cupos, no una estimación de costos ni garantía de capacidad. Los planes de pago no incluyen precios inventados: el administrador debe introducir la tarifa. La sugerencia de modalidad utiliza sólo el consumo registrado y no aplica cambios automáticamente.

## Persistencia y acceso

Plan y límites se guardan en el mismo objeto privado con comprobación de generación, para evitar un plan nuevo con cupos anteriores tras un fallo parcial. El backend verifica identidad administrativa, origen, UID existente, importe y límites. Asignar un plan no reinicia contadores ni confirma que se haya recibido un pago.

Editar los cupos directamente conserva la tarifa y señala límites personalizados. Restablecer los límites generales quita la asignación de plan de esa cuenta de forma explícita. Reiniciar consumo conserva la asignación de plan.

## Preparación para una pasarela

Los importes se representan como enteros en centavos (`priceMinor`), con moneda ISO `DOP` y período `month`. El modo de cobro es `manual` y el pago permanece `unverified`. Esto permite añadir después un adaptador de pasarela sin mezclar importes con contadores de operaciones.

La integración futura debe incorporar checkout, referencias de cliente/suscripción por proveedor, verificación de firmas de webhooks e idempotencia de pagos antes de activar o renovar automáticamente suscripciones. No hay SDK, webhook, credenciales ni enlaces de cobro activos en esta entrega. No se guardan datos de tarjetas.

Los cupos siguen renovándose por períodos UTC de calendario. La tarifa mensual configurada no crea una factura ni cambia por sí sola la fecha de cobro de una suscripción.

## Verificación

Verificador existente `scripts/verify_release.py --output tmp/manual-plans-final`: 465 pruebas Python y 239 JavaScript aprobadas; cobertura Python 81,95 %. Pruebas con fixtures y red bloqueada. Incluyen importe exacto de 0,29 DOP, rechazo de más de dos decimales y precios inválidos, pago no verificado, CAS y protección de acceso/sesión/simulación. Sin asignar planes, modificar cupos ni cobrar a cuentas reales durante la verificación.

No se añadieron dependencias ni servicios de pago. Plan y cupos comparten el objeto que ya se consulta para admisión; el guardado administrativo añade una escritura explícita de configuración. No hay sondeos de facturación.

## Publicación

Firebase confirmó api, telegram_worker y ambos sitios Hosting, build `20261017T175306Z-38eeedae`. Los archivos JS/CSS publicados coinciden con los probados (`tmp/manual-plans-smoke.json`). Con sesión administrativa se verificaron los botones Plan en las cuentas cargadas y el formulario con plantilla Plus, cupos 20/200, precio vacío y moneda DOP. Se comprobó a 390 px sin controles desbordados. No se pulsó Guardar plan ni se cambiaron asignaciones reales. Captura: `tmp/plan-dop-publicado.png`.


## Plan Básico, catálogo y anuncios de consumo

Los límites generales definen siempre el Básico gratuito. Una asignación explícita de Básico hereda esos límites también en la admisión real. Configuración → Límites generales → Planes y beneficios permite editar el catálogo Plus/Pro y el Personalizado opcional: nombre, cupos, precio mensual DOP, beneficios y publicación. Los cambios del catálogo no reasignan ni cobran automáticamente a cuentas existentes.

La app consulta el plan propio al iniciar sesión, sin exigir Drive. Un rechazo verificado por agotamiento diario o mensual muestra un anuncio flotante con Ver planes. Los errores de concurrencia no generan ese anuncio. La bienvenida identifica una asignación confirmada y presenta sus beneficios o cupos reales; no afirma que el pago manual esté confirmado. Se evita repetirla al editar sólo los cupos. Los anuncios se deduplican por cuenta, asignación y período; cerrar sesión elimina la vista y descarta respuestas atrasadas.

No hay consultas periódicas. La consulta del plan realiza cuatro lecturas de objetos privados al iniciar sesión o recibir un rechazo por cuota. La página administrativa añade una lectura de catálogo por página de cuentas. Guardar el catálogo hace una escritura explícita con control de generación. No se añadieron dependencias ni pasarela de pago; los precios vacíos se presentan como Precio por confirmar.

Archivos principales: plan_catalog.py, admission_policy.py, admin_usage.py, admin_plans.py, app.py, static/admin-architecture.js/.css, static/subscription-notices.js/.css, static/app.js y static/index.html. Pruebas locales con fixtures, red bloqueada y sin operaciones sobre cuentas reales.
