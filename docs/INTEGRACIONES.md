# Integraciones de Studio 2.2

Studio debe permanecer abierto. Las integraciones están desactivadas inicialmente y se configuran desde **Integraciones → Guardar integraciones**. No cambian el protocolo de envío del Times Gate.

## API local

Activa la API y copia su token. Por defecto escucha únicamente en `127.0.0.1:8787`. La opción de red local escucha en todas las interfaces; Studio no modifica el firewall. Usa HTTP solo en una red de confianza; para acceso remoto, utiliza una VPN o un proxy HTTPS autenticado.

Todas las peticiones necesitan `Authorization: Bearer TU_TOKEN`. No acepta comandos arbitrarios del firmware ni ejecución de programas. Máximo 16 KiB por petición; no admite peticiones desde páginas web con cabecera Origin.

Ejemplo PowerShell, solicitando el token sin dejarlo escrito en el historial:

```powershell
$keeperToken = Read-Host 'Token de Studio'
$keeperHeaders = @{ Authorization = "Bearer $keeperToken" }
Invoke-RestMethod 'http://127.0.0.1:8787/v1/status' -Headers $keeperHeaders
$keeperBody = @{ action = 'notice'; panel = 3; text = 'Descansa un momento'; seconds = 15 } | ConvertTo-Json
Invoke-RestMethod 'http://127.0.0.1:8787/v1/action' -Method Post -Headers $keeperHeaders -ContentType 'application/json' -Body $keeperBody
```

`GET /v1/status` devuelve los identificadores de dispositivos y escenas, sin credenciales. `POST /v1/action` acepta:

| action | Campos |
| --- | --- |
| `notice` | `panel`: 1–5, `text`: hasta 500 caracteres, `seconds`: 5–300; opcionales `title`, `buzzer` |
| `scene` | `scene_id`: un ID existente |
| `brightness` | `value`: 0–100 |
| `power` | `on`: booleano `true` o `false` |
| `send` | Reenvía la composición |

Todas admiten `device_id`; si se omite, usan el dispositivo seleccionado en Studio. Una respuesta **202** significa que la orden está en cola. El resultado del envío se consulta en Actividad; no equivale a confirmación visual en la pantalla. Una cola llena devuelve 503. Las acciones explícitas por API/MQTT pueden ejecutarse con la actualización automática desactivada; los avisos siguen necesitando una pantalla encendida con imagen o widget restaurable.

## MQTT y Home Assistant

Configura el servidor, puerto, usuario y contraseña del broker que utiliza Home Assistant. Activa TLS si corresponde: valida el certificado con las autoridades del sistema. El prefijo debe ser único por instalación, por ejemplo `keeper_escritorio`.

Con MQTT Discovery activo en Home Assistant, aparecerá un dispositivo por Times Gate con botones para sus escenas y para reenviar su composición. Studio publica:

- `PREFIJO/availability`: `online` / `offline`, con último testamento.
- `PREFIJO/status`: resumen sin credenciales, cada 30 segundos.
- `homeassistant/button/keeper_DEVICE_SCENE/config`: descubrimiento de botones.

Envía órdenes JSON a `PREFIJO/command`, con los mismos campos que la API. **No utilices retain** en órdenes: Studio descarta las órdenes retenidas al recibirlas para evitar reejecutarlas al reconectar.

### Mostrar un sensor de Home Assistant

Home Assistant debe publicar el valor en un tema. Studio no puede deducir automáticamente todas las entidades de Home Assistant solo por conectarse al broker.

Ejemplo de automatización que publica la temperatura elegida; sustituye `sensor.temperatura_salon` por tu entidad real:

```yaml
alias: Temperatura del salón para Keeper
triggers:
  - trigger: state
    entity_id: sensor.temperatura_salon
  - trigger: time_pattern
    minutes: "/1"
actions:
  - action: mqtt.publish
    data:
      topic: keeper_escritorio/sensor/salon
      payload: "{{ states('sensor.temperatura_salon') }}"
      retain: true
```

En Studio, selecciona **Sensor MQTT / hardware**, fuente MQTT, tema `keeper_escritorio/sensor/salon`, campo JSON vacío y unidad `°C`. Si publicas `{"temperature":23.5}`, usa `temperature` como campo. También admite rutas como `data.temperature` y posiciones de listas como `values.0`. Las lecturas caducan según el intervalo configurado; después muestran N/D. La caducidad se calcula desde la recepción, por lo que un valor retenido cuenta como recién recibido al reconectar.

Studio se suscribe a los temas concretos utilizados por widgets, listas, escenas y alertas, además de `PREFIJO/sensor/#`. MQTT no necesita el token de la API: usa la autenticación y los permisos del broker. Los botones de Discovery quedan almacenados en el broker al cerrar Studio y aparecen no disponibles hasta la siguiente conexión.

## LibreHardwareMonitor

Abre [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) y activa la lectura en Studio. Su proveedor WMI `root\LibreHardwareMonitor` debe estar disponible. **Actualizar lista de sensores** muestra nombre, tipo, identificador y lectura; la primera consulta se realiza en segundo plano, por lo que puede necesitar unos segundos.

Para un widget Sensor, elige LibreHardwareMonitor y pega el identificador exacto. Para una alerta, elige métrica Sensor numérico, fuente LibreHardwareMonitor e identificador. Las temperaturas CPU/GPU disponibles se incorporan también al widget PC. No todos los sensores están disponibles en todos los equipos; Studio no instala ni carga controladores y no solicita elevación.

## Música

Utiliza la sesión multimedia actual que expone Windows. Se han comprobado metadatos y carátula en este PC. Algunos reproductores no publican sesión, artista o imagen; en ese caso solo se muestra la información disponible. No controla el audio ni inicia reproducción.

## Credenciales y copias

El token de API y la contraseña MQTT se guardan en la configuración local del usuario. Las exportaciones portátiles los omiten y desactivan las integraciones; tras importar hay que configurarlas de nuevo. Las copias completas del directorio de datos, como cualquier copia manual, pueden contener las credenciales que existían en ese momento.

## Referencias

- [Microsoft: sesiones multimedia de Windows](https://learn.microsoft.com/en-us/uwp/api/windows.media.control).
- [PyWinRT: operaciones asíncronas y tipos](https://pywinrt.readthedocs.io/en/stable/types.html).
- [Microsoft: notificaciones de bloqueo y desbloqueo](https://learn.microsoft.com/en-us/windows/win32/termserv/wm-wtssession-change).
- [Paho MQTT para Python](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html).
- [Home Assistant MQTT](https://www.home-assistant.io/integrations/mqtt/).
