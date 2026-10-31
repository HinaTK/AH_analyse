import confirmed_runtime as runtime


def test_grid_advice_does_not_fetch_quotes(monkeypatch, capsys):
    monkeypatch.setattr(runtime, 'phase', lambda now: 'preview')
    monkeypatch.setattr(runtime, 'plan', lambda root: {'fixture': True})
    monkeypatch.setattr(runtime, 'render', lambda ticket: 'grid actions')
    def forbidden():
        raise AssertionError('grid advice must not depend on quotes')
    monkeypatch.setattr(runtime, 'fetch_quotes', forbidden)
    runtime.ops_main(['--phase', 'grid'])
    output = capsys.readouterr().out
    assert 'grid actions' in output
    assert '09:24' in output
    assert '实时行情' in output
