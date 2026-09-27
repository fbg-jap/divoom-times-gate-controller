import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from keeper.config import ConfigStore, slot
from keeper.engine import Engine
from keeper.lighting import defaults, payload, from_payload


class LightingTests(unittest.TestCase):
    def test_effect_is_addressed_to_the_selected_zone(self):
        settings = dict(color='#ABCDEF', brightness=73, effect=11, zone=2, on=True, keys=False, cycle=True)
        command = payload(settings)
        self.assertEqual(command, dict(Command='Channel/SetRGBInfo', Color='#abcdef', Brightness=73,
                                      LightList=[{'SelectEffect': 0}, {'SelectEffect': 0}, {'SelectEffect': 11}], SelectLightIndex=2, OnOff=1, KeyOnOff=0, ColorCycle=1))
        self.assertEqual(from_payload(command), {**settings, 'color': '#abcdef'})
        for zone in range(3):
            with self.subTest(zone=zone):
                command = payload({**settings, 'zone': zone})
                self.assertEqual([v['SelectEffect'] for v in command['LightList']],
                                 [11 if i == zone else 0 for i in range(3)])
                self.assertEqual(from_payload(command)['effect'], 11)

    def test_legacy_one_effect_commands_are_upgraded_before_sending(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ConfigStore(Path(temp), migrate=False)
            engine = Engine(store, demo=True)
            settings = {**defaults(), 'zone': 2, 'effect': 5}
            legacy = {**payload(settings), 'LightList': [{'SelectEffect': 5}]}
            with patch.object(engine, 'command', return_value={'error_code': 0}) as send:
                engine.process('command', store.get_device()['id'], {'payload': legacy})
            self.assertEqual(send.call_args.args[1], payload(settings))

    def test_invalid_lighting_cannot_reach_the_device(self):
        for key, bad_values in {'Color': ['red', '#fff', None], 'Brightness': [-1, 101, True],
                                'SelectLightIndex': [3, -1], 'OnOff': [True, 2],
                                'LightList': [[], [None], [8], [{'SelectEffect': 12}], [{'SelectEffect': 0}, {'SelectEffect': 1}],
                                              [{'SelectEffect': 0}, {'SelectEffect': True}, {'SelectEffect': 0}],
                                              [{'SelectEffect': 0}, {'SelectEffect': 1}, {'SelectEffect': 0}]]}.items():
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

    def test_lighting_restores_once_on_start_and_reconnect_without_auto_screens(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ConfigStore(Path(temp), migrate=False)
            d = store.get_device()
            d.update(ip='192.168.1.10', enabled=False, lighting={**defaults(), 'effect': 5, 'zone': 2})
            store.update_device(d)
            engine = Engine(store, demo=True)
            with patch.object(engine, 'command', return_value={'error_code': 0}) as send:
                engine.tick()
                engine.health(d)
                self.assertEqual([c.args[1] for c in send.call_args_list if c.args[1]['Command'] == 'Channel/SetRGBInfo'], [payload(d['lighting'])])
                with patch.object(engine, 'command', side_effect=RuntimeError('offline')):
                    engine.health(d)
                engine.health(d)
                self.assertEqual(sum(c.args[1]['Command'] == 'Channel/SetRGBInfo' for c in send.call_args_list), 2)
                self.assertFalse(any(c.args[1]['Command'].startswith('Draw/') for c in send.call_args_list))
            self.assertEqual(store.get_device(), d)

    def test_rejected_restore_does_not_mark_the_display_offline(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ConfigStore(Path(temp), migrate=False)
            d = store.get_device()
            d['lighting'] = defaults()
            engine = Engine(store, demo=True)
            with patch.object(engine, 'command', side_effect=[{'error_code': 0}, RuntimeError('RGB rejected')]):
                engine.health(d)
            self.assertTrue(engine.online[d['id']])
            self.assertNotIn((d['id'], d['ip']), engine.lighting_restored)
