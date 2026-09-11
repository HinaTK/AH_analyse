from pathlib import Path

ROOT = Path(r"D:/Code/AH_analyse")

run_path = ROOT / "ah_recommendation_system/backend/stock_recommend/run.py"
run_text = run_path.read_text(encoding="utf-8")
old = '''    try:
        realtime_amount = float(row.get("amount") or 0)
    except (TypeError, ValueError):
        realtime_amount = 0.0
    if realtime_amount < 100_000_000:
        amounts = []
        for bar in bars:
            try:
                value = float(bar.get("amount") or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                amounts.append(value)
        if amounts:
            row["amount"] = amounts[-1]
            row["amount_reference"] = "latest_completed_daily_bar"
'''
new = '''    try:
        realtime_amount = float(row.get("amount") or 0)
    except (TypeError, ValueError):
        realtime_amount = 0.0
    if realtime_amount < 100_000_000:
        completed = []
        for bar in bars:
            try:
                value = float(bar.get("amount") or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value >= 100_000_000:
                completed.append(value)
        if completed:
            row["amount"] = completed[-1]
            row["amount_reference"] = "latest_completed_daily_bar"
'''
if old not in run_text:
    raise SystemExit("run.py amount block not found")
run_path.write_text(run_text.replace(old, new, 1), encoding="utf-8")
print("patched run.py")

md_path = ROOT / "ah_recommendation_system/backend/stock_recommend/market_data.py"
md_text = md_path.read_text(encoding="utf-8")
old_merge = '''def merge_quote_fields(primary: Mapping[str, Any], secondary: Mapping[str, Any], fields: Sequence[str] = SUPPLEMENT_FIELDS) -> List[str]:
    """Fill only missing fields; primary price/change identity stays untouched."""
    filled: List[str] = []
    for name in fields:
        if primary.get(name) is None and secondary.get(name) is not None:
            primary[name] = secondary[name]
            filled.append(name)
    return filled
'''
new_merge = '''def _missing_quote_value(name: str, value: Any) -> bool:
    if value is None:
        return True
    if name in {"amount", "volume"}:
        number = coerce_number(value)
        return number is None or number <= 0
    return False


def merge_quote_fields(primary: Mapping[str, Any], secondary: Mapping[str, Any], fields: Sequence[str] = SUPPLEMENT_FIELDS) -> List[str]:
    """Fill only missing fields; primary price/change identity stays untouched."""
    filled: List[str] = []
    for name in fields:
        if _missing_quote_value(name, primary.get(name)) and not _missing_quote_value(name, secondary.get(name)):
            primary[name] = secondary[name]
            filled.append(name)
    return filled
'''
if old_merge not in md_text:
    raise SystemExit("merge_quote_fields not found")
md_path.write_text(md_text.replace(old_merge, new_merge, 1), encoding="utf-8")
print("patched market_data.py")

hs_path = ROOT / "ah_recommendation_system/backend/stock_recommend/hotspot_mapper.py"
hs_text = hs_path.read_text(encoding="utf-8")
old_alias = '''    "印制电路板": ["功率半导体", "科技"],
    "AI算力硬件": ["功率半导体", "科技"],
    "覆铜板": ["功率半导体", "科技"],
    "电子材料": ["功率半导体", "科技"],
    "光通信设备": ["功率半导体", "科技"],
    "光芯片": ["功率半导体", "科技"],
    "电子元件": ["功率半导体", "科技"],
    "电容器": ["功率半导体", "科技"],
    "半导体": ["功率半导体", "科技"],
    "通信设备": ["科技"],
'''
new_alias = '''    "印制电路板": ["功率半导体"],
    "AI算力硬件": ["功率半导体"],
    "算力硬件": ["功率半导体"],
    "覆铜板": ["功率半导体"],
    "电子材料": ["功率半导体"],
    "光通信设备": ["功率半导体"],
    "光芯片": ["功率半导体"],
    "电子元件": ["功率半导体"],
    "电容器": ["功率半导体"],
    "半导体": ["功率半导体"],
    "功率器件": ["功率半导体"],
    "通信设备": ["功率半导体"],
'''
if old_alias not in hs_text:
    raise SystemExit("alias block not found")
