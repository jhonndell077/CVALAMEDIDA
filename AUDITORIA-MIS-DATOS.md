# Auditoría de Mis datos — 14 de octubre de 2026

Actualización posterior a la auditoría: se habilitó el editor completo en modo Drive para los ocho renglones, con comprobación de la versión original, escritura condicional, verificación posterior y conservación de cambios manuales al reconstruir evidencia. Guardar cambios también invalida análisis y CV anteriores. Los hallazgos siguientes describen el estado previo y su motivación. Las pruebas de edición web agregadas cubren las ocho secciones y el rechazo de versiones antiguas.

Alcance: código actual del workspace, incluidos los arreglos previos aún sin desplegar. Pruebas con archivos temporales y Drive simulado; no se confirmó el comportamiento de la versión publicada ni de Safari en un dispositivo real.

| Renglón | Guardado manual en appweb | Persistencia comprobada |
| --- | --- | --- |
| Datos personales | No habilitado | Editor local: escritura y recarga. En web se incorporan datos de documentos/onboarding. |
| Experiencias y funciones | Sí, Nueva información | Escritura de JSON en Drive simulado, reintento sin duplicado y reconstrucción del perfil. |
| Habilidades | No habilitado | Editor local: escritura y recarga. En web se incorporan habilidades de documentos/onboarding. |
| Estudios | Sí, Nueva información | Escritura de JSON en Drive simulado, reintento sin duplicado y reconstrucción del perfil. |
| Cursos realizados | Sí, Nueva información | Escritura de JSON en Drive simulado, reintento sin duplicado y reconstrucción del perfil. |
| Proyectos | Sí, Nueva información | Escritura de JSON en Drive simulado, reintento sin duplicado y reconstrucción del perfil. |
| Referencias | Sí, Nueva información | Escritura de JSON en Drive simulado, reintento sin duplicado y reconstrucción del perfil, incluidos registros antiguos sin ID. |
| Datos pendientes de documentar | No habilitado | Editor local: escritura y recarga. La sincronización conserva la lista del perfil base; las notas de documentos se convierten en avisos, no se añaden a esta lista. |

## Hallazgos

1. **Falta cobertura funcional para tres renglones en appweb.** `static/index.html` solo ofrece cinco tipos. `app.new_information_record` acepta esos cinco; `PUT /api/profile` bloquea expresamente la edición en modo Drive/remoto. Las tarjetas muestran campos deshabilitados y ocultan Guardar cambios. No existe un guardado manual desde Mis datos para datos personales, habilidades y pendientes.
2. **Editar un registro existente no está habilitado en appweb.** Nueva información agrega o consolida registros compatibles; no sustituye sus valores existentes. `merge_record` conserva campos no vacíos y combina roles/descripciones/listas. No debe interpretarse un mensaje de guardado como confirmación de que se reemplazó un dato antiguo.
3. **El editor local guarda el banco, pero conserva análisis y CV anteriores.** `saveProfileChangesWork` actualiza perfil e índices y limpia el estado de edición, sin invalidar `state.analysis`, `state.draft`, `state.pdf` ni `vacancyRevision`. El flujo Nueva información sí los invalida. Un CV ya preparado puede seguir usando datos anteriores después de editar localmente.
4. **Fotografía:** no se modifica desde las tarjetas de Mis datos; la interfaz indica reemplazar el archivo del banco y sincronizar. Su subida pertenece al flujo de onboarding.

## Evidencia

- `tests/test_data_bank_audit.py`: ocho secciones guardadas por PUT local, lectura del archivo persistido, GET posterior y reconstrucción; cinco tipos escritos por DriveBank con verificación de reintentos; rechazo explícito de los tres tipos no soportados en web.
- `tests/test_new_information.py`: ruta HTTP de los cinco tipos, lectura posterior y referencias nuevas/existentes sin ID.
- `tests/profile-persistence.test.cjs`: aplicación del perfil devuelto, prevención de respuestas antiguas y reintentos.
- Las comprobaciones de Drive simulan respuestas de red. No equivalen a un guardado en el banco real de la cuenta.

Conclusión: los cinco guardados manuales disponibles alimentan el perfil base en las pruebas. Los ocho renglones persisten en el editor local. El apartado web completo todavía requiere implementar los tres guardados faltantes y la edición de registros existentes. Esta auditoría no cambia APIs ni configuración de despliegue.
