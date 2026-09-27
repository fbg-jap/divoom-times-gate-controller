# Divoom Keeper 3.1 · instalación

Keeper puede ejecutarse como escritorio Windows/Linux, servidor web o app autónoma Android/iOS. Todos usan el protocolo HTTP local del Times Gate. El teléfono y el servidor necesitan poder llegar a la IP privada del dispositivo; no se requiere una cuenta Divoom para enviar imágenes.

## Qué comparte cada versión

| Función | Linux escritorio | Docker / portal web | Android / iOS autónomos |
| --- | --- | --- | --- |
| Imágenes y GIF por pantalla | Sí | Sí | Sí |
| Panorámica de imagen, GIF y vídeo con encuadre, zoom y giro | Sí | Sí, conversión en servidor | Sí, conversión en teléfono |
| Escenas, cinco listas, rotación y horarios | Sí, proceso abierto | Sí, contenedor abierto aunque cierres el navegador | Sí, app en primer plano |
| Texto, reloj, tiempo, RSS, ICS, cuenta atrás, servicios y diseño | Sí | Sí | Sí |
| Pomodoro, recordatorios y avisos temporales | Sí | Sí | Sí, app activa |
| Sensores HTTP y MQTT | Sí | Sí | Sí; MQTT necesita WebSocket del broker |
| Home Assistant / órdenes MQTT | Sí | Sí | Sí, app activa; descubrimiento de botones de escenas |
| Métricas CPU/RAM/discos/red | Equipo Linux | Entorno visible al contenedor | No; usar datos externos mediante sensores |
| Música y carátula | MPRIS con `playerctl` | No se accede automáticamente a la sesión del escritorio | No se lee la música de otras apps |
| Temperaturas | Sensores disponibles en `psutil` | Solo sensores expuestos al contenedor | Sensor externo |
| Perfiles por proceso o bloqueo | Procesos locales; bloqueo con `loginctl` si la sesión lo publica | Procesos del contenedor; sin bloqueo del escritorio | No se observan procesos o bloqueo del PC |
| API de integración entrante | API local opcional existente | API opcional existente + API del portal | Sin servidor HTTP entrante; MQTT para órdenes |
| Copia ZIP con medios | Sí | Sí | Sí, importar/exportar con archivos locales |
| Herramientas y controles nativos | Sí, según firmware | Sí, según firmware | Sí, según firmware |
| Colores y panel RGB visual | Sí | Sí | Sí |

La interfaz muestra las limitaciones de la plataforma. No se generan valores ficticios de PC en móvil. Los diseños que importes con métricas del PC deben adaptarse a sensores externos o controlarse desde el equipo que recoge esas métricas.

Las herramientas nativas siguen dependiendo del firmware. El grupo nativo 0 permanece bloqueado porque durante las pruebas anteriores modificaba otras pantallas. Activar un reloj nativo no garantiza datos del PC. No se presenta ese modo como reparado.

## Migrar tus composiciones

1. En Windows 2.3 exporta una copia ZIP desde sus ajustes.
2. Instala la nueva versión y usa **Copias y ajustes → Importar copia**.
3. Comprueba la IP y revisa las funciones que dependen del sistema operativo.
4. Cierra la otra instancia que esté controlando ese mismo Times Gate antes de enviar.
5. Activa la actualización automática si quieres listas y widgets continuos.

La importación conserva una copia anterior de la configuración y desactiva el envío automático y las integraciones. Los ZIP portátiles excluyen credenciales de API/MQTT. Incluyen los archivos de pantallas, listas y escenas; las panorámicas generadas no necesitan el vídeo original. La exportación sirve también para conservar datos antes de desinstalar la app móvil.

## Docker y portal web

Requisitos: Docker Engine con Compose, acceso de red al Times Gate y puerto 8080 disponible. El contexto de construcción incluye los fuentes y `web/package-lock.json`; no incluye copias privadas, imágenes del usuario ni credenciales.

```sh
docker compose up -d --build
docker compose exec keeper cat /data/admin.token
```

Abre `http://IP_DEL_SERVIDOR:8080` e introduce ese token. Se genera al primer arranque y queda dentro del volumen persistente `keeper-data`. Para fijarlo tú mismo, copia `.env.example` a `.env` y define `KEEPER_TOKEN` con al menos 24 caracteres. Si defines esa variable, usa su valor en lugar de leer `admin.token`.

El contenedor corre como usuario 10001 y mantiene datos en `/data`. La interfaz, la conversión y el motor de envío están incluidos en la imagen. No depende de un navegador abierto para seguir ejecutando listas, horarios, widgets o avisos. No uses varias réplicas contra el mismo volumen: el motor y el bloqueo están diseñados para una sola instancia.

