import subprocess
import sys
import unittest

class FrozenCalendarTests(unittest.TestCase):
    def test_calendar_works_with_bundled_tools_shadow(self):
        code = "import sys,types;sys.modules['tools']=types.ModuleType('tools');from datetime import datetime;from confirmed_runtime import phase;assert phase(datetime(2026,10,14,10,0))=='execute'"
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
