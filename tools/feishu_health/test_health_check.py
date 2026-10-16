import importlib.util
from pathlib import Path

SOURCE = Path(__file__).with_name('feishu_health_check.py')
if not SOURCE.exists():
    SOURCE = Path('D:/Hermes Agent CN Desktop/data/hermes-home/scripts/feishu_health_check.py')
spec = importlib.util.spec_from_file_location('health', SOURCE)
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


def test_rotated_connection_marker_with_recent_group_activity(tmp_path, monkeypatch):
    logs = tmp_path / 'logs'
    logs.mkdir()
    (logs / 'agent.log').write_text('other log\n' * 200 + 'feishu:group received message\n', encoding='utf-8')
    (logs / 'gateway.log').write_text('scheduler tick\n', encoding='utf-8')
    monkeypatch.setattr(health, 'HERMES_HOME', str(tmp_path))
    monkeypatch.setattr(health, 'GATEWAY_LOG', str(logs / 'gateway.log'))
    ok, detail = health.check_recent_feishu()
    assert ok, detail


def test_missing_connection_marker_is_unknown_not_proven_disconnection(tmp_path, monkeypatch):
    logs = tmp_path / 'logs'
    logs.mkdir()
    (logs / 'agent.log').write_text('scheduler tick\n', encoding='utf-8')
    monkeypatch.setattr(health, 'HERMES_HOME', str(tmp_path))
    monkeypatch.setattr(health, 'GATEWAY_LOG', str(logs / 'gateway.log'))
    ok, detail = health.check_recent_feishu()
    assert ok, detail
    assert 'unknown' in detail.lower()
