# Validación de compilaciones · Keeper 3.1

El 27 de septiembre de 2026 se completó correctamente la [ejecución de GitHub Actions 36347165150](https://github.com/raishack/divoom-times-gate-controller/actions/runs/36347165150), a partir del commit [`1796b3f`](https://github.com/raishack/divoom-times-gate-controller/commit/1796b3f6962a41dcc7afa11617fb9108fcda323a).

| Plataforma | Comprobaciones completadas | Artefacto de la ejecución |
| --- | --- | --- |
| Windows | Instalación limpia, 121 pruebas Python y compilación PyInstaller | `windows-portable` |
| Linux x86_64 | Instalación limpia, 121 pruebas Python, 13 Node, frontend y compilación PyInstaller | `linux-x86_64` |
| Android | Instalación limpia, 13 pruebas Node, frontend, sincronización Capacitor y Gradle | `android-debug-apk` |
| iOS | Instalación limpia, frontend, sincronización Capacitor y compilación Xcode para simulador | `ios-simulator-unsigned` |
| Docker | Construcción de imagen, arranque y respuesta correcta de `/healthz` | Se construye desde el repositorio; no se publicó una imagen en un registro |

Para descargar, abre la ejecución con tu sesión de GitHub iniciada y busca **Artifacts** al final. Los archivos tienen la retención de GitHub Actions; si caducan, vuelve a ejecutar el flujo **Multiplatform builds** o compila desde el código. Las descargas de CI no crean una nueva release y no sustituyen la [versión original 0.1.3](https://github.com/raishack/divoom-times-gate-controller/releases/tag/v0.1.3).

El APK usa firma debug y el artefacto iOS es una app de simulador, no un IPA instalable en iPhone. La instalación y el envío desde teléfonos físicos siguen pendientes. La compilación Linux no sustituye una prueba interactiva del escritorio, y la prueba Docker comprueba el arranque del servicio, no la comunicación con un Times Gate físico.

La primera ejecución permitió corregir tres problemas que no aparecían en el entorno local ya instalado: referencias de dependencias alteradas en `package-lock.json`, un paquete retirado del SDK Android y desbordamiento de los botones de Actividad con las fuentes de Linux. La segunda ejecución verificó las correcciones desde cero. El transporte original de imágenes/GIF de `keeper/protocol.py` conserva sus bytes.

[Validación local y RGB](COLORES-3.1.0.md) · [Instalación](MULTIPLATAFORMA.md) · [Capturas](CAPTURAS.md)
