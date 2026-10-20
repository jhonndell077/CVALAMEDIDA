# Diagnóstico: cuenta bloqueada al analizar o generar un CV

## Causa identificada

El mensaje de la primera captura coincide con `job_account_maintenance`. El servidor lo devuelve cuando la cola de esa cuenta contiene `maintenance`. No depende del almacenamiento local ni del tamaño de pantalla: el bloqueo acompaña a la cuenta en cualquier dispositivo.

La ruta de eliminación administrativa de usuarios crea esa marca antes de revocar Telegram, revocar sesiones y solicitar la eliminación de la identidad Firebase. La implementación anterior no enlazaba la marca a su plan ni registraba un resultado terminal. Si fallaba una etapa, la marca podía permanecer indefinidamente. La eliminación completada también conserva un bloqueo deliberado; por eso no es seguro borrar cualquier marca al iniciar sesión.

Reproducción local de la versión anterior con proveedores simulados: eliminación fallida devuelve 503; la marca permanece; reiniciar consumo devuelve 200 pero no retira el bloqueo. Limpiar el navegador tampoco lo resuelve.

Los dos registros 503 de la segunda captura no acreditan dos causas distintas: son incidencias de solicitudes rechazadas a la misma ruta.

## Corrección general implementada localmente

- Vincular cada bloqueo nuevo con su plan, etapa y estado: en ejecución, fallido o completado.
- Comprobar la propiedad del bloqueo antes de cada etapa externa de la eliminación.
- Registrar fallos terminales sin conservar mensajes privados del proveedor.
- Mostrar al administrador qué cuentas tienen bloqueo y aclarar que reiniciar consumo no lo retira.
- Añadir `Recuperar acceso` como acción distinta, con vista previa, UID exacto, administrador autorizado, vencimiento y escrituras CAS.
- Permitir recuperación únicamente cuando el fallo original esté verificado, la identidad exista y esté habilitada, no haya procesos activos y no se haya intentado una eliminación de resultado incierto.
- Conservar banco, CV, consumo, recibos y procesos. No restaurar automáticamente permisos revocados.

## Límites y bloqueos antiguos

Un registro antiguo con solo `action` y `at` no permite saber si la eliminación falló, terminó o perdió su confirmación. La corrección lo identifica y exige investigación del registro original; no lo retira por antigüedad ni por el hecho de que un navegador conserve sesión.

Las capturas y el código permiten identificar la causa del rechazo reportado. No se consultaron ni modificaron los registros privados de la cuenta de producción para atribuirle una etapa o resultado que no estén confirmados. No se afirma que esa cuenta ya esté desbloqueada.

## Pruebas ejecutadas

- 358 pruebas JavaScript y 561 Python: **919 aprobadas**, sin fallos.
- Cobertura Python: **82,96 %**.
- Suite integral ejecutada con conexiones externas bloqueadas.
- Recuperación de 70 cuentas simuladas, conservando consumo y sin llamar a la eliminación de identidades.
- Bloqueos antiguos, activos, completados y desconocidos; identidades ausentes o deshabilitadas; resultado externo incierto; cambio concurrente de cola o plan; aislamiento entre cuentas; confirmación exacta y rechazo de repetición.
- Flujo administrativo de vista previa y ejecución verificado con fixtures locales.

## Entrega

Cambios locales en `admin_user_actions.py`, `admin_usage.py`, `static/admin-architecture.js` y pruebas asociadas. Tres agentes participaron en la investigación de causa, seguridad y puntos de integración. La implementación y la ejecución de pruebas se completaron en el agente principal.

**No se desplegaron cambios ni se restablecieron cuentas de producción.**

## Fase 1 · S01: trazabilidad y recuperación local

Los fallos confirmados de eliminación guardan `state=failed`, `code=admin_delete_failed`, etapa, `correlationId` generado en el servidor y `finishedAt`, tanto en el plan como en su marca. Un éxito confirmado no se reclasifica como fallo por un conflicto posterior al guardar la confirmación. Los conflictos CAS se reintentan de forma acotada.

La recuperación conserva un recibo de resultado. Repetir exactamente la misma acción ya confirmada devuelve ese recibo sin volver a modificar la cuenta, incluso si el plan venció después del éxito. Si se perdió únicamente la confirmación final, el recibo de la cola permite completar el registro del plan sin retirar un bloqueo nuevo creado entretanto.

Un cierre forzado del proceso o una indisponibilidad persistente de Storage no permiten inventar un resultado terminal: el registro incompleto permanece bloqueado para revisión. Nunca se retira mantenimiento por edad. Una eliminación externa iniciada y no confirmada tampoco se repite ni se considera recuperable automáticamente.

### Lista de bloqueos antiguos a revisar: procedimiento manual pendiente

No se enumeraron cuentas reales ni se ejecutaron estas consultas. El humano debe ejecutar únicamente lecturas y proyectar los campos permitidos; los documentos completos de planes contienen pruebas privadas y **no deben imprimirse**.

```powershell
# Inventario de objetos de cola; no descarga contenido del banco.
gcloud storage ls --project=cv-a-la-medida-jhonn 'gs://cv-a-la-medida-jhonn-telegram-private/jobs/vacancy-queue*.json'

# Para una cuenta elegida y verificada en Firebase Console:
$phase1Uid = Read-Host 'UID exacto a revisar'
$phase1Hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($phase1Uid))).ToLowerInvariant()
$phase1Queue = gcloud storage cat --project=cv-a-la-medida-jhonn "gs://cv-a-la-medida-jhonn-telegram-private/jobs/vacancy-queue-$phase1Hash.json" | ConvertFrom-Json
$phase1Queue.maintenance | Select-Object action,state,stage,code,correlationId,at,finishedAt,planId

# Solo si maintenance.planId existe; nunca imprimir proofKey ni el documento completo.
$phase1PlanId = $phase1Queue.maintenance.planId
if ($phase1PlanId -match '^[a-f0-9]{32}$') {
    $phase1Plan = gcloud storage cat --project=cv-a-la-medida-jhonn "gs://cv-a-la-medida-jhonn-telegram-private/jobs/admin-user-action-$phase1PlanId.json" | ConvertFrom-Json
    $phase1Plan | Select-Object id,uid,action,state,stage,code,correlationId,createdAt,finishedAt,deleteAttempted
}
```

Registrar por cada objeto: identidad existente/habilitada comprobada en Firebase Console, estado del plan original, etapa, fecha, resultado externo confirmado o desconocido y procesos pendientes. Sin `planId`, sin estado terminal o con eliminación externa incierta: **revisión manual, sin desbloqueo automático**. No ejecutar `reset` ni borrar la marca como sustituto. La lista queda pendiente de evidencia humana.
