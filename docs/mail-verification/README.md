# Adaptación de correo: auditoría y evidencia

Fecha: 2026-10-20. Base: `a6c737d87160817db06460412694baa71455668f`.

Estado: implementación propuesta para revisión; **no lista para desplegar** hasta completar la suite integral y las comprobaciones OAuth reales. No se modificaron usuarios, secretos, Firebase, datos de producción, filtros de correo ni DNS. No se enviaron comunicaciones reales.

## Hallazgos comprobados

1. Los dos mensajes históricos de prueba siguen etiquetados SPAM en el buzón receptor autorizado. Los encabezados recibidos contienen SPF=pass, DKIM=pass y DMARC=pass, alineados con gmail.com. Transporte Gmail API HTTPREST. Las evidencias sanitizadas están en los dos archivos JSON de este directorio. No se conoce la causa exacta de clasificación; no se atribuye a falta de autenticación.
2. En la base, `telegram_bot.auto_send_application` seleccionaba índice 0 aunque hubiera varios correos. Ahora requiere selección si hay varios; el comportamiento de un único correo conserva el envío automático existente. La web aplica la misma política y ofrece opciones de correo sin elegir todos automáticamente.
3. En la base, `_process_job` terminaba con «Solicitud completada» tras entregar el PDF, independientemente del correo. Ahora identifica expresamente el resultado del PDF y remite al resultado de Gmail por separado; el trabajo conserva `email_status`.
4. La autorización del bot comprobaba Drive sin exigir gmail.send. Ahora exige el permiso antes de guardar una nueva autorización y al renovar una sesión; ambos envíos verifican el grant antes de iniciar la operación.
5. Ya existía aislamiento mediante `account_context.AccountState`/ContextVar, `user_accounts.scope` y credenciales cifradas por UID en `telegram_accounts.runtime`. Se preserva. Se elimina también un posible access_token heredado al construir configuraciones de otra cuenta. El fallback heredado continúa restringido al propietario original; no se usa para otra cuenta.

La versión desplegada no pudo comprobarse: la URL pública no fue accesible mediante la herramienta de consulta. No se afirma que coincida con la base auditada.

## Implementación

| Archivo / función | Cambio |
|---|---|
| application_mail.compose | Servicio común de MIME, identidad visible, asunto profesional, Date, Message-ID estable, texto plano y HTML escapado; usa el mismo gmail_request existente en ambos canales |
| application_mail.validate_pdf | Abre y renderiza todas las páginas; bloquea PDF inválido, reparado, protegido, sin texto, con acciones activas o sobredimensionado |
| application_mail.reserve_rate | Reserva CAS común a web/bot: máximo 20/hora por usuario, 10 segundos entre operaciones y una postulación al mismo correo/puesto por hora; límites preventivos propios, no cuotas oficiales de Gmail |
| resume_routes.send_gmail_application | Valida grant antes del PDF, usa composición común, archiva exactamente los bytes adjuntos, conserva hash, ID del PDF, origen del destinatario, UID y correlación |
| telegram_bot.process_application | Reutiliza PDF del Drive verificado del usuario, compara hash con el original cuando está disponible, compone correo común, conserva aceptación incluso si falla el historial secundario |
| telegram_bot.application_buttons / auto_send_application | Permite elegir correo; varios contactos no causan envío automático |
| telegram_accounts.save_oauth / runtime | Conserva permisos concedidos por UID y expone capacidad Gmail separada de Drive |
| static/app.js / index.html / telegram.js | Presentación profesional, selección de destinatario y capacidades Gmail/Drive independientes |

No se añaden permisos de lectura Gmail ni proveedores externos. La verificación del grant usa la frontera tokeninfo ya utilizada por el repositorio; queda pendiente comprobar ese intercambio con Google real. El flujo GIS popup mantiene las comprobaciones de Origin y X-Requested-With existentes; no se introduce un flujo redirect ni PKCE manual incompatible con GIS. La integración OAuth completa no está acreditada por las pruebas unitarias.

Flujos finales:

- Web: identidad de sesión → identidad Gmail verificada → grant → Drive de la cuenta → reserva por postulación → PDF → MIME y hash → archivo en Drive → límite preventivo → Gmail → aceptación/resultado incierto → historial.
- Bot: binding Telegram activo → contexto UID → token propio → PDF en carpeta autorizada → grant/identidad → validación y hash → límite preventivo → reserva CAS → Gmail → aceptación/resultado incierto → historial y mensaje separado del PDF.

## Matriz de pruebas ejecutadas

| Grupo | Resultado | Evidencia |
|---|---|---|
| PDF real, MIME decodificado, From/To/asunto/Date/Message-ID, texto/HTML, caracteres españoles y hash exacto | Aprobado | python-mail-tests.txt |
| PDF vacío, cifrado, roto, activo, tamaño PDF y MIME | Aprobado | python-mail-tests.txt |
| Inyección de encabezados, HTML escapado, composición simultánea de dos identidades y archivos distintos | Aprobado | python-mail-tests.txt |
| Permisos parciales, error 401/403/429/500/503 y timeout en frontera Google simulada | Aprobado | python-mail-tests.txt |
| Límite por usuario/destinatario, aislamiento del límite y conflicto CAS | Aprobado | python-mail-tests.txt |
| Ejecución unitaria de las definiciones reales de ruta web y worker, con fronteras inyectadas: adjunto exacto, duplicado, cuenta ajena, binding ajeno, hash alterado, pérdida de respuesta, ausencia de ID, fallo de historial posterior y múltiples contactos | Aprobado | orchestration-unit-tests.txt |
| Autorización frontend, reutilización, errores recuperables y ambiguos, generación automática y selección entre varios destinatarios | Aprobado | javascript-mail-tests.txt |
| Sintaxis Python/JavaScript y git diff --check | Aprobado | ejecución local |
| Suite Flask/backend con dependencias del proyecto | NO EJECUTADA: error de importación, falta google; también falta Flask en el runtime | backend-integration-attempt.txt |
| Historial frontend con DOM real | NO EJECUTADA: falta linkedom | dependencia documentada en tests/package.json |
| OAuth real, renovación/revocación real, GCS concurrente, Firebase y cambio de cuenta completo | NO EJECUTADA | requiere entorno completo y consentimientos de prueba |
| Envíos reales nuevos por web y bot entre dos cuentas independientes | NO EJECUTADA | falta aprobación explícita y buzones de prueba autorizados |

