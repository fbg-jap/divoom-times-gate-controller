# Historial de cambios

Las versiones 2.x y 3.0 se desarrollaron y comprobaron localmente. Esta actualización publica su evolución junto con la 3.1; no implica que existan releases binarias separadas para cada versión.

## 3.1.1 · Corrección RGB de escritorio

- Efectos con nombres y descripciones específicos para bordes y luz trasera.
- Acceso directo a color fijo trasero sin ciclo multicolor y modo de luz continua en los bordes, con límites de color del firmware explicados.
- Corregido el direccionamiento de efectos mediante las tres entradas de `LightList`.
- Recuperación del último ajuste RGB aceptado al iniciar o reconectar, sin detener imágenes/GIF si falla el comando RGB.
- 125 pruebas Python. [Uso y validación](docs/RGB-3.1.1.md).

## 3.1.0 · Colores y RGB visuales

- Selector de tono y saturación/luminosidad, paleta de 16 muestras y ocho colores recientes por sesión.
- Selección visual en pantallas, listas, diseñador y panel RGB de escritorio/web/móvil.
- Vista previa de color, brillo y zonas; seis ambientes rápidos.
- Tarjetas para los doce efectos existentes, encendido, ciclo multicolor y luz de teclas.
- Persistencia por dispositivo tras aceptación. Aplicar RGB no pausa las pantallas ni cambia sus listas.
- 121 pruebas Python y 13 Node; compilaciones locales Windows y APK debug Android.
- Publicación del código completo, guías por plataforma y 14 capturas de ejemplo.
- Compilaciones Windows/Linux/Android/iOS simulador y arranque Docker verificados en GitHub Actions. Corregidos el archivo de dependencias web, la instalación del SDK Android y el ancho de los botones de Actividad en Linux.

## 3.0.0 · Multiplataforma

- Escritorio Linux con rutas XDG, autoarranque, MPRIS opcional y adaptación de métricas y sesión.
- Portal FastAPI autenticado, biblioteca privada, edición con revisión y una sola cola de envío.
- Docker con volumen persistente, conversión de medios y motor independiente del navegador.
- Android/iOS autónomos: Capacitor, HTTP directo al Times Gate, almacenamiento y conversión locales.
- Migración, ZIP portátiles y soporte móvil de sensores/MQTT WebSocket.
- Limitaciones por plataforma visibles; tareas móviles en primer plano.

## 2.3.0 · GIF y vídeo panorámicos

- Recorte de GIF/vídeo, selección de inicio/duración/FPS y generación de cinco GIF.
- Vista previa animada, pausa y búsqueda de fotogramas; conversión en segundo plano.
- Conservación de cadencia y de la composición anterior como escena.
- Animación confirmada en las cinco pantallas; sin garantía de sincronización física exacta.

## 2.2.0 · Encuadre, diseño y automatizaciones

- Encuadre panorámico mediante arrastre, desplazamiento, zoom y giro.
- Música de Windows, RSS/Atom y diseñador de texto/imágenes/barras.
- Pomodoro, alertas, recordatorios y perfiles por proceso/bloqueo.
- API local, MQTT, Home Assistant y sensores adicionales.

## 2.1.0 · Listas y monitor avanzado

- Listas independientes por pantalla con duración por elemento.
- Vistas de PC con gráficas, red, discos y temperaturas disponibles.
- Panorámicas de imagen fija y rotación de escenas.

## 2.0 / 2.0.1 · Keeper Studio

- Interfaz renovada con temas, editor por pantalla, escenas y horarios.
- Widgets locales, avisos, controles y herramientas del dispositivo.
- Biblioteca propia, migración del perfil original y copias portátiles.
- Corrección del envío para conservar el método de imágenes/GIF que funcionaba en la 0.1.3.
- Separación del monitor PC de Keeper y la activación nativa experimental; bloqueo del grupo nativo 0.

## 0.1.3 · Aplicación original

- Cinco medios persistentes, imágenes/GIF, envío manual/periódico y recuperación al arrancar.
- Descubrimiento LAN, selección de dispositivo, perfiles, bandeja, estado y autoarranque.
- [Release original conservada](https://github.com/raishack/divoom-times-gate-controller/releases/tag/v0.1.3).
