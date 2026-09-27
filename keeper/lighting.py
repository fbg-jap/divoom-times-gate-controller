"""Times Gate RGB settings and zone-specific effect descriptions.

Mapping: averhaegen/hacs-divoom-times-gate-dev, docs/RGB_LIGHTS.md,
commit e8475a1485e00340646bcd52f39971ad34429990 (on-device observations).
"""
import re

PALETTE = [
    ('Menta', 'Mint', '#64e6ca'), ('Turquesa', 'Teal', '#00c6b7'), ('Azul', 'Blue', '#5295ff'),
    ('Violeta', 'Violet', '#a799ff'), ('Rosa', 'Pink', '#ff70bd'), ('Rojo', 'Red', '#ff5263'),
    ('Naranja', 'Orange', '#ff9952'), ('Ámbar', 'Amber', '#ffc879'), ('Amarillo', 'Yellow', '#ffe66b'),
    ('Lima', 'Lime', '#b8eb62'), ('Blanco', 'White', '#ffffff'), ('Cálido', 'Warm', '#ffe8c6'),
    ('Pizarra', 'Slate', '#516078'), ('Noche', 'Night', '#101b2b'), ('Carbón', 'Charcoal', '#24252b'),
    ('Negro', 'Black', '#000000'),
]
PRESETS = [
    ('Océano', 'Ocean', '#5295ff', 45, False), ('Aurora', 'Aurora', '#64e6ca', 60, False),
    ('Atardecer', 'Sunset', '#ffc879', 45, False), ('Neón', 'Neon', '#ff70bd', 80, False),
    ('Lectura', 'Reading', '#ffe8c6', 30, False), ('Multicolor', 'Color cycle', '#64e6ca', 60, True),
]

# (Spanish name, English name, Spanish description, English description).
# Combined lighting uses the edge catalogue; the rear catalogue is different.
EDGE_EFFECTS = [
    ('Destellos pastel', 'Pastel sparkle', 'Arcoíris suave que asciende lentamente.', 'Soft rainbow moving slowly upwards.'),
    ('Péndulo', 'Pendulum', 'Alternancia de tonos rojos y naranjas.', 'Alternating red and orange tones.'),
    ('Arcoíris', 'Rainbow', 'Varios colores aparecen y se desvanecen.', 'Several colors fade in and out.'),
    ('Transición de colores', 'Color fade', 'Todas las luces cambian de tono juntas.', 'All lights change color together.'),
    ('Respiración', 'Breathing', 'El color elegido sube y baja de intensidad.', 'The chosen color gently brightens and dims.'),
    ('Luz continua', 'Steady light', 'Luz sin animación; el color de los bordes depende del firmware.', 'Steady light; edge color depends on firmware.'),
    ('Olas', 'Waves', 'Arcoíris alterno entre izquierda y derecha.', 'Rainbow alternating between left and right.'),
    ('Lluvia multicolor', 'Rainbow rain', 'Destellos de colores que se apagan suavemente.', 'Color flashes that fade away.'),
    ('Barrido lateral', 'Side sweep', 'El color elegido recorre los bordes de izquierda a derecha.', 'The chosen color sweeps the edges left to right.'),
    ('Cascada', 'Cascade', 'Ambos lados se iluminan de arriba abajo.', 'Both sides light up from top to bottom.'),
    ('Cohete', 'Rocket', 'Arcoíris giratorio de izquierda a derecha.', 'Spinning rainbow from left to right.'),
    ('Rueda de color', 'Color wheel', 'El color elegido avanza de atrás hacia delante.', 'The chosen color travels from back to front.'),
]
BACK_EFFECTS = [
    ('Arcoíris estático', 'Static rainbow', 'Degradado multicolor sin movimiento.', 'A multicolor gradient without motion.'),
    ('Fuego suave', 'Soft fire', 'Tonos rojos y naranjas alternos.', 'Alternating red and orange tones.'),
    ('Péndulo', 'Pendulum', 'Luces rojas, amarillas y verdes se encienden lentamente.', 'Red, yellow and green lights turn on slowly.'),
    ('Transición arcoíris', 'Rainbow fade', 'Colores que se mezclan lentamente.', 'Colors blending slowly together.'),
    ('Pulso', 'Pulse', 'Toda la luz trasera respira con el color elegido.', 'The whole backlight pulses in the chosen color.'),
    ('Color fijo', 'Solid color', 'El color elegido permanece encendido, sin animación.', 'The chosen color stays on without animation.'),
    ('Carrera', 'Chase', 'Puntos más brillantes avanzan de izquierda a derecha.', 'Brighter points chase from left to right.'),
    ('Ida y vuelta', 'Back and forth', 'El color avanza desde los extremos hacia el centro.', 'Color moves from the edges towards the center.'),
    ('Radar', 'Radar', 'Barrido de luces de izquierda a derecha y vuelta.', 'Lights sweep left to right and back.'),
    ('Olas', 'Waves', 'Luces que se acumulan y se desvanecen juntas.', 'Lights build up and fade together.'),
    ('Lluvia', 'Rain', 'Destellos aleatorios del color elegido.', 'Random flashes of the chosen color.'),
    ('Deslizamiento', 'Sliding glow', 'El color aparece suavemente y se desplaza.', 'The color fades in gently and slides along.'),
]
SOLID_EFFECT = 5


