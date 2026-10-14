"""Persisted list of held ETFs. Single source of enumeration for all entrypoints.

Active flag controls whether grid buy/sell suggestions are generated.
Inactive ETFs (migration exit) are still read, midnight-rolled and reported,
but never receive a sell or rebuy action.
"""
import json
import os
from pathlib import Path
from decimal import Decimal as D

DEFAULT = {
    'sh589720': {'name': '科创创新药ETF国泰', 'lot_budget': '8000', 'active': True},
    'sz159363': {'name': '创业板人工智能ETF华宝', 'lot_budget': '6000', 'active': True},
    'sz159992': {'name': '创新药ETF银华', 'lot_budget': None, 'active': False},
}


def holdings_path(home=None):
    home = home or os.environ.get('HERMES_HOME', 'D:/Hermes Agent CN Desktop/data/hermes-home')
    return Path(home) / 'cache/grid-account' / 'holdings.json'


def load_holdings(home=None):
    path = holdings_path(home)
    if not path.exists():
        return {code: dict(entry) for code, entry in DEFAULT.items()}
    data = json.loads(path.read_text(encoding='utf-8'))
    holdings = data.get('holdings', data)
    for code, entry in DEFAULT.items():
        holdings.setdefault(code, dict(entry))
    return holdings


def save_holdings(holdings, home=None):
    return save_holdings_to_root(holdings, holdings_path(home).parent)


def load_holdings_from_root(root):
    """Load holdings from a grid-account root directory directly."""
    root = Path(root)
    path = root / 'holdings.json'
    if not path.exists():
        return {code: dict(entry) for code, entry in DEFAULT.items()}
    data = json.loads(path.read_text(encoding='utf-8'))
    holdings = data.get('holdings', data)
    for code, entry in DEFAULT.items():
        holdings.setdefault(code, dict(entry))
    return holdings


def save_holdings_to_root(holdings, root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'holdings.json'
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps({'holdings': holdings}, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)
    return path


def active_codes(holdings=None):
    holdings = holdings or load_holdings()
    return tuple(code for code, entry in holdings.items() if entry.get('active'))


def held_codes(holdings=None):
    holdings = holdings or load_holdings()
    return tuple(holdings.keys())


def lot_budgets(holdings=None):
    holdings = holdings or load_holdings()
    return {code: D(entry['lot_budget']) if entry.get('lot_budget') else None
            for code, entry in holdings.items()}


def names(holdings=None):
    holdings = holdings or load_holdings()
    return {code: entry['name'] for code, entry in holdings.items()}


def is_active(code, holdings=None):
    holdings = holdings or load_holdings()
    return bool(holdings.get(code, {}).get('active'))