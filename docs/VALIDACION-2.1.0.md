# Validación 2.1.0

Fecha: 27 de septiembre de 2026.

## Preservación

- Copia del código, datos y ZIP ejecutable 2.0.1 en `backups/working-v2.0.1-20260927-193746/`, con SHA-256 de los archivos.
- El ejecutable 2.0.1 en `dist/DivoomKeeperStudio/` permanece separado de `dist/2.1.0/DivoomKeeperStudio/`.
- `keeper/protocol.py` no se ha modificado durante esta ampliación; se conserva el envío que el usuario validó físicamente.
- Se conserva el esquema 2 y la lectura de perfiles anteriores. Las listas son opcionales y mantienen un contenido de reserva compatible con la versión anterior.

## Pruebas

68 pruebas del núcleo, HTTP, widgets e interfaz, incluidas:

- Comparación de las peticiones JPG/PNG/GIF con el emisor original; IDs crecientes y protección del grupo nativo 0.
- Rotación de listas con duraciones diferentes e independencia entre pantallas.
- El tiempo de transferencia no consume la duración visible del elemento.
- Un envío fallido no avanza la lista; reintentos con separación mínima de 5 segundos.
- Una actualización de widget no reinicia la duración del elemento.
- Pausa, automático desactivado, avisos temporales y restauración del elemento activo.
- Escenas antiguas y nuevas, listas con contenido duplicado, exportación e importación de sus archivos.
- Validación de listas vacías activas, tipos nativos y duraciones fuera de rango.
- Recorte panorámico ordenado, conservación de la composición previa y rechazo de GIF animado como panorámica.
- Tasas de red calculadas con diferencias de contadores, caché compartida y reinicio de contadores.
- Disco ausente mostrado como N/D y renderizado de las cinco vistas del PC.
- Guardado y cancelación de diálogos, orden/duración de listas y aplicación de la panorámica desde la interfaz.

Capturas revisadas en `artifacts/ui-2.1.0/`: siete secciones, tema claro, editor PC, listas, panorámica y cinco vistas del monitor.

El ejecutable Windows empaquetado también supera la prueba de arranque, navegación, lectura de métricas, decodificación de GIF y calendario; resultado en `artifacts/packaged-ui-2.1.0/smoke-result.json`.

## Prueba en el Times Gate

- Panorámica numerada del 1 al 5, repartida entre las cinco pantallas.
- Lista en la pantalla 3 alternando gráficos del PC y tráfico de red con datos reales durante unos 35 segundos.
- Confirmación visual del usuario: «Sí, ambas funcionan».
- Al terminar se restauró la composición previa, incluido el GIF. La configuración del usuario se conservó sin cambios durante la prueba.
- Registro de peticiones y restauración en `artifacts/live-test-2.1.0.json`.

## Límites

- La CPU, RAM, disco y red no requieren un controlador adicional. GPU y temperatura NVIDIA dependen de nvidia-smi. No se añade un controlador de temperatura de CPU en Windows.
- Las listas necesitan Studio abierto y actualización automática activa. Los GIF grandes o fuentes lentas pueden retrasar otras pantallas porque el envío es serial.
- Las panorámicas son imágenes fijas y se envían por partes. No se ofrece sincronización de GIF entre pantallas.
- La activación del PC nativo sigue siendo experimental; el grupo 0 continúa bloqueado. No se han ampliado comandos nativos.
- Las pruebas automatizadas de escritura usan dobles y un servidor HTTP de prueba. La prueba física y su confirmación visual se documentan por separado arriba.

## Fuentes técnicas

- [psutil: contadores de red, discos y sensores](https://psutil.io/).
- [Pillow: ajustes y recorte de imágenes](https://pillow.readthedocs.io/en/stable/reference/ImageOps.html).