La red bridge con salida hacia la LAN permite introducir directamente la IP del Times Gate. El descubrimiento de red puede no atravesar VLAN, aislamiento Wi-Fi o NAT; en ese caso utiliza la IP. El móvil conectado al portal es un cliente del servidor; **el APK autónomo es otra modalidad distinta**.

Por defecto Compose publica el portal en todas las interfaces. `KEEPER_BIND=127.0.0.1` limita el acceso al propio servidor. Para un proxy HTTPS configura `KEEPER_ORIGINS=https://keeper.tu-dominio` con el origen exacto del navegador. Mantén el portal en tu LAN o detrás de un proxy autenticado/HTTPS si lo vas a publicar. Los endpoints `/api/*`, medios y copias requieren el token; `/healthz` solo indica disponibilidad.

```sh
docker compose logs --tail=100 keeper
docker compose down       # conserva el volumen de datos
```

Las estadísticas corresponden al entorno que ve el contenedor: no representan necesariamente los límites de CPU/memoria del servicio ni la sesión del PC. Música, bloqueo de escritorio y sensores de hardware no aparecen automáticamente en Docker. Para datos de otro ordenador usa sensores HTTP/MQTT.

### Servidor sin Docker

Python 3.11+ y Node 22+ (compilación del frontend verificada con Node 24):

```sh
python3 -m venv .venv-server
.venv-server/bin/python -m pip install -r requirements-server.txt
cd web
npm ci
npm run build
cd ..
.venv-server/bin/python server.py --host 0.0.0.0 --port 8080 --data-dir server-data
```

El token queda en `server-data/admin.token`. Para una prueba sin transmitir al Times Gate añade `--demo` y usa otro directorio de datos. En Windows usa `.venv-server\Scripts\python.exe`. `packaging/keeper-server.service` es una plantilla de servicio de usuario systemd: ajusta las rutas antes de instalarla. No utiliza Qt.

La API opcional de integraciones del escritorio (puerto 8787) es distinta de la API autenticada del portal (8080). Compose solo publica 8080. Puedes usar MQTT sin abrir otro puerto entrante. Para clientes de la API del portal el envío es `POST /api/action` con `{"action":"send","device_id":"ID","args":{}}` y cabecera `Authorization: Bearer TOKEN`; devuelve un trabajo que se consulta en `GET /api/jobs/ID`.

## Linux escritorio

Requisitos: distribución Linux con escritorio gráfico, Python 3.11+, `venv` y bibliotecas de Qt. En Debian/Ubuntu:

```sh
sudo apt install python3-venv libgl1 libegl1 libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-xinerama0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 fonts-dejavu-core
bash run_linux.sh
```

El primer arranque crea `.venv-linux` e instala las dependencias. Los datos se guardan en `$XDG_DATA_HOME/divoom-keeper-studio` o `~/.local/share/divoom-keeper-studio`. El autoarranque usa un archivo Desktop Entry en `$XDG_CONFIG_HOME/autostart` o `~/.config/autostart`.

```sh
sudo apt install playerctl    # opcional: música publicada por reproductores MPRIS
bash run_linux.sh --demo
bash build_linux.sh           # genera dist/DivoomKeeperStudio-3.1.0-linux-ARQUITECTURA.tar.gz
```

El empaquetado debe hacerse en Linux para la arquitectura de destino. El paquete contiene el runtime Python/Qt, pero sigue dependiendo de bibliotecas gráficas de la distribución. Algunas sesiones Wayland no ofrecen bandeja; sin ella, cerrar la ventana termina el programa. La detección de bloqueo necesita una sesión con `XDG_SESSION_ID` y `loginctl` que exponga `LockedHint`.

El código, los lanzadores y el workflow permiten compilar en Linux. Consulta los artefactos de una ejecución correcta de GitHub Actions para obtener un binario de CI. El archivo `linux-source.tar.gz` generado por `packaging/bundle_universal.py` es código fuente, no un binario precompilado.

## Android autónomo

El APK debug es instalable para pruebas y contiene interfaz, conversión, almacenamiento y transporte HTTP nativo. Android mínimo 7.0 / API 24. No hay una URL de servidor incrustada ni requiere Docker.

1. Compila el APK con los comandos inferiores o descarga `android-debug-apk` de una ejecución correcta de GitHub Actions; cópialo al teléfono e instálalo. El paquete local de desarrollo se denomina `DivoomKeeper-3.1.0-android-debug.apk`.
2. Conéctalo a una red que alcance al Times Gate.
3. Introduce la IP privada en **Dispositivo** o importa tu ZIP.
4. Prueba primero una imagen en una sola pantalla y después un GIF/panorámica.

