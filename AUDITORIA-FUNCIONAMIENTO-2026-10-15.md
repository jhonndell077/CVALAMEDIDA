# Auditoría de funcionamiento — 15 de octubre de 2026

Sitio: https://cvalamedida.web.app/. Revisión del código, suites completas existentes y comprobación visual de la interfaz con servicios simulados. No es una certificación de ausencia de errores ni una prueba de penetración.

## Hallazgos corregidos

| Hallazgo | Evidencia y efecto | Corrección |
| --- | --- | --- |
| Sincronizar y Analizar vacante inaccesibles sin sesión | Reproducido en el sitio publicado: ambos controles tenían `disabled`. La sesión de otro dispositivo no inicia automáticamente la de este navegador. | Los controles permiten pulsar y explican que se debe iniciar sesión en ese dispositivo. Mantienen la autorización obligatoria para ejecutar las operaciones. |
| Inicialización del modelo dependía de completar acceso/perfil | `loadModels` estaba después de las operaciones de inicialización que podían fallar. | Se configura el modelo antes de iniciar esas operaciones. |
| Carga inicial sin recuperación | Salud del servidor y scripts de Firebase podían esperar indefinidamente. El error de servidor afirmaba, sin comprobarlo, que faltaba Blaze. | Límite de espera de 20 segundos, errores de conexión y botón Reintentar inicio. |
| Renovación de token durante cambio de cuenta | Una respuesta anterior podía sustituir el token de la cuenta nueva, incluso antes de enviar una petición. | Se comprueba el propietario después de renovar y antes de guardar el token o enviar la petición. Pruebas con respuestas retrasadas de otra cuenta. |
| Renovación de sesión habilitaba Analizar durante un análisis | El cálculo de disponibilidad no contemplaba el estado ocupado del botón. | La disponibilidad conserva el bloqueo mientras el análisis está ocupado. |
| Recursos ausentes en el servidor Flask | Lista de recursos públicos omitía paneles de datos, navegación, selección de categorías, manual y acceso auxiliar de Drive. | Lista explícita completada. Prueba de todas las dependencias de las páginas y de rechazo a archivos privados. |
| Anuncio vacío iniciaba trabajo innecesario | La validación ocurría en el backend, después de intentar sincronizar. | Validación antes de sincronizar o solicitar el análisis. |
| Acceso desde Mis datos | Al pedir sesión desde el modal, el fondo permanecía inaccesible o el foco volvía a Datos. | Se cierra el modal y, tras su cierre, se enfoca Continuar con Google. Verificado visualmente. |

## Alcance de las comprobaciones

- Interfaz: acceso y cierre de sesión, Drive y Gmail, botones, carga concurrente, cancelación de permisos, cambios de cuenta, edición del perfil y referencias, formulario inicial, anuncio adjunto y selección entre varias vacantes, navegación, CV recuperados y Empleo Inteligente.
- Backend: autenticación y separación entre cuentas, banco y sincronización, altas y eliminación de datos, extracción documental, análisis y reintentos, trabajos persistentes, Telegram, contactos, historial y generación de PDF/Word.
- Seguridad: revisión con `ecc:security-review`; autorización antes de rutas privadas, comprobación de identidad de Drive, contexto aislado por cuenta, validación de entradas, uso de texto para contenido dinámico y acceso restringido a recursos estáticos. La comprobación de publicación muestra únicamente ubicaciones si detecta patrones sensibles.
- Navegador real: controles sin sesión en escritorio y pantalla de 390 × 844; sincronización desde el modal; mensaje y foco en el acceso; recuperación visible tras un tiempo de espera de Firebase. Servicios simulados en localhost.

## Verificación

- Frontend: 106 pruebas aprobadas mediante `npm test --prefix tests`.
- Backend: 312 pruebas aprobadas en la suite completa de unittest, con conexiones de socket bloqueadas para evitar llamadas a servicios reales.
- Sintaxis: 29 módulos Python, 19 archivos JavaScript y tres manifiestos JSON válidos.
- El proyecto no tiene scripts de compilación, lint o tipos; no se instalaron herramientas. No hay herramienta de cobertura instalada; no se declara un porcentaje de cobertura.
- Diff revisado y comprobación de publicación previa al despliegue mediante el script existente.

## Límites y comprobación posterior

El bloqueo sin sesión se reprodujo en producción; no se dispone de evidencia que permita atribuir todos los bloqueos observados por el usuario a esa única causa. La validación autenticada de sincronización, análisis, exportación, Telegram y Gmail se hizo con fixtures: no se enviaron correos ni se modificaron bancos privados para probarlos. No se ejecutaron pruebas contra servicios de producción. Las restricciones particulares de Safari, Firefox, extensiones y políticas del ordenador del usuario requieren reproducción en esos entornos si el problema persiste.

El despliegue usa `Deploy.ps1`, que publica las funciones y ambos sitios de Hosting y sincroniza GitHub. El resultado efectivo de publicación y la versión servida se verifican después; este documento no presupone que el despliegue haya terminado.
