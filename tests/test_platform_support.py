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
            for name in ('APPIMAGE', 'APPDIR'):
                os.environ.pop(name, None)
            root = Path(folder) / 'My data $test 100%'
            platform.linux_startup(True, root)
            entry = Path(folder) / 'autostart/divoom-keeper-studio.desktop'
            text = entry.read_text(encoding='utf-8')
            self.assertIn('--config-dir', text)
            self.assertIn('\\$test 100%%', text)
            self.assertIn('Terminal=false', text)
            platform.linux_startup(False, root)
            self.assertFalse(entry.exists())

    def test_startup_repeats_the_web_ui_arguments_only_when_given(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'XDG_CONFIG_HOME': folder}):
            for name in ('APPIMAGE', 'APPDIR'):
                os.environ.pop(name, None)
            entry = Path(folder) / 'autostart/divoom-keeper-studio.desktop'
            platform.linux_startup(True, Path(folder) / 'data', ['--ui', 'web'])
            self.assertIn('"--ui" "web" "--minimized" "--config-dir" "', entry.read_text(encoding='utf-8'))
            platform.linux_startup(True, Path(folder) / 'data')
            text = entry.read_text(encoding='utf-8')
            self.assertNotIn('--ui', text)
            self.assertIn('"--minimized" "--config-dir"', text)

    def test_set_startup_passes_the_ui_arguments_set_by_the_shell(self):
        from keeper import startup
        try:
            with patch.object(startup.os, 'name', 'posix'), patch.object(platform, 'linux_startup') as linux:
                startup.set_ui_args([])
                startup.set_startup(True, Path('/x'))
                linux.assert_called_with(True, Path('/x'), [])
                startup.set_ui_args(['--ui', 'web'])
                startup.set_startup(True, Path('/x'))
                linux.assert_called_with(True, Path('/x'), ['--ui', 'web'])
        finally:
            startup.set_ui_args([])

    def test_startup_uses_appimage_path_when_frozen_inside_the_appdir(self):
        with tempfile.TemporaryDirectory() as folder:
            appdir = Path(folder) / 'mount'
            env = {'XDG_CONFIG_HOME': folder, 'APPIMAGE': '/opt/My Apps/Divoom$Keeper.AppImage', 'APPDIR': str(appdir)}
            with patch.dict(os.environ, env), patch.object(platform.sys, 'frozen', True, create=True), \
                    patch.object(platform.sys, 'executable', str(appdir / 'usr/lib/divoom/divoom')):
                platform.linux_startup(True, Path(folder) / 'data')
            text = (Path(folder) / 'autostart/divoom-keeper-studio.desktop').read_text(encoding='utf-8')
            self.assertIn('Exec="/opt/My Apps/Divoom\\$Keeper.AppImage" "--minimized" "--config-dir"', text)
            self.assertNotIn('app.py', text)

    def test_startup_ignores_an_inherited_appimage_variable(self):
        with tempfile.TemporaryDirectory() as folder:
            env = {'XDG_CONFIG_HOME': folder, 'APPIMAGE': '/tmp/evil.AppImage', 'APPDIR': str(Path(folder) / 'mount')}
            entry = Path(folder) / 'autostart/divoom-keeper-studio.desktop'
            with patch.dict(os.environ, env):  # not frozen: a source checkout launched from a shell that inherited the variables
                platform.linux_startup(True, Path(folder) / 'data')
                self.assertNotIn('evil', entry.read_text(encoding='utf-8'))
                self.assertIn('app.py', entry.read_text(encoding='utf-8'))
                with patch.object(platform.sys, 'frozen', True, create=True):  # frozen, but not running from that AppDir
                    platform.linux_startup(True, Path(folder) / 'data')
                self.assertNotIn('evil', entry.read_text(encoding='utf-8'))

    def test_optional_session_sources_report_absence(self):
        with patch.object(platform.shutil, 'which', return_value=None):
            self.assertIsNone(platform.linux_locked())
            self.assertIn('playerctl', platform.linux_music()['status'])

    def test_linux_temperatures_keep_stable_sensor_identifiers(self):
        sensor = SimpleNamespace(label='Package', current=45.5)
        with patch('psutil.sensors_temperatures', return_value={'coretemp': [sensor]}, create=True):
            self.assertEqual(platform.linux_hardware(), [{'Identifier': '/coretemp/temperature/0', 'Name': 'Package', 'SensorType': 'Temperature', 'Value': 45.5}])