El APK usa la firma de depuración. Una distribución de producción necesita un keystore propio y una compilación release; conserva ese keystore para futuras actualizaciones. No se ha publicado en Google Play.

Para recompilar: Node 22+, JDK 21, Android SDK 36 y build-tools 36.0.0. Configura `ANDROID_HOME` o `web/android/local.properties` para tu SDK.

```sh
cd web
npm ci
npm test
npm run build
npx cap sync android
cd android
./gradlew assembleDebug
```

En Windows usa `gradlew.bat`. El resultado está en `web/android/app/build/outputs/apk/debug/app-debug.apk`.

## iOS autónomo

Se entrega el proyecto de Xcode con los mismos fuentes y el transporte HTTP nativo, permisos de red local y declaración de privacidad del plugin de archivos. **No se ha generado un IPA ni probado una instalación en iPhone desde Windows.**

En un Mac con Node 22+, Xcode 26 y sus herramientas:

```sh
cd web
npm ci
npm run build
npx cap sync ios
npx cap open ios
```

En Xcode selecciona el equipo de firma en **Signing & Capabilities**, conecta el iPhone y ejecuta la app. Acepta el acceso a la red local cuando iOS lo solicite. El identificador predeterminado es `com.raishack.divoomkeeper`; ajústalo si tu equipo necesita otro. Para distribución usa Archive y la firma correspondiente de Apple. Las dependencias nativas se resuelven mediante Swift Package Manager.

El HTTP sin TLS se permite porque el endpoint local del Times Gate es `http://IP/post`. No se desactiva la verificación de certificados HTTPS. La app no pide acceso a los archivos del PC ni a las sesiones de otras apps.

## Límites de las apps móviles

- Las tareas se ejecutan **en primer plano**. No se implementa un servicio Android permanente ni se promete ejecución ilimitada en segundo plano en iOS. Al suspenderse la app se detienen las tareas; no se recuperan horarios perdidos como una cola histórica.
- Las imágenes y animaciones ya cargadas permanecen en el Times Gate, que reproduce sus GIF sin el teléfono. Mantén la app abierta durante la transferencia; si se interrumpe, vuelve a enviar la composición.
- El vídeo se convierte con los códecs del teléfono. MP4 H.264 es la primera opción para comprobar compatibilidad; MKV/AVI u otros códecs pueden no abrirse. En escritorio y servidor se usa PyAV.
- Máximo 100 MB por archivo; clips de hasta 30 s y 120 fotogramas por pantalla. A 10 FPS, el máximo es 12 s. No se transmite audio ni vídeo en directo. Cinco subidas secuenciales pueden quedar desfasadas.
- IndexedDB conserva los archivos dentro de la app. Borrar sus datos o desinstalarla elimina esa biblioteca; usa exportación ZIP antes. La exportación nativa abre el diálogo Compartir/Guardar del sistema.
- MQTT móvil necesita una URL `ws://` o `wss://` ofrecida por el broker. Host/puerto TCP son para escritorio/servidor. Las órdenes MQTT retenidas se ignoran para evitar repetir acciones antiguas al conectar.
- Los widgets de PC/música y los perfiles por proceso/bloqueo se indican como no disponibles. Sensores HTTP/MQTT permiten mostrar datos publicados por otro equipo.

## Desarrollo y comprobaciones

```sh
python -m pip install -r requirements.txt -r requirements-server.txt httpx
python -m unittest discover -s tests
cd web
npm ci
npm test
npm run build
```

`?mobile-demo=1` en el portal ejecuta el motor móvil con almacenamiento del navegador y envíos simulados, útil para desarrollo. No conecta con el dispositivo. El modo normal del navegador siempre utiliza el servidor; las apps nativas seleccionan el motor autónomo automáticamente.

`.github/workflows/multiplatform.yml` prepara Windows, Linux, Android, Docker y una app de simulador iOS sin firma. Consulta el resultado de cada ejecución en [GitHub Actions](https://github.com/raishack/divoom-times-gate-controller/actions/workflows/multiplatform.yml); los artefactos solo están disponibles para compilaciones correctas. El job iOS requiere Xcode 26. Un artefacto de simulador no puede instalarse en un iPhone real. Las compilaciones debug de Android pueden usar claves distintas entre equipos/ejecuciones: exporta una copia antes de sustituir una instalación con firma incompatible.

Referencias: [entorno de Capacitor](https://capacitorjs.com/docs/getting-started/environment-setup), [HTTP nativo](https://capacitorjs.com/docs/apis/http), [despliegue de Qt para Python](https://doc.qt.io/qtforpython-6.8/deployment/index.html), [redes de Docker Compose](https://docs.docker.com/compose/how-tos/networking/).