Resultados ejecutados: **18 pruebas del componente común + 12 pruebas unitarias de orquestación + 6 pruebas frontend aprobadas**. La extracción AST en las pruebas de orquestación ejecuta las funciones reales del código con dependencias inyectadas, sin arrancar Flask. No equivale a pruebas HTTP, de autenticación completa ni de entrega real.

Comandos reproducibles desde la raíz del repositorio, en un entorno con PyMuPDF y Node:

```sh
python tests/test_application_mail.py
python tests/test_mail_orchestration_offline.py
node --require ./scripts/offline_node.cjs --test tests/gmail-auth.test.cjs tests/gmail-recovery.test.cjs tests/automatic-gmail.test.cjs tests/application-flow.test.cjs
python -m compileall -q .
node --check static/app.js
node --check static/telegram.js
git diff --check
```

Se adaptaron también las pruebas existentes de Gmail y Telegram a PDFs reales; su ejecución integral sigue pendiente. La instalación de dependencias no estuvo disponible por las restricciones de red. No se omiten ni se presentan como aprobados los errores de importación.

## Limitaciones y cierre pendiente

- La clasificación en Principal/Spam depende del receptor; la nueva presentación aún no tiene medición real de entregabilidad.
- El rate limit reserva intentos de manera conservadora: un fallo posterior puede consumir un cupo. Una reserva ambigua bloquea el reenvío. No hay recuperación automática de postulaciones antiguas inciertas.
- El hash original solo puede contrastarse en trabajos nuevos; trabajos antiguos se validan estructuralmente al enviar pero no tienen un hash histórico verificable.
- La inspección de PDF sin texto bloquea también un CV completamente escaneado: decisión conservadora para CV generado con texto; debe revisarse si se admiten CV externos escaneados.
- Quedan por ejecutar la suite integral, el aislamiento de dos sesiones completas, cambio de cuenta, desvinculación y revocación en el entorno real. No se declara aceptación final hasta completarlos.
- `gmail_authorized` refleja permisos guardados, no una prueba continua de vigencia; cada envío vuelve a comprobar el grant. Credenciales antiguas sin metadatos requieren comprobar/reautorizar al probar la migración, sin borrar cuentas.
- No se implementa lectura de rebotes ni confirmación automática del buzón receptor porque requeriría permisos adicionales. No se asignan estados rebotado/recibido sin evidencia.

## Procedimiento de pruebas reales, pendiente de aprobación

1. Preparar dos cuentas Google de prueba A y B y dos chats Telegram vinculados correctamente; usar CV ficticios identificables y buzones receptores de prueba autorizados. Nunca vacantes ni empleadores reales.
2. Autorizar Gmail/Drive de cada cuenta por separado y comprobar identidad y carpetas. Probar autorización parcial, revocación y renovación sin exponer credenciales.
3. Por cada canal (web/bot), enviar una postulación de A a B y otra de B a A. Confirmar PDF correcto e historial aislado. No cambiar filtros ni marcar No es spam antes de documentar la clasificación inicial.
4. Registrar remitente, receptor, hora, application_id, gmail_message_id, Message-ID real, presencia en Enviados, categoría o Spam recibida, encabezados SPF/DKIM/DMARC sanitizados, nombre/tamaño/hash del PDF recibido y compararlo con el archivado.
5. Repetir callbacks y simular pérdida de respuesta en un entorno controlado para verificar ausencia de duplicados. Separar aceptación de Gmail de recepción, categoría y rebote.

## Despliegue y reversión

No ejecutar deploy ni fusionar todavía. El workflow existente despliega al hacer push a main. Mantener esta propuesta en una rama y PR borrador.

Antes de publicar: preparar dependencias fijadas y datos sintéticos con el procedimiento privado existente; ejecutar `scripts/verify_release.py`, revisar todas las regresiones y completar las pruebas de OAuth/entrega aprobadas. No modificar umbrales de cobertura para dar por aprobada la versión.

Tras aprobación explícita, desplegar el artefacto validado y observar errores sanitizados, permisos parciales y resultados inciertos. Reversión: restaurar la revisión de código anterior mediante el procedimiento de release; conservar las reservas de envío, credenciales y datos, sin reenviar trabajos ni borrar usuarios. No requiere migración destructiva.

## Fuentes oficiales consultadas

- https://developers.google.com/workspace/gmail/api/guides/sending
- https://developers.google.com/identity/protocols/oauth2/
- https://developers.google.com/identity/protocols/oauth2/web-server
- https://support.google.com/mail/answer/81126

Estas fuentes describen MIME/base64url, grants y autorización incremental; no garantizan clasificación en Principal.
