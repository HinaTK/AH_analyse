"""把 AH 单一真源部署到 hermes 运行时目录：唯一真源、漂移门禁、SHA256 校验与可复制回滚。

2026-11-04 重写背景（见 deploy-chain-audit-20261104.md，全只读取证）：
- 原版只装 `tools/confirmed_grid/launchers/*.py` 的 7 个薄壳，`deploy_scripts/` 下的
  独立脚本（grid_regime_cache、overseas_trigger_monitor 等）没有部署路径，只能手工部署；
- 同名双源 `launchers/grid_weixin_execute.py`（265B 无解释器钉子）与
  `deploy_scripts/grid_weixin_execute.py`（1334B 带钉子，提交 fb49ea2 修门控静默失效）
  导致本部署器把已上线的热修覆盖回退——这是本次要堵死的根因；
- cron 由 hermes 内嵌 Python 3.14（无 pandas）执行，jobs.json / config.yaml 均无解释器
  字段，无法全局切解释器；因此解释器钉子必须收进入口脚本真源本身。

设计要点：
1. `manifest()` 给出 目标名 -> 唯一源文件；未在 PINNED 里裁准的同名双源直接报错，
   绝不再静默覆盖；
2. 活体与真源字节不一致时抛 DeployDrift，必须显式 --force 才覆盖（先备份）；
3. 每次部署输出可复制的 PowerShell 回滚命令（仓库公告第 5 条）；
4. 默认 dry-run 友好：`--dry-run` 零写入，可先在生产上预览映射；
5. 保留对权威账本状态的保护：部署前后 confirmed-*.json 哈希必须一致。
"""
import argparse
from datetime import datetime
import hashlib
from pathlib import Path
import shutil
import json
import sys

# 部署源目录（按文件名扫描；同名双源需在 PINNED 裁准）
SOURCE_DIRS = ('tools/confirmed_grid/launchers', 'deploy_scripts')

# 同名双源的人工裁准：目标名 -> 相对仓库根的源路径。
# 未列入此表又出现同名双源时 manifest() 报错，而不是按目录顺序静默取一个。
PINNED = {
    # 265B 薄壳无解释器钉子，会在缓存缺失时复现 2026-10-28 门控静默失效；
    # 1334B 版钉死系统 Python3.12 再 import，是唯一权威内容。
    'grid_weixin_execute.py': 'deploy_scripts/grid_weixin_execute.py',
}

# 明确不部署的脚本：run_and_push.py 由 Windows 计划任务直接调用 AH 仓库内路径
# （schtasks 的 Arguments 写死 D:\Code\AH_analyse\deploy_scripts\run_and_push.py），
# 放进 hermes/scripts 反而制造第二份会被误改的副本。
UNDEPLOYED = {'run_and_push.py'}

# 部署器自身默认仓库根：tools/confirmed_grid/deploy.py -> parents[2]
DEFAULT_REPO = Path(__file__).resolve().parents[2]

# 备份根目录（相对 hermes home）
BACKUP_ROOT = 'cache/confirmed-runtime-deploy'


class DeployError(RuntimeError):
    """部署清单本身有问题（双源未裁准、源缺失等）。"""


class DeployDrift(RuntimeError):
    """活体与真源不一致：拒绝静默覆盖，需显式 --force。"""


