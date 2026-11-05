import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.etf_research import engine, run_single


class ResearchHomePathsTests(unittest.TestCase):
    def test_research_paths_follow_home(self):
        try:
            with tempfile.TemporaryDirectory() as folder:
                with patch.dict(os.environ, {'HERMES_HOME': folder}):
                    importlib.reload(engine)
                    self.assertEqual(engine.DEFAULT_INPUT, Path(folder) / 'cache/grid-broad-20260923')
                    self.assertEqual(engine.DEFAULT_OUTPUT, Path(folder) / 'cache/grid-research')
        finally:
            importlib.reload(engine)

    def test_single_uses_engine_output_directory(self):
        # Exercise main with simulated data only; no network or real state.
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(engine, 'DEFAULT_OUTPUT', Path(folder)), patch.object(run_single, 'run', return_value={'code': 'test'}), patch.object(os.sys, 'argv', ['run_single', 'test']):
                run_single.main()
                self.assertTrue((Path(folder) / 'single_test.json').is_file())
