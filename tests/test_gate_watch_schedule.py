"""The gate observer uses an AH-only script and a separate 15-minute schedule."""
import importlib.util
from pathlib import Path
import subprocess
import shutil
import unittest
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parent.parent
INSTALLER = REPO / 'deploy_scripts' / 'register_intraday_gate_watch.ps1'
NS = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}


class GateWatchScheduleTests(unittest.TestCase):
    def test_observer_registered_for_script_only_push(self):
        spec = importlib.util.spec_from_file_location('watch_wrapper_test', REPO / 'deploy_scripts' / 'run_and_push.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIn('gate_watch', module.JOBS)
        self.assertEqual(module.JOBS['gate_watch']['push'], 'on')
        self.assertEqual(module.resolve_script('gate_watch'), REPO / 'deploy_scripts' / 'grid_intraday_gate_watch.py')
        self.assertEqual(module.DEFAULT_HERMES_HOME, REPO / '.cache' / 'grid-home')

    def test_installer_preview_is_non_mutating_weekday_quarter_hour_task(self):
        self.assertTrue(INSTALLER.is_file(), 'observer scheduler installer is missing')
        shell = shutil.which('pwsh') or shutil.which('powershell') or r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
        result = subprocess.run([shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(INSTALLER), '-Preview'],
                                capture_output=True, text=True, encoding='utf-8', timeout=20, check=True)
        task = ET.fromstring(result.stdout.lstrip('\ufeff'))
        trigger = task.find('t:Triggers/t:CalendarTrigger', NS)
        self.assertIsNotNone(trigger)
        self.assertTrue(trigger.findtext('t:StartBoundary', namespaces=NS).endswith('T09:45:00+08:00'))
        self.assertEqual(trigger.findtext('t:Repetition/t:Interval', namespaces=NS), 'PT15M')
        self.assertEqual(trigger.findtext('t:Repetition/t:Duration', namespaces=NS), 'PT5H1M')
        weekdays = trigger.find('t:ScheduleByWeek/t:DaysOfWeek', NS)
        self.assertEqual({n.tag.rsplit('}', 1)[-1] for n in weekdays},
                         {'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'})
        action = task.find('t:Actions/t:Exec', NS)
        self.assertIn('Python312', action.findtext('t:Command', namespaces=NS))
        self.assertIn(str(REPO / 'deploy_scripts' / 'run_and_push.py'), action.findtext('t:Arguments', namespaces=NS))
        self.assertIn('--job gate_watch', action.findtext('t:Arguments', namespaces=NS))
        self.assertEqual(action.findtext('t:WorkingDirectory', namespaces=NS), str(REPO))
        self.assertEqual(task.findtext('t:Settings/t:Enabled', namespaces=NS), 'true')
        self.assertEqual(task.findtext('t:Settings/t:MultipleInstancesPolicy', namespaces=NS), 'IgnoreNew')


if __name__ == '__main__':
    unittest.main()