def effects_for_zone(zone):
    return BACK_EFFECTS if zone == 2 else EDGE_EFFECTS


def defaults():
    return dict(color='#64e6ca', brightness=50, effect=0, zone=0, on=True, cycle=False, keys=True)


def validate_lighting(settings):
    if not isinstance(settings, dict):
        raise ValueError('Configuración de iluminación inválida')
    value = {**defaults(), **settings}
    if not isinstance(value['color'], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value['color']):
        raise ValueError('Color RGB inválido')
    for key, maximum in [('brightness', 100), ('effect', 11), ('zone', 2)]:
        if type(value[key]) is not int or not 0 <= value[key] <= maximum:
            raise ValueError('Valor de iluminación inválido: ' + key)
    for key in ['on', 'cycle', 'keys']:
        if type(value[key]) is not bool:
            raise ValueError('Estado de iluminación inválido: ' + key)
    return value


def payload(settings):
    s = validate_lighting(settings)
    lights = [{'SelectEffect': 0} for _ in range(3)]
    lights[s['zone']]['SelectEffect'] = s['effect']
    return dict(Command='Channel/SetRGBInfo', Brightness=s['brightness'], Color=s['color'].lower(),
                OnOff=int(s['on']), KeyOnOff=int(s['keys']), ColorCycle=int(s['cycle']),
                SelectLightIndex=s['zone'], LightList=lights)


def from_payload(p):
    expected = {'Command', 'Brightness', 'Color', 'OnOff', 'KeyOnOff', 'ColorCycle', 'SelectLightIndex', 'LightList'}
    if not isinstance(p, dict) or set(p) != expected or p['Command'] != 'Channel/SetRGBInfo':
        raise ValueError('Comando de iluminación inválido')
    lights = p['LightList']
    if (not isinstance(lights, list) or len(lights) not in (1, 3)
            or any(not isinstance(item, dict) or set(item) != {'SelectEffect'}
                   or type(item['SelectEffect']) is not int or not 0 <= item['SelectEffect'] <= 11 for item in lights)):
        raise ValueError('Lista de efectos RGB inválida')
    if type(p['SelectLightIndex']) is not int or not 0 <= p['SelectLightIndex'] <= 2:
        raise ValueError('Zona RGB inválida')
    index = p['SelectLightIndex'] if len(lights) == 3 else 0
    if len(lights) == 3 and any(item['SelectEffect'] != 0 for i, item in enumerate(lights) if i != index):
        raise ValueError('La configuración admite un único efecto principal')
    if any(type(p[k]) is not int or p[k] not in (0, 1) for k in ['OnOff', 'KeyOnOff', 'ColorCycle']):
        raise ValueError('Interruptor RGB inválido')
    return validate_lighting(dict(color=p['Color'], brightness=p['Brightness'], effect=lights[index]['SelectEffect'],
                                  zone=p['SelectLightIndex'], on=bool(p['OnOff']), keys=bool(p['KeyOnOff']), cycle=bool(p['ColorCycle'])))
