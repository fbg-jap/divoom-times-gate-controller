# Divoom Times Gate Controller · Keeper 3.1

Convierte las cinco pantallas de tu **Divoom Times Gate** en un escritorio de imágenes, animaciones, datos y avisos. Keeper se comunica por **HTTP en la red local** y conserva tus composiciones para recuperarlas después de una desconexión o reinicio.

**Windows · Linux · Portal web / Docker · Android · iOS**

**Escritorio 3.1.1:** efectos RGB con nombres por zona, acceso a color fijo trasero y recuperación de la iluminación al reconectar. [Uso y detalles de la corrección](docs/RGB-3.1.1.md).

[Primeros pasos](#primeros-pasos) · [Instalación por plataforma](docs/MULTIPLATAFORMA.md) · [Galería de capturas](docs/CAPTURAS.md) · [Historial de cambios](CHANGELOG.md) · [Versión original 0.1.3](https://github.com/raishack/divoom-times-gate-controller/releases/tag/v0.1.3)

![Keeper Studio: cinco pantallas con reloj, monitor PC, texto, tiempo y red](docs/screenshots/screens.png)

*Captura real de la interfaz en modo demo, con datos de ejemplo. Las vistas previas representan contenido generado por Keeper; no son fotografías del dispositivo.*

## Qué puedes hacer

| Función | Para qué sirve |
| --- | --- |
| **Cinco pantallas independientes** | Combinar imágenes, GIF y widgets; enviar una pantalla o la composición completa. |
| **Panorámicas de imagen, GIF y vídeo** | Repartir una composición entre las cinco pantallas, elegir la zona visible y ajustar encuadre, zoom, giro y duración. |
| **Listas por pantalla** | Alternar imágenes y widgets con una duración distinta para cada elemento. |
| **Monitor del PC** | Mostrar CPU, RAM, GPU disponible, gráficas, tráfico de red, discos y temperaturas disponibles. |
| **Widgets** | Reloj, texto, tiempo, cuenta atrás, estado HTTP, calendario ICS, noticias RSS/Atom, música compatible, Pomodoro y sensores. |
| **Diseñador visual** | Crear pantallas con texto, imágenes, barras y campos dinámicos; mover y ordenar capas. |
| **Escenas y horarios** | Guardar composiciones, rotarlas y programar cambios, brillo o encendido/apagado. |
| **Automatizaciones** | Avisos por umbrales, recordatorios y perfiles según procesos o bloqueo, cuando el sistema los permita. |
| **Iluminación RGB visual** | Elegir colores, ambientes, brillo, zonas y efectos mediante muestras, deslizadores y tarjetas. |
| **Integraciones** | API local, MQTT y Home Assistant; datos de sensores HTTP/MQTT. |
| **Copias portátiles** | Exportar e importar configuración, escenas, listas y medios en un ZIP. |
| **Recuperación automática** | Conservar el contenido deseado y reenviarlo periódicamente o al recuperar la conexión. |

Las funciones continuas necesitan que el motor esté ejecutándose. En escritorio permanece en la bandeja cuando la sesión lo permite; en Docker sigue funcionando aunque cierres el navegador; en móvil depende de mantener la app activa.

## Novedades de 3.1: colores y RGB sin escribir códigos

- Paleta de **16 colores**, selector de tono y área para ajustar saturación/luminosidad.
- Colores recientes durante la sesión y botones para confirmar o cancelar la elección.
- Vista previa de **color, brillo y zonas** del Times Gate.
- Seis ambientes: **Océano, Aurora, Atardecer, Neón, Lectura y Multicolor**.
- Doce tarjetas para elegir los modos RGB que ya admitía el controlador.
- Controles de bordes, luz trasera, ciclo multicolor, encendido y luz de teclas.
- Los últimos ajustes aceptados se guardan por dispositivo. Elegir una muestra solo cambia la vista previa; **Aplicar iluminación** envía los cambios.
- El mismo selector visual se utiliza en pantallas, listas y diseños de escritorio, web y móvil.

![Panel RGB del portal web: vista previa, paleta, ambientes y tarjetas de efectos](docs/screenshots/rgb-web.png)

En escritorio 3.1.1 los efectos tienen nombres descriptivos según la zona y un acceso directo al color fijo trasero. El portal y las apps móviles conservan **Efecto 1–12**. La vista previa representa el color; las animaciones reales dependen del firmware. [Corrección RGB de escritorio](docs/RGB-3.1.1.md) · [Guía de colores de 3.1](docs/COLORES-3.1.0.md).

## Panorámicas con encuadre y animación

Elige una imagen, GIF o vídeo local y decide **qué zona se muestra**: arrastra el encuadre, desplázalo horizontal/verticalmente, ajusta el zoom o gira 90°. Para animaciones selecciona inicio, duración y FPS, reproduce la vista previa o busca un fotograma concreto.

![Conversión de un vídeo de ejemplo en cinco animaciones panorámicas](docs/screenshots/panorama-video.png)

Al aplicar, Keeper guarda la composición anterior como escena y genera cinco archivos para el dispositivo. Los vídeos se convierten a animaciones sin audio; **no se transmite vídeo en directo**. Las subidas son secuenciales y pueden quedar desfasadas entre pantallas.

Límites: 100 MB por archivo, hasta 30 segundos y 120 fotogramas por pantalla. A 10 FPS el máximo es 12 segundos. Los códecs dependen de PyAV/FFmpeg en escritorio/servidor y del teléfono en móvil.

## Diseña tus propias pantallas

![Diseñador visual con texto dinámico y barra de CPU](docs/screenshots/designer.png)

Mezcla texto, imágenes y barras con campos como `{cpu}`, `{ram}`, `{time}` o `{date}`. El monitor del PC incluye gráficas, red, almacenamiento y temperaturas; los sensores no disponibles se muestran como **N/D**. [Más ejemplos de widgets, listas y automatizaciones](docs/CAPTURAS.md).

## Plataformas y estado

| Plataforma | Cómo se ejecuta | Estado de la versión 3.1 |
| --- | --- | --- |
| **Windows** | App PySide6, bandeja y autoarranque opcional | Ejecutable compilado y probado en demo. Conserva el transporte original de imágenes/GIF. |
| **Linux** | Escritorio con rutas XDG, sensores y MPRIS opcional | Pruebas y binario x86_64 completados en CI; escritorio físico pendiente de validar. |
| **Docker / web** | Portal FastAPI y motor persistente | Portal probado en Windows; imagen construida y arranque comprobado en CI. |
| **Android** | App autónoma Capacitor: conversión y envío desde el teléfono | APK debug compilado; instalación y envío en teléfono físico pendientes. |
| **iOS** | App autónoma con frontend compartido y HTTP nativo | App de simulador compilada en CI. Necesita Mac y firma para instalar en iPhone; teléfono físico pendiente. |

El móvil autónomo **no necesita un servidor Keeper**. Sus funciones continuas dependen del primer plano y de las restricciones de Android/iOS. Los GIF enviados siguen reproduciéndose en el dispositivo. El portal web es otra modalidad: el navegador controla al servidor.

Métricas de PC, música, hardware y perfiles varían entre sistemas. Docker muestra el entorno que ve el contenedor; móvil puede usar sensores externos. Consulta la [comparativa completa y requisitos](docs/MULTIPLATAFORMA.md).

## Primeros pasos

1. Conecta el ordenador, servidor o teléfono a una red que pueda alcanzar al Times Gate.
2. Abre **Dispositivo** e introduce su IP privada; en escritorio también puedes utilizar el descubrimiento LAN.
3. En **Pantallas**, elige una imagen o widget y pulsa **Guardar y enviar**.
4. Activa la actualización automática para widgets, listas, horarios y avisos continuos.
5. Guarda una escena o exporta una copia ZIP antes de experimentar con otra composición.

Para evitar que varios programas sobrescriban las mismas pantallas, utiliza un solo controlador activo por dispositivo.

### Windows desde el código fuente

Python 3.11 o posterior:

```powershell
git clone https://github.com/raishack/divoom-times-gate-controller.git
cd divoom-times-gate-controller
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Para explorar la interfaz sin transmitir al dispositivo:

```powershell
.\.venv\Scripts\python.exe app.py --demo
```

Para compilar un ejecutable portátil:

```powershell
.\build_windows.ps1
```

El resultado está en `dist/DivoomKeeperStudio/`. Copia **toda la carpeta**, incluida `_internal`; el ejecutable compilado no necesita Python instalado.

### Linux

```sh
bash run_linux.sh
# Prueba sin dispositivo:
bash run_linux.sh --demo
```

Instala primero las [bibliotecas de Qt y requisitos de Linux](docs/MULTIPLATAFORMA.md#linux-escritorio).

### Docker y portal web

```sh
docker compose up -d --build
docker compose exec keeper cat /data/admin.token
```

Abre `http://IP_DEL_SERVIDOR:8080` e introduce el token generado. El volumen conserva los datos. También puedes fijar `KEEPER_TOKEN` mediante `.env.example`. [Red, autenticación, copias y servidor sin Docker](docs/MULTIPLATAFORMA.md#docker-y-portal-web).

### Android e iOS

```sh
cd web
npm ci
npm run build
npx cap sync
# Abre el proyecto de la plataforma que vayas a compilar:
npx cap open android
# En un Mac:
npx cap open ios
```

Android requiere JDK 21 y SDK 36. iOS requiere Xcode 26 y firma para instalar en iPhone. [Instrucciones y límites móviles](docs/MULTIPLATAFORMA.md#android-autónomo).

### Descargas y compilaciones

- La [versión original 0.1.3](https://github.com/raishack/divoom-times-gate-controller/releases/tag/v0.1.3) sigue disponible como recuperación.
- El código actual está en esta rama. Los binarios y datos personales no se guardan en Git.
- [GitHub Actions](https://github.com/raishack/divoom-times-gate-controller/actions/workflows/multiplatform.yml) compila Windows, Linux, Android y el simulador iOS, y comprueba Docker. Los artefactos aparecen en cada ejecución que termine correctamente; su disponibilidad depende del resultado de CI. No equivalen a una prueba en hardware físico.
- [Compilación con escritorio 3.1.1 y descargas](https://github.com/raishack/divoom-times-gate-controller/actions/runs/36348139691): los cuatro trabajos terminaron correctamente. Para Windows, descarga **windows-portable** en **Artifacts**: contiene `DivoomKeeper-3.1.1-windows.zip`, con la corrección RGB. Necesitas una sesión de GitHub iniciada. [Novedades y validación](docs/RGB-3.1.1.md).

## Migración, copias y compatibilidad

Keeper Studio utiliza `%APPDATA%/DivoomKeeperStudio/` en Windows, separado de la aplicación original. Al migrar importa los perfiles antiguos y copia los medios disponibles sin modificar la configuración de la 0.1.3. En Linux usa las rutas XDG.

Los ZIP incluyen medios, escenas y listas. Antes de importar se conserva una copia de la configuración anterior y se desactiva el envío automático para revisar el dispositivo. Permiten trasladar composiciones entre escritorio/web/móvil, teniendo en cuenta sus diferencias de funciones.

El historial Git y la release 0.1.3 se mantienen. Para volver a ella, cierra Studio, revisa el autoarranque de la nueva versión y utiliza el ejecutable original. Las copias privadas de desarrollo y los datos de usuario están excluidos del repositorio.

## Qué se ha comprobado

- **126 pruebas Python** aprobadas para el escritorio 3.1.1 y **13 pruebas Node** para el frontend compartido.
- Ejecutable Windows en demo, conversión real de GIF/vídeo de prueba, interfaz web y motor móvil con transporte simulado.
- Compilación Android debug y coincidencia de sus recursos con el frontend web.
- [CI desde un clon limpio](docs/VALIDACION-CI-3.1.0.md): pruebas Windows/Linux, binarios de escritorio, APK Android, app para simulador iOS y construcción/arranque de Docker completados correctamente.
- Confirmación visual previa en el Times Gate de imágenes/GIF, datos del PC renderizados por Keeper, listas y panorámicas de GIF/vídeo en las cinco pantallas.

Las animaciones RGB de la nueva interfaz y el transporte desde teléfonos físicos están pendientes de validación real. Los relojes y herramientas nativas dependen del firmware. **PC Monitor nativo sigue siendo experimental:** el grupo nativo 0 está bloqueado porque alteraba otras pantallas. Para datos del PC comprobados utiliza el widget renderizado por Keeper.

[Validación de 3.1](docs/COLORES-3.1.0.md) · [Multiplataforma 3.0](docs/VALIDACION-3.0.0.md) · [Pruebas físicas de panorámicas](docs/VALIDACION-2.3.0.md).

## Desarrollo

```sh
python -m pip install -r requirements.txt -r requirements-server.txt httpx
python -m unittest discover -s tests
cd web
npm ci
npm test
npm run build
```

Capturas de ejemplo de escritorio: `python app.py --screenshot-dir artifacts/ui`. El modo `?mobile-demo=1` del portal ejecuta el motor móvil con IndexedDB y envíos simulados.

| Carpeta / archivo | Responsabilidad |
| --- | --- |
| `app.py`, `keeper/ui.py`, `keeper/color_ui.py` | Escritorio y controles visuales. |
| `keeper/protocol.py`, `keeper/engine.py` | Transporte HTTP compatible, cola y programación. |
| `keeper/config.py`, `keeper/content.py` | Datos, composiciones, listas y copias. |
| `keeper/widgets.py`, `keeper/extensions.py` | Datos y renderizado de widgets. |
| `keeper/automation.py`, `keeper/integrations.py` | Reglas, API local y MQTT. |
| `server.py`, `keeper/portal.py` | Portal autenticado y API web. |
| `web/src/`, `web/android/`, `web/ios/` | Frontend compartido y apps móviles autónomas. |
| `tests/`, `web/tests/`, `.github/workflows/` | Pruebas y compilaciones automatizadas. |

## Documentación y referencias

- [Galería de capturas](docs/CAPTURAS.md)
- [Guía de escritorio](docs/ESCRITORIO.md)
- [Instalación y diferencias entre plataformas](docs/MULTIPLATAFORMA.md)
- [Colores y RGB](docs/COLORES-3.1.0.md)
- [API, MQTT y Home Assistant](docs/INTEGRACIONES.md)
- [Historial de novedades](CHANGELOG.md)

El envío mantiene la estrategia original: `Draw/SendHttpGif`, fotogramas JPEG en base64 y selección individual de pantalla. Referencias comunitarias: [adiastra/divoom-gaming-gate](https://github.com/adiastra/divoom-gaming-gate), [usausa/divoom-tool](https://github.com/usausa/divoom-tool), [Divoom-PC-Monitor-PowerShell](https://github.com/KallanX/Divoom-PC-Monitor-PowerShell), [divoom-monitor](https://github.com/Pisyukaev/divoom-monitor), [polynomial/divoom-times-gate](https://github.com/polynomial/divoom-times-gate) y [divoom-timesgate-customplugins](https://github.com/f0x1777/divoom-timesgate-customplugins).

No todos los comandos de Pixoo u otros modelos funcionan en Times Gate. Este es un proyecto comunitario independiente de Divoom.

## English overview

Keeper controls the five Times Gate screens over local HTTP. Version 3.1 adds visual color pickers and RGB controls on top of images/GIFs, adjustable image/GIF/video panoramas, per-screen playlists, PC widgets, custom layouts, scenes, schedules and integrations. It includes a Windows/Linux desktop application, a Docker web portal and standalone Android/iOS projects. Mobile apps send directly to the display and require foreground execution for continuous tasks.

The original working [v0.1.3 release](https://github.com/raishack/divoom-times-gate-controller/releases/tag/v0.1.3) remains available. [CI builds with desktop 3.1.1](https://github.com/raishack/divoom-times-gate-controller/actions/runs/36348139691) passed for Windows, Linux, Android and the iOS simulator, including Docker startup. Download `windows-portable` for the Windows RGB fixes. Physical mobile testing and firmware-specific RGB animations remain pending. Native PC Monitor activation is experimental. Use `--demo` to explore the desktop UI without controlling a device; switch the desktop interface to English in Settings.
