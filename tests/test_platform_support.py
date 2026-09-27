import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from keeper import platform_support as platform


class LinuxSupportTests(unittest.TestCase):
    def test_xdg_data_path_and_windows_compatibility(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = SimpleNamespace(name='posix', getenv=lambda key, default=None: folder if key == 'XDG_DATA_HOME' else default)
            with patch.object(platform, 'os', fake):
                self.assertEqual(platform.data_directory(), Path(folder) / 'divoom-keeper-studio')
            fake = SimpleNamespace(name='nt', getenv=lambda key, default=None: folder if key == 'APPDATA' else default)
            with patch.object(platform, 'os', fake):
                self.assertEqual(platform.data_directory(), Path(folder) / 'DivoomKeeperStudio')

    def test_startup_quotes_paths_and_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'XDG_CONFIG_HOME': folder}):
            root = Path(folder) / 'My data $test 100%'
            platform.linux_startup(True, root)
            entry = Path(folder) / 'autostart/divoom-keeper-studio.desktop'
            text = entry.read_text(encoding='utf-8')
            self.assertIn('--config-dir', text)
            self.assertIn('\\$test 100%%', text)
            self.assertIn('Terminal=false', text)
            platform.linux_startup(False, root)
            self.assertFalse(entry.exists())

    def test_optional_session_sources_report_absence(self):
        with patch.object(platform.shutil, 'which', return_value=None):
            self.assertIsNone(platform.linux_locked())
            self.assertIn('playerctl', platform.linux_music()['status'])

    def test_linux_temperatures_keep_stable_sensor_identifiers(self):
        sensor = SimpleNamespace(label='Package', current=45.5)
        with patch('psutil.sensors_temperatures', return_value={'coretemp': [sensor]}, create=True):
            self.assertEqual(platform.linux_hardware(), [{'Identifier': '/coretemp/temperature/0', 'Name': 'Package', 'SensorType': 'Temperature', 'Value': 45.5}])
