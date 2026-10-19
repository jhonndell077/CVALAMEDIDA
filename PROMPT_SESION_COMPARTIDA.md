# Prompt: funcionamiento coherente entre dispositivos

Implementa una única lógica funcional y una versión publicada común de CV a la Medida. Usa este ordenador como referencia del comportamiento esperado, nunca como fuente de credenciales ni como copia de los datos de otras cuentas.

Para una misma cuenta, todos los dispositivos deben consultar el mismo estado confirmado en el servidor: datos guardados, procesos y errores registrados. Ante la misma revisión del estado, si existen cinco incidencias confirmadas, deben mostrar cinco. No conviertas la ausencia de eventos en prueba de buen funcionamiento. La sincronización periódica puede producir un breve desfase entre consultas.

Mantén separados los fallos locales de red, permisos del navegador y ventanas de autorización. No inventes errores en otros equipos ni ocultes fallos para igualar una pantalla. No compartas datos, permisos, cuotas o sesiones entre cuentas distintas.

Recupera operaciones únicamente cuando su causa esté confirmada. Conserva formularios, documentos de Drive, CV, historial, planes y reservas de operaciones activas. No borres localStorage de forma global, no revoques sesiones, no reinicies cuotas y no repitas envíos de correo o generación de CV para simular una reparación.

Comprueba con fixtures locales setenta clientes independientes, aislamiento entre cuentas, token renovado, cambio de usuario, desconexión y recuperación. Distingue simulaciones de dispositivos físicos. Informa qué errores se corrigieron, cuáles necesitan evidencia y qué cambios están publicados. Publica únicamente con instrucción explícita de despliegue.

## Alcance de esta implementación

El endpoint `/api/session/state` comparte incidencias confirmadas de la ventana disponible del diagnóstico: hasta una hora y 400 eventos globales. La salida de un evento de esa ventana no confirma recuperación. No replica sesiones OAuth, formularios sin guardar ni procesos históricos, ni garantiza la disponibilidad de servicios externos. Consulta al entrar y recuperar conexión; mientras el detalle y el menú están abiertos, actualiza al recuperar foco y cada veinte segundos. No modifica cuentas ni documentos.
