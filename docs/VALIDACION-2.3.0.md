# Validación 2.3.0

Fecha: 27 de septiembre de 2026.

## Conservación

La versión 2.2 se conserva en `dist/2.2.0/` y `backups/working-v2.2.0-20260927-203514/`, con código, pruebas, paquete, datos y manifiesto SHA-256. `run_stable_2.2.ps1` prepara una copia independiente en `compat/2.2.0-data/`, sin modificar el checkpoint ni registrar autoarranque. La recuperación 2.1 y la aplicación original siguen disponibles.

El SHA-256 de `keeper/protocol.py` sigue siendo `54faa7df993e05cebee38fc072c2d5be028587eea123ee7bf55d41cc14c3ae59`. Se usa el mismo transporte que ya funcionaba para imágenes y GIF, sin nuevos comandos nativos.

## Pruebas automáticas

**102 pruebas superadas**, incluidas las 92 de 2.2. Registro: `artifacts/tests-2.3.0.log`.

- GIF con duraciones variables, zonas estáticas y expansión de fotogramas unidos por el codificador: las cinco partes mantienen el mismo número de fotogramas y cadencia.
- Decodificación real de un MP4 generado con PyAV, selección de inicio, duración y final del archivo.
- Recorte, zoom y giro aplicados a todos los fotogramas; reconstrucción de la vista previa desde los GIF guardados.
- Validación de límites, cancelación, archivos inválidos y partes con distinta duración.
- Conservación de la composición anterior y listas en una escena; copia portátil con medios y velocidad del clip.
- Envío simulado de las cinco partes a su velocidad propia; el GIF normal sigue usando la velocidad global y el decodificador original.
- Conversión asíncrona desde la interfaz, reproducción y búsqueda en la vista previa, guardado, recarga y cancelación; descarte de resultados obsoletos.
- Liberación del archivo GIF de la vista previa al cerrar o cambiar de composición.

## Ejecutable

Compilación PyInstaller correcta en `dist/2.3.0/`, con PyAV y sus DLL de FFmpeg. La prueba del ejecutable terminó con código 0, `frozen: true`, nueve secciones, GIF panorámico y MP4 convertido a diez fotogramas. También se comprobaron las funciones anteriores de calendario, GIF, métricas del PC y lectura multimedia de Windows.

Registro: `artifacts/packaged-ui-2.3.0/smoke-result.json`. Captura revisada del diálogo animado: `artifacts/packaged-ui-2.3.0/18-panorama-video.png`. Los 48 archivos del checkpoint 2.2 coinciden con su manifiesto SHA-256.

## Dispositivo físico

Prueba reversible con configuración temporal: GIF y MP4 de ocho fotogramas a 2 FPS, recortados desde la mitad inferior de una imagen de 640 × 256. Cada pantalla muestra su número, un contador y una barra en movimiento. Las cinco partes se cargaron usando el motor normal y sus GIF guardados.

Todas las peticiones fueron aceptadas con `error_code: 0`; se restauró la composición original y se comprobó que los bytes de la configuración del usuario no cambiaron. Registro: `artifacts/live-test-2.3.0.json`.

**Confirmación visual del usuario: «Sí, se animan las cinco».** Esta confirmación valida la animación en las cinco pantallas; no establece sincronización exacta entre ellas.

## Límites

Los cinco GIF comparten duración y cadencia, pero **no se garantiza inicio simultáneo ni sincronización física**: el transporte envía una pantalla cada vez. La vista previa sí reproduce las cinco partes juntas. No se añade transmisión de vídeo en directo ni audio.

Archivos locales de hasta 100 MB, 30 s y 120 fotogramas por parte; 1, 2, 4, 5 o 10 FPS. Máximo 20 megapíxeles por fotograma. Los códecs dependen de FFmpeg incluido en PyAV 18.1.0. La prueba de vídeo usa MP4/MPEG-4; no implica que se hayan probado todas las combinaciones de contenedor y códec. El giro es manual. La conversión comprueba cancelación y límite de tiempo entre fotogramas, no puede interrumpir instantáneamente una llamada bloqueada en el decodificador.

Referencias de implementación: [PyAV: contenedores, seek y decode](https://pyav.org/docs/stable/api/container.html) y [Pillow: GIF](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#gif).
