# Mapa funcional automático de la web

Ruta: https://cvalamedida.web.app/admin/funcionamiento, enlazada desde /admin/conexiones. Autorización interna mediante el mismo propietario verificado por Firebase que el monitor de conexiones.

## Qué demuestra cada señal

- Inventario: páginas HTML públicas de la aplicación, controles nativos, manejadores estáticos, asignaciones directas de disponibilidad, enlaces y llamadas API inferidas. Las vistas administrativas no se incluyen en el inventario de la aplicación del usuario.
- Comparación: controles añadidos, retirados o modificados frente a la publicación anterior y frente a la primera base. Un cambio estructural no equivale a una regresión.
- Pruebas: resultado global de la suite local, cantidades y cobertura, vinculados al hash del código. Referencias a IDs en tests son referencias, no cobertura funcional completa de ese botón.
- Configuración: rutas Flask registradas y banderas de autenticación, múltiples cuentas y empleo. Registrar una ruta no comprueba disponibilidad de su proveedor ni su efecto de negocio.
- Observación: ventana de la aplicación abierta expresamente por el administrador. Disponibilidad visible, estados de carga, clicks y estados HTTP de fetch; fallos JavaScript se notifican sin contenido ni stack. Un fallo HTTP posterior a un click se presenta como coincidencia temporal, no como causalidad demostrada.

## Actualización en cada publicación

1. `scripts/verify_release.py` ejecuta comprobaciones sintácticas y suites con red bloqueada para Python. Escribe `tmp/functional-map-test-evidence.json` con hash de fuentes y resultado.
2. `generate_manifest.py` y `generate_version.py`, hooks predeploy existentes, llaman a `generate_functional_map.py`.
3. Se descarga exclusivamente el inventario estructural público de la versión actualmente publicada. Un 404 inicial establece la base; errores de consulta o esquema incompatible bloquean la publicación para no perder la referencia.
4. `generate_functional_map.cjs` analiza HTML con linkedom y JavaScript con Acorn ya incluido en Firebase CLI, sin ejecutar scripts de la aplicación. No instala dependencias. Si falta el analizador, falla la publicación.
5. Se exige evidencia aprobada para el hash actual. Se escribe el JSON mediante reemplazo atómico. Las dos ejecuciones de Hosting no convierten la versión actual en su propia comparación.
6. El manifiesto queda publicado en `static/functional-map.manifest.json`. Contiene metadatos estructurales de fuentes públicas, versiones y totales de pruebas; no contiene datos de usuario, secretos ni observaciones de sesiones.

Los nuevos controles HTML y páginas se incorporan sin editar el diagrama. Los controles generados durante el uso aparecen al abrir su pantalla en observación; no se inventa un manejador cuando no se puede resolver. La primera publicación de esta funcionalidad establece la base; no reconstruye evidencia histórica de versiones anteriores.

## Privacidad y límites

El observador solo se activa con `?cv-observe=1` y un opener del mismo origen. No cambia CSP ni permite iframes. Envía mensajes únicamente a esa ventana; la vista receptora verifica origen y ventana exacta. No captura valores de campos, textos de CV, payloads, tokens, consultas de URL ni cuerpos de respuesta. Las rutas HTTP no presentes en el inventario público se sustituyen por `/ruta-no-inventariada`. Solo se muestran metadatos en memoria del navegador; detener observación o cerrar sesión descarta estados.

La instrumentación no hace click ni invoca acciones de negocio automáticamente. Usar la ventana conserva los efectos habituales de las acciones elegidas por el administrador. Los fallos observados no se convierten en verdes por una simple nueva instantánea. Una nueva observación permite comprobar la corrección sin arrastrar esos fallos.

No es una prueba exhaustiva de todas las ramas. La resolución estática conserva relaciones conservadoras de funciones compartidas; puede incluir destinos de ramas no ejecutadas. Los manejadores delegados, callbacks ambiguos, redirecciones fuera del origen, XHR, iframes externos y componentes cerrados requieren pruebas específicas. No se añaden tests semánticos automáticamente por detectar un nuevo botón. Las suites fallidas impiden publicar y su detalle queda en CI, no se atribuye una avería a un botón sin evidencia.

## Operación y reversión

La vista actualiza el inventario cada minuto mientras está visible. Su endpoint es de lectura y no ejecuta sondas de Vertex, Drive, Telegram o Gmail. Usa Hosting y la API existentes. No cambia presupuestos ni cuotas.

Reversión: recuperar el commit anterior y volver a desplegar con la suite aprobada, o restaurar la versión anterior de Hosting y la revisión anterior de la API. Conservar el manifiesto publicado como referencia de comparación. No modificar manualmente las señales para convertir pendientes en éxitos.