class ExternalLaunchTests(unittest.TestCase):
    BUNDLE = "/tmp/.mount_x/usr/lib/divoom/_internal"

    def frozen(self):
        return patch.multiple(platform.sys, frozen=True, _MEIPASS=self.BUNDLE, platform="linux", create=True)

    def test_frozen_environment_drops_bundled_library_paths(self):
        env = {"LD_LIBRARY_PATH": self.BUNDLE, "QT_PLUGIN_PATH": self.BUNDLE + "/plugins", "QT_SCALE_FACTOR": "2",
               "PYTHONHOME": self.BUNDLE, "PATH": "/usr/bin", "DISPLAY": ":0"}
        with self.frozen():
            cleaned = platform.external_environment(env)
        self.assertNotIn("LD_LIBRARY_PATH", cleaned)
        self.assertNotIn("QT_PLUGIN_PATH", cleaned)
        self.assertNotIn("PYTHONHOME", cleaned)
        self.assertEqual((cleaned["QT_SCALE_FACTOR"], cleaned["PATH"], cleaned["DISPLAY"]), ("2", "/usr/bin", ":0"))

    def test_frozen_environment_restores_the_original_library_path(self):
        env = {"LD_LIBRARY_PATH": self.BUNDLE + ":/opt/lib", "LD_LIBRARY_PATH_ORIG": "/opt/lib"}
        with self.frozen():
            cleaned = platform.external_environment(env)
        self.assertEqual(cleaned, {"LD_LIBRARY_PATH": "/opt/lib"})

    def test_unfrozen_environment_is_left_alone(self):
        env = {"LD_LIBRARY_PATH": "/opt/lib", "QT_PLUGIN_PATH": "/x"}
        self.assertEqual(platform.external_environment(env), env)

    def test_open_external_reports_launcher_failure_and_uses_a_clean_environment(self):
        calls = []

        class Process:
            def __init__(self, code=None):
                self.code = code

            def wait(self, timeout=None):
                if self.code is None:
                    raise platform.subprocess.TimeoutExpired("xdg-open", timeout)
                return self.code

        def launch(code):
            def popen(command, **kwargs):
                calls.append((command, kwargs))
                return Process(code)
            return popen

        with self.frozen(), patch.object(platform.shutil, "which", return_value="/usr/bin/xdg-open"), \
                patch.dict(platform.os.environ, {"LD_LIBRARY_PATH": self.BUNDLE}):
            with patch.object(platform.subprocess, "Popen", launch(0)):
                self.assertTrue(platform.open_external("https://example.org"))
            self.assertEqual(calls[-1][0], ["/usr/bin/xdg-open", "https://example.org"])
            self.assertNotIn("LD_LIBRARY_PATH", calls[-1][1]["env"])
            with patch.object(platform.subprocess, "Popen", launch(4)):
                self.assertFalse(platform.open_external("https://example.org"))
            with patch.object(platform.subprocess, "Popen", launch(None)):
                self.assertTrue(platform.open_external("https://example.org", wait=0.01))
            with patch.object(platform.subprocess, "Popen", side_effect=OSError):
                self.assertFalse(platform.open_external("https://example.org"))
        with patch.object(platform.sys, "platform", "linux"), patch.object(platform.shutil, "which", return_value=None):
            self.assertFalse(platform.open_external("https://example.org"))


class LauncherEntryTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "XDG desktop entries")
    def test_writes_an_entry_with_the_wm_class_and_the_icon_once(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from keeper import platform_support
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"XDG_DATA_HOME": temp}):
            platform_support.linux_launcher_entry(Path(temp) / "cfg")
            entry = Path(temp) / "applications" / "divoom-keeper-studio.desktop"
            text = entry.read_text(encoding="utf-8")
            self.assertIn("StartupWMClass=DivoomKeeperStudio", text)
            self.assertIn("Icon=divoom-keeper-studio", text)
            self.assertIn("--config-dir", text)
            self.assertNotIn("--minimized", text)
            self.assertTrue((Path(temp) / "icons" / "hicolor" / "256x256" / "apps" / "divoom-keeper-studio.png").is_file())
            before = entry.stat().st_mtime_ns
            platform_support.linux_launcher_entry(Path(temp) / "cfg")
            self.assertEqual(entry.stat().st_mtime_ns, before)   # unchanged content is not rewritten
