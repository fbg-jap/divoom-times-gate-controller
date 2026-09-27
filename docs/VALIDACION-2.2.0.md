# Validación 2.2.0

Fecha: 27 de septiembre de 2026.

## Conservación de la versión funcional

- Código, pruebas, documentación, paquete 2.1.0 y datos del usuario preservados en `backups/working-v2.1.0-20260927-200013/`, con manifiesto SHA-256.
- Ejecutable 2.1.0 intacto en `dist/2.1.0/`. La 2.2.0 se compila en `dist/2.2.0/`.
- Recuperación mediante `run_stable_2.1.ps1`, con una copia independiente de los datos y los medios de 2.1 en `compat/2.1.0-data/`. No se escribe sobre el checkpoint.
- `keeper/protocol.py` conserva SHA-256 `54faa7df993e05cebee38fc072c2d5be028587eea123ee7bf55d41cc14c3ae59`, idéntico a 2.1 y 2.0.1.

## Pruebas automáticas

**92 pruebas superadas**, incluidas las 68 anteriores. Registro: `artifacts/tests-2.2.0.log`.

Las ampliaciones comprueban:

- Recorte superior/inferior y horizontal, zoom y concordancia entre vista previa y archivo guardado.
- Edición de RSS, creación de nuevos widgets en listas y arrastre en el diseñador.
- Renderizado de los nuevos widgets, barras, sustitución de métricas y sensores ausentes.
- Inclusión de imágenes del diseñador en las copias portátiles y exclusión de credenciales.
- RSS/Atom, rotación, caché, tamaño máximo y rechazo de entidades XML.
- Sensores MQTT con rutas JSON, datos caducados y selección de identificadores de hardware.
- Alertas sostenidas, rearme, intervalo mínimo y ausencia de falsos avisos por sensores no disponibles.
- Recordatorios tras pausa, avisos en cola y restauración.
- Perfiles con prioridad, procesos sin distinción de mayúsculas y preservación de la composición guardada.
- Pomodoro: pausa, continuación, cambio de fase, descanso largo y reinicio.
- API con servidor HTTP real de pruebas: autenticación, rutas, límites de tamaño, validación de acciones, cola llena y separación entre recepción y envío al dispositivo.
- MQTT con cliente simulado: suscripciones, recepción de sensores, Discovery y descarte de órdenes retenidas.
- Configuraciones inválidas rechazadas sin guardar cambios parciales.

## Ejecutable y aspecto visual

- Compilación PyInstaller correcta; conserva la resolución de ICU de Windows usada en 2.1.
- Prueba del ejecutable empaquetado: salida 0, nueve secciones, calendario recurrente, GIF, CPU/RAM/disco y WinRT.
- Lectura real de la sesión multimedia de Windows: título y carátula presentes, sin registrar su contenido privado en el informe.
- Capturas revisadas: panorámica, diseñador, editor de alertas, automatizaciones, integraciones y nuevos widgets. Directorios: `artifacts/ui-2.2.0/` y `artifacts/packaged-ui-2.2.0-final/`.

## Dispositivo físico

Prueba reversible con configuración temporal: dos encuadres panorámicos («ARRIBA» y «ABAJO»), música real, diseño con métricas reales del PC, Pomodoro, una fuente RSS local de prueba y un sensor simulado identificado como prueba. Aviso mediante la API HTTP local en la pantalla 3. El registro de ejecución, restauración y conservación de la configuración está en `artifacts/live-test-2.2.0.json`.

La ejecución terminó correctamente: todas las peticiones al dispositivo devolvieron `error_code: 0`, la API respondió 202 y la composición se restauró con la configuración intacta.

La confirmación visual del usuario se registra por separado en ese archivo; la aceptación HTTP no equivale a validación visual.

## Límites de la validación

- No hay un broker/Home Assistant del usuario configurado en este entorno; MQTT se valida con simulación, no contra su instalación real.
- El proveedor WMI de LibreHardwareMonitor no está disponible en este equipo durante la prueba. Su lectura se comprueba con datos simulados y se mantiene N/D cuando falta.
- Los perfiles de bloqueo se comprueban mediante el estado de sesión simulado; no se ha bloqueado el escritorio del usuario durante la prueba.
- La panorámica sigue siendo fija. No se promete sincronización de animaciones entre pantallas.
- Las funciones nativas experimentales permanecen con las mismas restricciones; no se han añadido comandos nativos nuevos.
- Las reglas y widgets requieren Studio abierto; las actualizaciones y automatizaciones requieren el envío automático. Las integraciones externas se activan solo al configurarlas.
