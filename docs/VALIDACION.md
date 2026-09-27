# Validación de Divoom Keeper Studio

Fecha: 27 de septiembre de 2026.

## Corrección 2.0.1 tras el fallo comunicado por el usuario

- Conservada otra copia del código y de los datos de Studio en `backups/studio-before-fix-20260927-191324/`; la copia original 0.1.3 sigue intacta.
- Reproducido el envío al dispositivo real con la clase `DivoomSender` extraída de la copia original, sin arrancar ni modificar la aplicación antigua.
- Restablecidos PicID basados en segundos Unix (crecientes incluso con envíos rápidos), POST independiente, timeout de 10 segundos y espera de 100 ms tras cada fotograma, incluidas imágenes fijas.
- Comparación automatizada del emisor corregido contra una referencia congelada del original: JSON, bytes JPEG, destino, tiempos y URL para JPG, PNG transparente y GIF, en las cinco pantallas. Las pruebas anteriores no detectaban estas diferencias.
- 48 pruebas automatizadas correctas, incluidas las nuevas pruebas de regresión y el guardado del PC nativo sin IDs.
- Envío con el motor corregido a las cinco pantallas reales: 3 imágenes, 1 GIF y 1 imagen con CPU/RAM/GPU. Todos los fotogramas aceptados; `Draw/GetHttpGifId` devuelve el identificador final enviado. Evidencia en `artifacts/device-send-2.0.1.json`.
- Lecturas reales de CPU, RAM, disco, uso y temperatura NVIDIA disponibles; temperatura CPU no disponible en este Windows.
- Ejecutable 2.0.1 probado con salida 0, siete secciones renderizadas, GIF y calendario recurrente. Dentro del ejecutable empaquetado también se obtienen datos reales de CPU, RAM, disco y NVIDIA; evidencia en `artifacts/packaged-ui-2.0.1/smoke-result.json`.
- El modo nativo ya puede enviar métricas a un PC Monitor seleccionado en Divoom sin IDs de la nube. La activación directa bloquea el grupo 0 y no envía un DeviceId ficticio. Se registran los valores enviados.
- El usuario confirma visualmente: «Se ven las imágenes, el GIF y los valores del PC». Esto valida la recuperación del contenido enviado. La documentación de Divoom exige IDs crecientes: el contador anterior con módulo podía retroceder; no se han probado de forma aislada las otras diferencias del transporte.
- La nube devuelve una lista vacía para este dispositivo. Prueba real de activación nativa: reloj 625, grupo 0, pantalla índice 1, seguida de las seis métricas. Ambos comandos devolvieron `error_code: 0`, pero el usuario observó el monitor en dos pantallas sin datos y las otras tres vacías. Se restauró toda la composición y se bloqueó el grupo 0 tanto en la interfaz como en el motor y transporte. La aceptación HTTP no valida la selección de pantalla. Evidencia en `artifacts/native-pc-probe-2.0.1.json`.

## Validación previa de 2.0 (insuficiente para detectar la regresión)

## Realizado

- Copia de los cinco archivos originales y de la configuración previa antes de editar.
- Verificación SHA-256 de los cinco archivos preservados.
- Compilación sintáctica de los módulos Python.
- Comprobación de dependencias con `pip check`.
- El empaquetado excluye DLL ICU incompatibles encontradas en el PATH; Qt utiliza la API ICU de Windows 10/11.
- 40 pruebas automatizadas del núcleo, HTTP, widgets e interfaz (unittest).
- Renderizado de las siete secciones de la interfaz y del tema claro con Qt offscreen.
- Ejecutable final PyInstaller probado: salida 0, siete páginas, decodificación de GIF y calendario recurrente. Resultado en `artifacts/packaged-ui/smoke-result.json` (`frozen: true`).
- Migración de la configuración real en un directorio temporal: un dispositivo y cinco archivos disponibles; original sin cambios y automático desactivado.
- Comprobación de la interfaz a 1120 × 760 sin desplazamiento horizontal.
- Consultas de lectura al dispositivo configurado, recibidas con `error_code: 0`:
  - `Channel/GetAllConf`: brillo 100, 24 horas, °C, sin espejo, pantallas encendidas.
  - `Channel/GetIndex`: cinco índices devueltos.
  - `Device/GetDeviceTime`: hora UTC y local devueltas.

## Alcance

Las consultas reales no cambiaron imágenes, modos, brillo ni ajustes. Las pruebas de escritura se hicieron contra dobles de prueba y un servidor HTTP local que simula el dispositivo. No se ha verificado visualmente el resultado de los nuevos comandos en el Times Gate físico.

Las funciones con mayor dependencia del firmware son RGB, selección de relojes, monitor PC nativo y herramientas por pantalla. La interfaz identifica esas rutas como experimentales o comunitarias. Los widgets generados por Pillow reutilizan el transporte JPEG probado en la aplicación original.

Los errores `offline` que aparecen en algunas pruebas se provocan deliberadamente para verificar recuperación y aislamiento de fallos; no indican que la prueba haya fallado.

Fuentes contrastadas para esta corrección: [protocolo de animaciones](https://docin.divoom-gz.com/web/#/5/133), [selección individual](https://docin.divoom-gz.com/web/#/5/119) y [monitor oficial](https://github.com/DivoomDevelop/DivoomPCMonitorTool/blob/main/DivoomPCMonitorTool/WindowsFormsApplication1/Form1.cs).
