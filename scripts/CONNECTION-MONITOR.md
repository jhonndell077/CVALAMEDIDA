# Diagrama de conexiones

Iniciar desde la raíz del proyecto:

```powershell
node scripts/connection_monitor.cjs
```

Abrir http://127.0.0.1:8765. El proceso solo escucha en este equipo; detenerlo cierra el monitor. No se ha publicado en Firebase.

Consulta la página pública y `/api/health` cada 60 segundos, con caché compartida entre pestañas. Son lecturas reales, sin credenciales ni datos personales. No envía mensajes ni invoca IA. Verde significa respuesta válida del recurso consultado; no significa prueba de acceso de un usuario ni entrega de mensajes. Un HTTP fallido aparece rojo. Problemas de conectividad del equipo y lecturas vencidas aparecen sin verificar.

Drive, Google/Firebase Auth, Vertex, Storage, Tasks, worker, Telegram, Gmail, Push y presupuestos están documentados a partir de la auditoría, pero carecen de sondas autenticadas actuales en esta versión. Las líneas muestran dependencias implementadas, no tráfico real. No hay alertas persistentes cuando el equipo está apagado. La copia HTML funciona como documento de consulta; necesita el servidor local para consultar estados actuales.

Para una cobertura completa falta instrumentación autenticada por servicio y trazabilidad de trabajos con identificadores de correlación, errores sanitizados y tiempos de cada etapa. Su ausencia se muestra explícitamente, sin inferir salud de una configuración o un resultado histórico.

Verificación: `node --test tests/connection_monitor.test.cjs` (fixtures de HTTP, sin servicios reales); suite JavaScript completa: 158 pruebas aprobadas. Lectura del monitor comprobada en navegador: Hosting y API respondieron correctamente el 16/10/2026. No se modificaron despliegues, permisos, datos ni presupuestos.
