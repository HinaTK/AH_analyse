"""部署清单 TDD：按文件映射、唯一真源、漂移门禁、SHA256 与可复制回滚命令。

背景（2026-11-04 审计，只读取证报告 deploy-chain-audit-20261104.md）：
- 原 deploy.py 只装 `tools/confirmed_grid/launchers/*.py`（7 个薄壳），
  `deploy_scripts/` 下的独立脚本无部署路径，只能手工部署；
- 同名双源 `launchers/grid_weixin_execute.py`(265B 无钉子) vs
  `deploy_scripts/grid_weixin_execute.py`(1334B 带解释器钉子) 导致 deploy.py
  把已部署的门控静默失效热修（提交 fb49ea2）覆盖回退；
- cron 用 hermes 内嵌 Python 3.14（无 pandas）执行脚本，jobs.json/config.yaml
  均无解释器字段 —— 无法全局切解释器，只能把钉子收进入口真源。
"""
import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.confirmed_grid import deploy as D


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(__file__).resolve().parents[1]
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.home = Path(self.folder.name)
        (self.home / 'scripts').mkdir(parents=True)

    def test_every_target_resolves_to_exactly_one_source(self):
        """唯一真源：清单里每个目标只能有一个源文件（防覆盖回退）。"""
        seen = {}
        for target, src in D.manifest(self.repo).items():
            self.assertTrue(src.is_file(), f'{target} 的源不存在: {src}')
            self.assertNotIn(target, seen, f'{target} 有两个真源: {seen.get(target)} 与 {src}')
            seen[target] = src

    def test_execute_launcher_source_is_the_pinned_deploy_scripts_version(self):
        """grid_weixin_execute.py 必须取带解释器钉子的 1334B 版，且旧薄壳已删。"""
        src = D.manifest(self.repo)['grid_weixin_execute.py']
        self.assertEqual(src, self.repo / 'deploy_scripts' / 'grid_weixin_execute.py')
        self.assertIn('SYSTEM_PY', src.read_text(encoding='utf-8'))
        self.assertFalse(
            (self.repo / 'tools/confirmed_grid/launchers/grid_weixin_execute.py').exists(),
            'launchers 里的 265B 旧壳必须删除，否则部署器会再次回退热修',
        )

    def test_manifest_covers_all_deploy_scripts_except_undeployable(self):
        """deploy_scripts 下非测试脚本全部纳入；run_and_push.py 不部署。"""
        covered = set(D.manifest(self.repo))
        expected = {
            p.name for p in (self.repo / 'deploy_scripts').glob('*.py')
            if not p.name.startswith('test_')
        } - {'run_and_push.py'}
        self.assertEqual(expected - covered, set(), 'deploy_scripts 有脚本漏装')
        self.assertNotIn('run_and_push.py', covered, 'run_and_push.py 由 schtasks 直接调 AH 路径，不部署')

    def test_manifest_covers_all_confirmed_grid_launchers(self):
        """confirmed_grid 的入口薄壳（裁准项除外）仍从 launchers 取。"""
        covered = D.manifest(self.repo)
        launcher_dir = self.repo / 'tools/confirmed_grid/launchers'
        for p in launcher_dir.glob('*.py'):
            if p.name in D.PINNED:
                continue
            self.assertIn(p.name, covered, f'{p.name} 不在部署清单')
            self.assertEqual(covered[p.name], p, f'{p.name} 应取 launchers 版')

    def test_dry_run_writes_nothing(self):
        """dry-run 必须零写入，可安全在生产上先跑。"""
        report = D.deploy(self.home, repo=self.repo, apply=False)
        self.assertEqual(report['mode'], 'dry-run')
        self.assertEqual(list((self.home / 'scripts').iterdir()), [])

    def test_dry_run_reports_mode_source_hash_and_rollback(self):
        """dry-run 输出须含映射、源哈希与可复制回滚命令。"""
        report = D.deploy(self.home, repo=self.repo, apply=False)
        entry = next(t for t in report['targets'] if t['name'] == 'grid_weixin_execute.py')
        self.assertIn('sha256', entry)
        self.assertTrue(report['rollback'], '必须输出回滚命令')
        self.assertTrue(all('Copy-Item' in line for line in report['rollback']))

    def test_apply_refuses_to_overwrite_drift_without_force(self):
        """活体与真源不一致时拒绝静默覆盖（漂移门禁），且不写任何文件。"""
        target = self.home / 'scripts' / 'grid_weixin_execute.py'
        target.write_text('# 旧壳\n', encoding='utf-8')
        before = target.read_bytes()
        with self.assertRaises(D.DeployDrift) as ctx:
            D.deploy(self.home, repo=self.repo, apply=True)
        self.assertIn('grid_weixin_execute.py', str(ctx.exception))
        self.assertEqual(target.read_bytes(), before, '被拒时不得改动活体')

    def test_apply_with_force_backs_up_verifies_and_reports_rollback(self):
        """--force 才覆盖；覆盖前备份活体，覆盖后字节校验，并给回滚命令。"""
        target = self.home / 'scripts' / 'grid_weixin_execute.py'
        target.write_text('# 旧壳\n', encoding='utf-8')
        report = D.deploy(self.home, repo=self.repo, apply=True, force=True)
        src = D.manifest(self.repo)['grid_weixin_execute.py']
        self.assertEqual(
            hashlib.sha256(target.read_bytes()).hexdigest(),
            hashlib.sha256(src.read_bytes()).hexdigest(),
        )
        backup = Path(report['backup'])
        self.assertEqual((backup / 'grid_weixin_execute.py').read_text(encoding='utf-8'), '# 旧壳\n')
        self.assertTrue(any('Copy-Item' in line for line in report['rollback']))

    def test_apply_twice_is_idempotent(self):
        """同源重复部署为幂等：第二次不再报漂移。"""
        D.deploy(self.home, repo=self.repo, apply=True, force=True)
        first = (self.home / 'scripts' / 'grid_weixin_execute.py').read_bytes()
        report = D.deploy(self.home, repo=self.repo, apply=True)
        self.assertEqual((self.home / 'scripts' / 'grid_weixin_execute.py').read_bytes(), first)
        self.assertEqual(report['drift'], [])


if __name__ == '__main__':
    unittest.main()
