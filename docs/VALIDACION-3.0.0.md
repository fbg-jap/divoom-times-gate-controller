# Validación de Keeper 3.0

Fecha: 27 de septiembre de 2026. Entorno de trabajo: Windows. Este documento distingue implementación, compilación y pruebas reales en hardware.

## Comprobado

- 115 pruebas Python aprobadas: las 102 previas, 9 del portal y 4 de adaptación Linux. Incluyen el protocolo, las colas, medios, escenas, listas, horarios, avisos, integración, UI Qt y conversión de panorámicas.
- 10 pruebas Node aprobadas: equivalencia del payload HTTP móvil, rechazo de IP/valores inválidos y grupo nativo 0, orden de trabajos, recuperación de errores, duración de listas tras la transferencia, independencia de escenas, Pomodoro, pausa en segundo plano y migración de configuraciones antiguas.
- Frontend Vite compilado y sincronizado con ambos proyectos nativos. Se ha corregido un bloqueo de arranque por un ciclo de importaciones asíncronas.
- APK Android debug 3.0.0 compilado con Gradle 8.14.3, JDK 21 y SDK 36. Es un APK de pruebas con firma de depuración.
- Portal real FastAPI ejecutado en modo demo sobre Windows: autenticación, rechazo de orígenes ajenos, archivos privados, guardado con revisión, conversión panorámica y envío simulado por las cinco pantallas.
- Interfaz revisada en navegador a ancho de teléfono. El motor móvil se ejecutó con IndexedDB y simulación del transporte, sin depender de los endpoints del servidor para generar contenido.
- GIF panorámico local: 8 fotogramas de 200 ms, selección del recorte inferior, vista previa animada y envío simulado a las cinco pantallas.
- MP4 H.264 local: 10 fotogramas, 2 segundos, conversión con el decodificador del navegador y cinco GIF generados.
- Dos guardados/envíos móviles consecutivos comprobados después de corregir la actualización de la revisión tras una orden.
- ZIP exportado por el motor móvil e importado por el `ConfigStore` Python: cinco GIF de 8 fotogramas y velocidad de 200 ms conservados, escenas presentes y envío automático desactivado.
- El módulo `keeper/protocol.py` conserva el SHA-256 de la versión 2.3: `54faa7df993e05cebee38fc072c2d5be028587eea123ee7bf55d41cc14c3ae59`.

Los logs locales están en `artifacts/tests-3.0.0.log`, `artifacts/tests-mobile.log`, `artifacts/android-build-final.log`, `artifacts/web-build-final.log` y `artifacts/portable-check.json`. Los logs no se incluyen en los paquetes distribuibles.

## Pendiente de validar en cada plataforma

| Entorno | Validación pendiente |
| --- | --- |
| Android físico | Instalación del APK, permiso/conectividad LAN, envío real, selección de archivos, compartir ZIP y comportamiento al suspender/reanudar |
| iPhone | Compilación con Xcode, firma, instalación, permiso de red local, HTTP nativo, códecs y exportación |
| Linux | Arranque de Qt en una distribución real, empaquetado PyInstaller, bandeja, autoinicio, sensores, MPRIS y bloqueo de sesión |
| Docker | Construcción y arranque de la imagen con Docker Engine; red hacia el Times Gate y persistencia del volumen |
| MQTT móvil | Broker WebSocket real, autenticación, sensores y descubrimiento en Home Assistant |

El workflow de GitHub está preparado pero no se ha ejecutado aquí. No hay IPA firmado, binario Linux ni imagen Docker preconstruida en esta entrega. La comprobación del portal en Windows no equivale a una prueba de Docker, y la del motor móvil en navegador no equivale a una prueba del APK en Android.

## Compatibilidad conservada

Windows 2.3 sigue en `dist/2.3.0/`, con copia de seguridad previa en `backups/working-v2.3.0-20260927-210000/`. Esta entrega no reemplaza ese ejecutable ni sus datos. Las pruebas nuevas usaron configuración demo independiente y no enviaron contenido al Times Gate físico.

El usuario ya había confirmado en la versión 2.3 la animación panorámica real en las cinco pantallas. Eso valida la base del protocolo y el dispositivo, pero no sustituye la prueba pendiente del transporte nativo de los nuevos teléfonos.

Para la primera prueba en cada plataforma: cerrar el controlador anterior, introducir la IP, enviar una imagen a una sola pantalla, enviar un GIF corto y después una panorámica corta. Revisar la actividad y volver a importar la copia previa si se quiere restaurar la composición.