def sha256(path):
    """返回文件的 SHA256 十六进制摘要。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manifest(repo=None):
    """返回部署清单：目标文件名 -> 唯一源文件。

    同名的第二个源若不等于 PINNED 裁准的那个，直接报错——静默覆盖正是
    grid_weixin_execute.py 热修被回退的原因。
    """
    repo = Path(repo or DEFAULT_REPO)
    found = {}
    for folder in SOURCE_DIRS:
        for path in sorted((repo / folder).glob('*.py')):
            name = path.name
            if name.startswith('test_') or name in UNDEPLOYED:
                continue
            found.setdefault(name, []).append(path)

    resolved = {}
    for name, paths in sorted(found.items()):
        if name in PINNED:
            chosen = repo / PINNED[name]
            if chosen not in paths:
                raise DeployError(f'{name} 的裁准源不存在：' + str(chosen))
            resolved[name] = chosen
        elif len(paths) == 1:
            resolved[name] = paths[0]
        else:
            raise DeployError(
                f'{name} 有多个真源未裁准：{[str(p) for p in paths]}；'
                f'请在 PINNED 中指定唯一源'
            )
    return resolved


def _rollback_lines(home, backup, names):
    """生成可复制的 PowerShell 回滚命令。"""
    return [
        f"Copy-Item '{Path(backup) / name}' "
        f"'{Path(home) / 'scripts' / name}' -Force"
        for name in names
    ]


def deploy(home, repo=None, apply=True, force=False):
    """执行部署或 dry-run。

    home    hermes 运行目录（其下 scripts/ 是部署目标，cache/ 放备份）
    repo    AH 仓库根，默认本文件所在仓库
    apply   False 时只出报告不写盘（dry-run）
    force   活体与真源不一致时是否允许覆盖（覆盖前必先备份）
    """
    home = Path(home)
    repo = Path(repo or DEFAULT_REPO)
    targets = manifest(repo)

    # 先算全部状态，再决定是否动盘：漂移门禁必须在任何写入之前生效。
    entries = []
    drift = []
    for name, src in sorted(targets.items()):
        target = home / 'scripts' / name
        src_sha = sha256(src)
        current = sha256(target) if target.exists() else None
        if current is None:
            state = 'new'
        elif current == src_sha:
            state = 'same'
        else:
            state = 'drift'
            drift.append(name)
        entries.append({
            'name': name,
            'source': str(src),
            'target': str(target),
            'sha256': src_sha,
            'current': current,
            'state': state,
        })

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = home / BACKUP_ROOT / stamp

    if not apply:
        return {
            'mode': 'dry-run',
            'backup': None,
            'targets': entries,
            'drift': drift,
            'rollback': _rollback_lines(home, backup, [e['name'] for e in entries]),
        }

    if drift and not force:
        raise DeployDrift(
            '活体与真源不一致，拒绝覆盖（确认无误后加 --force）：' + ', '.join(drift)
        )

    # 权威账本保护：部署前后 confirmed-*.json 哈希必须一致。
    sys.path.insert(0, str(repo))
    import holdings as H
    held = H.held_codes()
    states = [home / 'cache/grid-account' / ('confirmed-' + code[-6:] + '.json') for code in held]
    before = {str(path): sha256(path) for path in states if path.exists()}

    backup.mkdir(parents=True)
    changed = []
    for entry in entries:
        if entry['state'] == 'same':
            continue
        target = Path(entry['target'])
        source = Path(entry['source'])
        if target.exists():
            shutil.copy2(target, backup / target.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        # 原子替换：先写临时文件再 rename，避免半截文件被 cron 读到。
        temp = target.with_suffix('.tmp')
        temp.write_bytes(source.read_bytes())
        temp.replace(target)
        assert sha256(target) == entry['sha256'], target
        changed.append(entry['name'])

    H.save_holdings_to_root(
        H.load_holdings_from_root(home / 'cache/grid-account'), home / 'cache/grid-account'
    )
    after = {str(path): sha256(path) for path in states if path.exists()}
    assert before == after, 'Authoritative state changed during deployment'

    return {
        'mode': 'apply',
        'backup': str(backup),
        'targets': entries,
        'drift': drift,
        'changed': changed,
        'rollback': _rollback_lines(home, backup, changed),
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='部署 AH 真源到 hermes 运行时目录')
    parser.add_argument('--home', required=True, help='hermes 运行目录')
    parser.add_argument('--repo', default=None, help='AH 仓库根，默认本文件所在仓库')
    parser.add_argument('--dry-run', action='store_true', help='只出映射报告，不写任何文件')
    parser.add_argument('--force', action='store_true', help='活体与真源不一致时允许覆盖（先备份）')
    options = parser.parse_args()
    report = deploy(
        options.home, repo=options.repo, apply=not options.dry_run, force=options.force
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
