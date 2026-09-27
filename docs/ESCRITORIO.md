# Guía de escritorio

[Volver al README](../README.md) · [Instalación por plataforma](MULTIPLATAFORMA.md)

## Primeros pasos

1. Cierra la aplicación original desde su bandeja antes de activar los envíos de Studio. Dos controladores podrían sobrescribir el contenido entre sí.
2. En **Dispositivo**, revisa la IP importada o utiliza la búsqueda LAN. El descubrimiento vía Divoom es una opción separada que consulta sus servidores y permite obtener MAC y DeviceId.
3. En **Pantallas**, selecciona una tarjeta, elige contenido y pulsa **Guardar y enviar**. Cambiar de pantalla guarda los cambios válidos pendientes.
4. Activa **Actualización automática** cuando quieras mantener imágenes y widgets. Esta opción se configura por dispositivo; varios dispositivos pueden funcionar simultáneamente.
5. Guarda tus composiciones en **Escenas** y añade rotación o **Horarios** si lo necesitas.

Cerrar la ventana la oculta en la bandeja cuando esta está disponible. Utiliza **Salir** en el menú de la bandeja para finalizar los envíos. Sin bandeja, cerrar la ventana termina la aplicación.

## Funciones

### Pantallas y biblioteca

- Cinco pantallas configurables por dispositivo y vistas previas de contenido generado.
- Imágenes PNG, JPEG, BMP, WebP y GIF; previsualización animada de GIF.
- Ajustes de encajar con bandas, recortar o estirar; los perfiles antiguos conservan el ajuste estirado original.
- Imágenes y animaciones enviadas como **JPEG 128 × 128 en base64**, con `LcdArray`, `PicNum`, `PicOffset`, `PicID` y `PicSpeed`, manteniendo el protocolo original.
- Calidad JPEG y duración por fotograma configurables por dispositivo. La velocidad es uniforme y no reproduce duraciones distintas del GIF original.
- Salto de fotogramas para reducir transferencias. Límite explícito de 600 fotogramas por envío y 100 MB por archivo importado.
- Biblioteca propia: mover el archivo de origen después de guardarlo no rompe el perfil.
- Pantallas sin gestionar / nativas: Studio no sube contenido a esas pantallas.

### Widgets

| Widget | Fuente / comportamiento |
| --- | --- |
| Texto | Renderizado local, color, fondo y tamaño de letra ajustable |
| Reloj | Zona horaria IANA, por ejemplo `Europe/Madrid`; cambio estacional a través de tzdata |
| PC | CPU/RAM/GPU, gráficas, tráfico de red, disco seleccionable y temperaturas disponibles; GPU NVIDIA mediante `nvidia-smi` |
| Tiempo | Open-Meteo, coordenadas, temperatura, humedad y estado; caché de 10 minutos |
| Cuenta atrás | Fecha/hora objetivo; no emite sonido por sí misma |
| Calendario | URL ICS o archivo local; próximo evento en 7 días, incluyendo recurrencias; caché de 5 minutos |
| Servicio | URL HTTP/HTTPS, estado y latencia; timeout de 4 segundos, caché de 15 segundos |
| Monitor PC nativo | Envía datos al PC Monitor elegido en la app Divoom sin IDs de la nube; activación del reloj 625 desde Studio experimental |

Los widgets se generan en el PC: Studio debe permanecer abierto para actualizarlos. Su intervalo mínimo es 5 segundos, aunque cada fuente puede aplicar una caché mayor. No son aplicaciones instaladas en el firmware.

Los sensores ausentes se muestran como N/D. La temperatura de CPU mediante psutil depende del sistema operativo; en Windows normalmente no está disponible. GPU/temperatura NVIDIA requiere `nvidia-smi`. No se instala ningún controlador de hardware.

Para usar **Monitor PC nativo**, selecciona primero PC Monitor en la pantalla deseada desde la app Divoom, elige aquí **Enviar datos al monitor ya elegido** y pulsa **Guardar y enviar**. Activa **Actualización automática** para mantener los datos al día. Este modo envía las seis métricas por HTTP local sin consultar la nube. La opción **Intentar activar el reloj 625** permite probar la activación directa: requiere un grupo LcdIndependence válido del catálogo. El grupo 0 está bloqueado porque en la prueba real alteró varias pantallas y no actualizó datos. DeviceId solo se envía si está configurado. La activación directa no está validada en este dispositivo. **Estadísticas del PC** genera su propia imagen y evita esa dependencia.

La versión 2.0.1 recupera el transporte del original: `PicID` basado en segundos Unix y creciente entre envíos, POST independiente, timeout de 10 segundos y pausa de 100 ms después de cada fotograma, también en imágenes fijas. El ajuste **Estirar** conserva la conversión de imagen original. Hay pruebas de comparación con el emisor original preservado; la aceptación HTTP no sustituye la confirmación visual en el equipo.

Open-Meteo requiere Internet; información y atribución: <https://open-meteo.com/>. Calendarios y URLs de servicios solo se consultan si el usuario los configura.

### Dispositivo y herramientas

- Brillo de pantalla, encendido/apagado de las pantallas, espejo, 12/24 horas y °C/°F.
- Sincronización UTC con el PC y envío de su desplazamiento horario actual. La zona nativa no se resincroniza automáticamente en cambios estacionales; los widgets de reloj sí usan zona IANA.
- RGB: selector visual de color, brillo, tarjetas de efectos, zonas, ambientes rápidos, ciclo multicolor y luz de teclas. Compatibilidad comunitaria dependiente del firmware.
- Temporizador, cronómetro, marcador, medidor de ruido y buzzer.
- Destino por pantalla experimental para temporizador y marcador; cronómetro/medidor se envían globalmente.
- Avisos temporales con restauración de la imagen/widget anterior y pitido opcional. No se superponen a pantallas nativas sin contenido restaurable.
- Consulta de ajustes/canales y reinicio manual con confirmación.
- Relojes nativos completos o individuales y consulta del catálogo de cinco pantallas. Requieren IDs válidos y pruebas en el firmware concreto.

Las herramientas nativas que sustituyen el contenido **pausan el reenvío para ese dispositivo**. Aplicar iluminación RGB no pausa las pantallas. Usa **Restaurar composición** o **Enviar todo** para volver a los widgets/imágenes. La pausa y el apagado se conservan entre reinicios. La respuesta `error_code: 0` confirma aceptación del comando, no prueba por sí sola su efecto visual.

### Escenas, horarios y recuperación

- Escenas completas de cinco pantallas, renombrado y eliminación.
- Rotación por dispositivo de las escenas marcadas, en el orden de la lista.
- Horarios diarios, entre semana o fin de semana: aplicar escena, ajustar brillo, encender o apagar pantallas.
- Se usa la hora local del PC. Studio debe estar ejecutándose y el dispositivo tener la actualización automática activada. Los horarios perdidos con el PC apagado no se reproducen después.
- Huellas del contenido para evitar subidas idénticas en cada actualización; reenvío de recuperación a intervalos configurables (60 minutos por defecto).
- Comprobación de conexión cada 30 segundos para dispositivos automáticos. Al recuperar conexión se invalida la caché y se restaura el contenido gestionado, salvo pausa/apagado.
- No se cambia automáticamente a otro Divoom si falla un envío. Una IP cambiada debe corregirse seleccionando explícitamente el dispositivo.
- Una sola cola de comunicación evita transferencias simultáneas desde la propia aplicación. Las solicitudes de red se ejecutan fuera del hilo de la interfaz.
