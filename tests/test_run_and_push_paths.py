"""DSH 计划任务只跑 AH_analyse 里的脚本，不得调用 hermes-home/scripts 下的部署副本。

2026-11-05 用户指出：run_and_push.py 的 SCRIPTS 指向
D:\\Hermes Agent CN Desktop\\data\\hermes-home\\scripts，DSH 链实际执行的是 Hermes
的部署副本（例如 grid_weixin_execute.py 两边内容已不同），迁移对比失去意义。
"""
import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HERMES_SCRIPTS = Path(r'D:\Hermes Agent CN Desktop\data\hermes-home\scripts')


def _load():
    spec = importlib.util.spec_from_file_location('run_and_push_under_test', REPO / 'deploy_scripts' / 'run_and_push.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunAndPushScriptPathTests(unittest.TestCase):
    def setUp(self):
        self.module = _load()

    def test_every_job_resolves_inside_ah_analyse(self):
        for job in self.module.JOBS:
            path = Path(self.module.resolve_script(job)).resolve()
            with self.subTest(job=job):
                self.assertTrue(str(path).lower().startswith(str(REPO).lower()),
                                f'{job} 解析到 {path}，不在 AH_analyse 内')
                self.assertTrue(path.is_file(), f'{job} 的脚本不存在：{path}')

    def test_no_job_uses_hermes_scripts(self):
        for job in self.module.JOBS:
            path = Path(self.module.resolve_script(job)).resolve()
            with self.subTest(job=job):
                self.assertNotIn(str(HERMES_SCRIPTS).lower(), str(path).lower())


if __name__ == '__main__':
    unittest.main()
