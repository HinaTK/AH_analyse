from pathlib import Path

hs = Path(r"D:/Code/AH_analyse/ah_recommendation_system/backend/stock_recommend/hotspot_mapper.py")
text = hs.read_text(encoding="utf-8")
old = '''def _alias_keys(industry: str) -> list[str]:
    keys = [industry]
    keys.extend(INDUSTRY_ALIASES.get(industry, []))
    return keys
'''
new = '''def _alias_keys(industry: str) -> list[str]:
    keys = [industry]
    keys.extend(INDUSTRY_ALIASES.get(industry, []))
    return keys


def _is_unrelated_power_name(name: str) -> bool:
    text = str(name or "")
    if any(token in text for token in ("新能源", "光伏", "锂电", "电池", "储能")):
        return False
    return any(token in text for token in ("深圳能源", "深南电", "电力", "热电", "水电", "火电"))


def _keep_mapped_member(name: str, alias: str) -> bool:
    return not (alias == "新能源" and _is_unrelated_power_name(name))
'''
if old not in text:
    raise SystemExit("alias helper not found")
text = text.replace(old, new, 1)

old_loop = '''            for alias in _alias_keys(industry):
                for item in focus_universe.get(alias, ()):
                    code = str(item.get("code") or "").zfill(6)
                    if len(code) == 6:
                        members[code] = {"code": code, "name": item.get("name") or code}
            for key, items in focus_universe.items():
                if any(alias == str(key) for alias in _alias_keys(industry)):
                    for item in items:
                        code = str(item.get("code") or "").zfill(6)
                        if len(code) == 6:
                            members[code] = {"code": code, "name": item.get("name") or code}
'''
new_loop = '''            for alias in _alias_keys(industry):
                for item in focus_universe.get(alias, ()):
                    code = str(item.get("code") or "").zfill(6)
                    name = str(item.get("name") or code)
                    if len(code) == 6 and _keep_mapped_member(name, alias):
                        members[code] = {"code": code, "name": name}
            for key, items in focus_universe.items():
                if any(alias == str(key) for alias in _alias_keys(industry)):
                    for item in items:
                        code = str(item.get("code") or "").zfill(6)
                        name = str(item.get("name") or code)
                        if len(code) == 6 and _keep_mapped_member(name, str(key)):
                            members[code] = {"code": code, "name": name}
'''
if old_loop not in text:
    raise SystemExit("member loop not found")
hs.write_text(text.replace(old_loop, new_loop, 1), encoding="utf-8")
print("patched mapper")

test = Path(r"D:/Code/AH_analyse/ah_recommendation_system/backend/tests/test_recommendation_display_repairs.py")
t = test.read_text(encoding="utf-8")
old_test = '''            focus_universe={
                "新能源": [{"code": "300750", "name": "宁德时代"}, {"code": "002594", "name": "比亚迪"}],
                "电力": [{"code": "000027", "name": "深圳能源"}, {"code": "000037", "name": "深南电A"}],
            },
'''
new_test = '''            focus_universe={
                "新能源": [
                    {"code": "300750", "name": "宁德时代"},
                    {"code": "002594", "name": "比亚迪"},
                    {"code": "000027", "name": "深圳能源"},
                    {"code": "000037", "name": "深南电A"},
                ],
                "电力": [{"code": "000027", "name": "深圳能源"}, {"code": "000037", "name": "深南电A"}],
            },
'''
if old_test not in t:
    raise SystemExit("energy test block not found")
test.write_text(t.replace(old_test, new_test, 1), encoding="utf-8")
print("patched test")
