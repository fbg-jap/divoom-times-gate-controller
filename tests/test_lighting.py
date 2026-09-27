import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from keeper.config import ConfigStore, slot
from keeper.engine import Engine
from keeper.lighting import defaults, payload, from_payload


class LightingTests(unittest.TestCase):
    def test_visual_choices_keep_the_existing_device_payload(self):
        settings = dict(color='#ABCDEF', brightness=73, effect=11, zone=2, on=True, keys=False, cycle=True)
        command = payload(settings)
        self.assertEqual(command, dict(Command='Channel/SetRGBInfo', Color='#abcdef', Brightness=73,
                                      LightList=[{'SelectEffect': 11}], SelectLightIndex=2, OnOff=1, KeyOnOff=0, ColorCycle=1))
        self.assertEqual(from_payload(command), {**settings, 'color': '#abcdef'})

    def test_invalid_lighting_cannot_reach_the_device(self):
        for key, bad_values in {'Color': ['red', '#fff', None], 'Brightness': [-1, 101, True],
                                'SelectLightIndex': [3, -1], 'OnOff': [True, 2],
                                'LightList': [[], [None], [8], [{'SelectEffect': 12}], [{'SelectEffect': 0}, {'SelectEffect': 1}]]}.items():
            for value in bad_values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    from_payload({**payload(defaults()), key: value})

    def test_only_acknowledged_lighting_is_saved_without_changing_screens(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ConfigStore(Path(temp), migrate=False)
            d = store.get_device()
            d['screens'][0] = slot('text', text='Keep my display')
            store.update_device(d)
            engine = Engine(store, demo=True)
            before = copy.deepcopy(store.get_device())
            command = payload({**defaults(), 'effect': 7, 'zone': 1})
            with patch.object(engine, 'command', side_effect=RuntimeError('device rejected')):
                with self.assertRaises(RuntimeError):
                    engine.process('command', d['id'], {'payload': command})
            self.assertEqual(store.get_device(), before)
            engine.process('command', d['id'], {'payload': command})
            saved = store.get_device()
            self.assertEqual(saved['lighting'], from_payload(command))
            self.assertEqual(saved['screens'], before['screens'])
            self.assertEqual(saved['playlists'], before['playlists'])
            self.assertNotIn(d['id'], engine.paused)
            self.assertEqual(ConfigStore(Path(temp), migrate=False).get_device()['lighting'], saved['lighting'])
