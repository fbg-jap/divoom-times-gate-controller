# Divoom Keeper 3.1 · selección visual de colores y RGB

## Uso

- **Windows/Linux:** Dispositivo → Iluminación RGB. Pulsa la muestra de color para abrir la paleta y el selector de tono. Los editores de pantalla, listas y diseños utilizan el mismo selector para texto y fondo.
- **Portal, Android e iOS:** sección Iluminación RGB. Los editores de pantalla, listas y diseños también tienen muestras de color y paleta rápida.
- El selector permite arrastrar por el área de color, mover el tono, elegir entre 16 muestras y recuperar los ocho colores utilizados recientemente durante la sesión. Se puede manejar con teclado. Cancelar conserva el color anterior; Usar color confirma la selección.
- El panel RGB muestra una aproximación del color, brillo y zonas iluminadas del Times Gate. Elige todas las zonas, bordes o luz trasera, mueve el brillo y controla la iluminación, el ciclo multicolor y la luz de las teclas.
- Los seis ambientes rápidos combinan color y brillo: Océano, Aurora, Atardecer, Neón, Lectura y Multicolor. Conservan el efecto y la zona elegidos.
- Las doce tarjetas seleccionan los modos existentes del dispositivo. No hace falta escribir códigos. **No se han asignado nombres de animaciones sin verificar:** Efecto 1–12 corresponde a los identificadores internos 0–11 que ya admitía el controlador. Su animación real depende del firmware y no se simula en la vista previa.
- Pulsa **Aplicar iluminación** para enviar. Elegir colores, ambientes o tarjetas solo cambia la vista previa. Los últimos ajustes aplicados se guardan por dispositivo después de recibir una respuesta correcta. Aplicar RGB no pausa las listas ni cambia la composición de las pantallas.

## Ejecutables y versiones conservadas

Las rutas `dist/`, `backups/` y `artifacts/` de este informe pertenecen a la validación local; sus datos privados no se publican en Git. Para construir desde un clon, utiliza `build_windows.ps1`, `build_linux.sh` y las instrucciones móviles. Los resultados disponibles de CI se encuentran en [GitHub Actions](https://github.com/raishack/divoom-times-gate-controller/actions/workflows/multiplatform.yml). La [release original 0.1.3](https://github.com/raishack/divoom-times-gate-controller/releases/tag/v0.1.3) permanece publicada.

La nueva compilación de Windows está en `dist/3.1.0/DivoomKeeperStudio/DivoomKeeperStudio.exe`. Para copiarla, utiliza `dist/DivoomKeeper-3.1.0-windows.zip` o toda la carpeta, incluida `_internal`. Cierra la instancia anterior desde **Salir** en la bandeja antes de abrir la nueva con los mismos datos. Para explorarla en paralelo sin enviar al dispositivo, ejecútala con `--demo`.

La 2.3 sigue en `dist/2.3.0/`, y los paquetes 3.0 permanecen en `dist/`. La copia del código previa a esta modificación se encuentra en `backups/working-v3.0.0-20260927-214107/`, con manifiesto SHA-256. No se han cambiado la configuración activa, los medios ni el acceso de inicio del usuario durante estas pruebas.

El APK es `dist/DivoomKeeper-3.1.0-android-debug.apk`. Linux, Docker y el proyecto iOS se distribuyen junto con el código 3.1. Sigue las [instrucciones multiplataforma](MULTIPLATAFORMA.md). El paquete Linux contiene código fuente, no un binario compilado. iOS necesita Mac, Xcode y firma.

## Validación local

- 121 pruebas Python: protocolo original, contenidos, panorámicas, configuración, interfaz, portal y motor. Incluyen rechazos de parámetros RGB, conservación de pantallas/listas y persistencia únicamente tras aceptación.
- 13 pruebas Node: motor autónomo, RGB, conversión de colores, validación y transporte móvil.
- Compilación Windows con PyInstaller y prueba del ejecutable en demo: nueve páginas, imágenes/GIF, calendarios, panorámicas GIF/vídeo y proveedores de Windows. Conversión de vídeo de prueba: diez fotogramas por pantalla. Resultado en `artifacts/smoke-3.1.0/smoke-result.json`.
- Compilación Vite y sincronización de sus recursos con Android/iOS. APK debug construido con Gradle y firma comprobada. Los recursos del APK coinciden con la compilación web.
- Interfaz web comprobada en navegador: paleta, aceptar/cancelar, tono, brillo, ambientes, zona, efecto y persistencia después de aplicar en el simulador. Vista de teléfono a 390 px, sin desbordamiento horizontal; consola sin errores.
- No se han enviado pruebas RGB al dispositivo real ni se ha instalado el APK en un teléfono. Linux/Docker e iOS no se han ejecutado en sus sistemas respectivos desde este equipo Windows.

El archivo `keeper/protocol.py`, responsable del envío original de imágenes/GIF, conserva el SHA-256 `54faa7df993e05cebee38fc072c2d5be028587eea123ee7bf55d41cc14c3ae59`.

El comando RGB conserva los campos originales de `Channel/SetRGBInfo`. Las zonas concuerdan con [LightIndex en Divoom.Client](https://github.com/usausa/divoom-tool/blob/6a60147bf5bb17b25cc603fa5252a78f4c4a0c46/Divoom.Client/Enums.cs). Esta referencia no proporciona nombres verificados para las animaciones de los doce modos.
