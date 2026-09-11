from pathlib import Path
p = Path(r"D:/Code/AH_analyse/ah_recommendation_system/backend/stock_recommend/market_data.py")
t = p.read_text(encoding="utf-8")
old = '''        missing_fields: set[str] = {
            field_name
            for row in result.rows
            for field_name in SUPPLEMENT_FIELDS
            if row.get(field_name) is None
        }
'''
new = '''        missing_fields: set[str] = {
            field_name
            for row in result.rows
            for field_name in SUPPLEMENT_FIELDS
            if _missing_quote_value(field_name, row.get(field_name))
        }
'''
if old not in t:
    raise SystemExit("missing_fields block not found")
p.write_text(t.replace(old, new, 1), encoding="utf-8")
print("patched missing_fields")