hs_text = hs_text.replace(old_alias, new_alias, 1)
old_tag = "                if any(industry == tag or industry in tag or tag in industry for tag in tags):\n"
new_tag = "                if any(industry == tag for tag in tags):\n"
if old_tag not in hs_text:
    raise SystemExit("tag match not found")
hs_path.write_text(hs_text.replace(old_tag, new_tag, 1), encoding="utf-8")
print("patched hotspot_mapper.py")

test_path = ROOT / "ah_recommendation_system/backend/tests/test_recommendation_display_repairs.py"
test_text = test_path.read_text(encoding="utf-8")
marker = "class TestNewsDedupAndConfidence"
addition = '''
    def test_semiconductor_alias_does_not_pull_broad_tech_bucket(self):
        from ah_recommendation_system.backend.stock_recommend.hotspot_mapper import validate_and_expand_hotspots
        from ah_recommendation_system.backend.stock_recommend.focused_collector import DEFAULT_FOCUS_UNIVERSE

        mapped = validate_and_expand_hotspots(
            [{
                "theme": "AI算力链业绩兑现与功率半导体",
                "industries": ["半导体", "算力硬件", "功率器件"],
                "confidence": 0.57,
                "evidence_refs": ["macro-a", "macro-b"],
                "status": "early_signal",
            }],
            focus_universe=DEFAULT_FOCUS_UNIVERSE,
        )
        reps = mapped["hotspots"][0].get("representatives") or []
        self.assertIn("长电科技", reps)
        self.assertIn("韦尔股份", reps)
        self.assertNotIn("宁德时代", reps)
        self.assertNotIn("东方财富", reps)
        self.assertNotIn("立讯精密", reps)

    def test_row_tags_do_not_substring_match_across_industries(self):
        from ah_recommendation_system.backend.stock_recommend.hotspot_mapper import validate_and_expand_hotspots

        mapped = validate_and_expand_hotspots(
            [{
                "theme": "能源通胀",
                "industries": ["能源"],
                "confidence": 0.7,
                "evidence_refs": ["macro-a", "macro-b"],
                "status": "early_signal",
            }],
            rows=[
                {"code": "000027", "name": "深圳能源", "industry": "电力"},
                {"code": "300750", "name": "宁德时代", "focus_industries": ["新能源"]},
            ],
        )
        reps = mapped["hotspots"][0].get("representatives") or []
        self.assertNotIn("宁德时代", reps)
        self.assertNotIn("深圳能源", reps)


class TestPreMarketTurnoverReference(unittest.TestCase):
    def test_incomplete_last_tick_is_not_used_as_liquidity(self):
        from ah_recommendation_system.backend.stock_recommend.run import _apply_daily_feature_row

        row = {"code": "002142", "amount": 5_489_565.0}
        bars = [
            {"date": "2026-09-08", "open": 34, "high": 35, "low": 33, "close": 34.66, "volume": 17_425_068, "amount": 604_176_357},
            {"date": "2026-09-09", "open": 34, "high": 36, "low": 34, "close": 35.87, "volume": 44_975_091, "amount": 1_602_459_052},
            {"date": "2026-09-10", "open": 35.95, "high": 36.0, "low": 35.38, "close": 35.59, "volume": 152_700, "amount": 5_489_565},
        ]
        self.assertTrue(_apply_daily_feature_row(row, bars))
        self.assertEqual(row["amount"], 1_602_459_052)
        self.assertEqual(row["amount_reference"], "latest_completed_daily_bar")

    def test_zero_or_premarket_amount_is_treated_as_missing_for_supplement(self):
        from ah_recommendation_system.backend.stock_recommend.market_data import merge_quote_fields

        primary = {"price": 35.95, "change_pct": 0.22, "amount": 5_489_565.0, "volume": 152700, "pe": 7.6}
        secondary = {"amount": 1_602_459_052.49, "volume": 44_975_091, "pe": 7.2}
        filled = merge_quote_fields(primary, secondary)
        self.assertIn("amount", filled)
        self.assertEqual(primary["amount"], 1_602_459_052.49)
        self.assertEqual(primary["pe"], 7.6)

'''
if "test_semiconductor_alias_does_not_pull_broad_tech_bucket" in test_text:
    print("tests already present")
else:
    if marker not in test_text:
        raise SystemExit("test marker not found")
    test_path.write_text(test_text.replace(marker, addition + marker, 1), encoding="utf-8")
    print("patched tests")
print("done")
