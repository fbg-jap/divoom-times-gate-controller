# RGB en escritorio · 3.1.1

En **Dispositivo → Iluminación RGB**, las tarjetas tienen nombres descriptivos y una explicación del movimiento. Cambian al seleccionar **Bordes / Todas las zonas** o **Luz trasera**, porque el Times Gate tiene dos catálogos diferentes.

Para un color sólido, pulsa **Color fijo trasero · sin animación**, elige el color y el brillo y pulsa **Aplicar iluminación**. El acceso directo selecciona la luz trasera, el efecto continuo y desactiva el ciclo multicolor. La app guarda el ajuste solo si el dispositivo lo acepta y lo recupera al arrancar o reconectar, incluso si la actualización de las pantallas está desactivada. No reinicia los efectos en cada comprobación de conexión.

En **Bordes** o **Todas las zonas** existe **Luz continua**, sin animación. La documentación comunitaria indica que el color de ese modo puede estar fijado por el firmware; no se presenta como color personalizado garantizado para los bordes. Un cambio RGB puede afectar a ambas zonas, y el brillo y el encendido son globales.

![RGB de escritorio con nombres y acceso al color fijo](screenshots/rgb-desktop.png)

## Corrección del envío

`Channel/SetRGBInfo` necesita tres entradas en `LightList`: el efecto principal ocupa la posición indicada por `SelectLightIndex`. Antes se enviaba una sola entrada, lo que no seleccionaba correctamente los efectos traseros. Los comandos antiguos de una entrada siguen siendo aceptados por el motor y se convierten al formato correcto antes del envío.

La tabla y las descripciones proceden de las [pruebas documentadas de RGB_LIGHTS.md](https://github.com/averhaegen/hacs-divoom-times-gate-dev/blob/e8475a1485e00340646bcd52f39971ad34429990/docs/RGB_LIGHTS.md). Los nombres en español describen su comportamiento; no son nombres oficiales de Divoom. La vista previa representa color y zona principal, no simula los efectos ni garantiza el estado de la zona secundaria.

## Comprobaciones

- 125 pruebas Python aprobadas; incluyen direccionamiento por zona, compatibilidad de comandos anteriores, persistencia tras aceptación y recuperación RGB sin detener las imágenes/GIF si falla la iluminación.
- Interfaz comprobada en demo y compilación Windows preparada con PyInstaller.
- El Times Gate aceptó una prueba de luz continua violeta para ambas zonas. La apariencia física está pendiente de confirmación del usuario; una respuesta correcta de la API no demuestra el color visible.
- `keeper/protocol.py` mantiene su SHA-256 original: `54faa7df993e05cebee38fc072c2d5be028587eea123ee7bf55d41cc14c3ae59`.

La compilación 3.1.0 y la copia del código anterior permanecen en las carpetas locales `dist/3.1.0/` y `backups/`. La 3.1.1 se genera en `dist/3.1.1/`. Los cambios visuales de esta revisión corresponden al escritorio; el portal y las apps móviles conservan su interfaz anterior.
