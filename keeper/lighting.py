"""RGB settings; the device effect IDs deliberately have no invented names."""
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
    return dict(Command='Channel/SetRGBInfo', Brightness=s['brightness'], Color=s['color'].lower(),
                OnOff=int(s['on']), KeyOnOff=int(s['keys']), ColorCycle=int(s['cycle']),
                SelectLightIndex=s['zone'], LightList=[{'SelectEffect': s['effect']}])


def from_payload(p):
    expected = {'Command', 'Brightness', 'Color', 'OnOff', 'KeyOnOff', 'ColorCycle', 'SelectLightIndex', 'LightList'}
    if not isinstance(p, dict) or set(p) != expected or p['Command'] != 'Channel/SetRGBInfo':
        raise ValueError('Comando de iluminación inválido')
    if (not isinstance(p['LightList'], list) or len(p['LightList']) != 1
            or not isinstance(p['LightList'][0], dict) or set(p['LightList'][0]) != {'SelectEffect'}):
        raise ValueError('Selecciona un único efecto RGB')
    if any(type(p[k]) is not int or p[k] not in (0, 1) for k in ['OnOff', 'KeyOnOff', 'ColorCycle']):
        raise ValueError('Interruptor RGB inválido')
    return validate_lighting(dict(color=p['Color'], brightness=p['Brightness'], effect=p['LightList'][0]['SelectEffect'],
                                  zone=p['SelectLightIndex'], on=bool(p['OnOff']), keys=bool(p['KeyOnOff']), cycle=bool(p['ColorCycle'])))
