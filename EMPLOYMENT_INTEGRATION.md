# Empleo inteligente — búsqueda RD

La pantalla principal tiene un campo de cargo, **Buscar vacantes** y **Ver últimas publicadas**. No requiere GPS, sincronización de Drive ni evaluación del perfil para consultar ofertas. Las búsquedas requieren la sesión Google existente.

La fuente agregada es el RSS oficial de Chiripas: https://chiripas.com/rss/all/. Su página https://chiripas.com/rss autoriza incluir los empleos conservando el enlace de aplicación a Chiripas. Se conservan enlaces y atribución, se interpreta RSS 1.0 y RSS 2.0 y se muestra el contenido como texto seguro. El feed consultado contiene la bolsa de RD; no se presenta la distancia como comprobada. No se ejecutan envíos de candidaturas.

Buscar filtra cargo y empresa sin distinguir mayúsculas ni acentos. Últimas ignora el cargo y devuelve hasta 200 vacantes del feed por fecha descendente; los registros sin fecha quedan al final. No representa todas las vacantes de todos los portales. La caché pública dura cinco minutos y no contiene CV, identidad ni coordenadas.

Himalayas y HiringCafe se retiraron del registro activo y de la interfaz principal. Se conservan los seis enlaces de portales vinculados con RD como consultas manuales en una sección plegable. Las utilidades geográficas y el historial siguen disponibles en secciones opcionales.

Pruebas locales: tests/test_employment_rd.py cubre RSS, búsquedas sin GPS, fechas, seguridad de enlaces, caché y fallos. tests/employment-rd.test.cjs cubre la búsqueda por cargo, últimas sin filtro, tarjetas, CV, fallos y disposición del formulario. Los tests usan fixtures y no consultan servicios de producción.

## Calendario de últimas publicaciones

Al consultar las últimas se abre un calendario por mes, con conteos por día. Elegir una fecha filtra el resultado ya recibido sin consultar otra vez el proveedor. Las fechas se convierten a America/Santo_Domingo; las vacantes sin fecha aparecen solo en la vista de todas. Hay navegación mensual y un botón para quitar el filtro. El calendario se limpia al cambiar de cuenta. No se afirma disponer de un archivo histórico fuera de las ofertas del RSS.
