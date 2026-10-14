# Búsqueda unificada de empleo RD

Una consulta reúne resultados en la ventana de ofertas, con filtro por fuente,
calendario en hora de República Dominicana y selección separada de ofertas sin
fecha. Una fuente caída no descarta las respuestas de las demás. No se interpreta
un fallo de consulta como ausencia de vacantes.

## Conexiones utilizadas

| Fuente | Acceso | Datos mostrados |
| --- | --- | --- |
| Chiripas | RSS público https://chiripas.com/rss/all/ | Cargo, empresa, descripción, fecha y enlace original |
| TuEmpleoRD | RSS de empleos https://tuempleord.do/?feed=job_feed | Cargo, descripción, ubicación, fecha y enlace original |
| RD Trabaja | API pública https://empleateya.mt.gob.do/api/puestos | Cargo, descripción, requisitos y fechas; empresa no informada |
| TuVacanteRD | Índice público https://tuvacanterd.com/ultimas-vacantes | Resumen de cargo, empresa cuando existe y enlace original; no se inventan fechas ni requisitos |
| Aldaba | Búsqueda original con cargo y país RD | Acceso directo, sin extracción de ofertas |
| Computrabajo RD | Búsqueda original con cargo y orden reciente | Acceso directo, sin extracción de ofertas |

RD Trabaja abre el detalle en un modal y no ofrece un enlace individual verificado.
La tarjeta abre su búsqueda con el cargo. Su ID público distingue dos anuncios
con el mismo título; no se fusionan por compartir enlace de búsqueda. Sus fechas
sin offset se interpretan como hora local de RD.

Para TuVacanteRD se leen solo los datos breves del índice, que debe identificar
el país como DO. Antes de adaptar un CV se pide pegar los requisitos originales;
no se usa el resumen como si fuera la descripción completa.

## Límites y fallos

- Hasta 50 resultados por fuente integrada y 200 en total; no es todo el archivo histórico.
- Consultas en paralelo, caché por fuente y consulta durante 15 minutos.
- Peticiones con timeout, tamaño máximo de 2 MB y sin seguir redirecciones.
- Los destinos de red son fijos. No se visitan URLs proporcionadas por usuarios.
- Descripciones como texto; entidades XML y destinos ajenos se rechazan.
- Aldaba y Computrabajo aparecen siempre como consulta directa, no como resultados integrados vacíos.

No se instalan dependencias ni se requieren claves de estos portales. Se conserva
la autenticación y el límite diario existente del módulo. Las pruebas usan
fixtures locales y no consultan Firebase ni portales reales.

## Fuentes primarias revisadas

- Chiripas, publicación RSS y uso: https://chiripas.com/rss
- WP Job Manager, feed diseñado para publicar/importar vacantes:
  https://wpjobmanager.com/document/advanced-usage/rss-feed-for-jobs/
- Frontend oficial RD Trabaja (GET /puestos y filtros de búsqueda):
  https://rdtrabaja.mt.gob.do/main.c8a79a36c39c5f31.js
  y https://rdtrabaja.mt.gob.do/209.60479e409512cc94.js
- TuVacanteRD, condiciones: https://tuvacanterd.com/terminos
  e índice público con robots Allow: https://tuvacanterd.com/robots.txt
- Aldaba, reproducción/distribución requiere autorización:
  https://www.aldaba.com/avisoLegal.php
- Computrabajo, prohíbe extracción automática y reproducción sin autorización:
  https://do.computrabajo.com/avisolegal/

Para integrar también los resultados de los dos últimos dentro de la ventana
se necesita una API o acuerdo de distribución del proveedor. El enlace de
consulta conserva el cargo escrito y la selección de República Dominicana.
