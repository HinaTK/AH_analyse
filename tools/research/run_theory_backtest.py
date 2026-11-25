# -*- coding: utf-8 -*-
"""理论口径参数敏感性跑批（只读：只拉行情、只写报告，不碰账本与生产代码）。

标的：510300 沪深300ETF、515180 红利ETF、589720 科创创新药ETF、159363 创业板AI ETF。
参数：格距 3%/4.5%/6% × 单格 2000/3000/5000（等比）。
窗口：全样本 + 三段单边市（2015-06~2016-02、2018 全年、2022 全年）——
标的上市晚于窗口的，窗口结果标注"无数据"，不外推。

数据：东财日K前复权，按 end 分页（单页上限约 1000 根，见 tools/probe_east_depth.py
的探针结论）。输出：workspace 下 JSON，供报告引用。
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, 'D:/Code/AH_analyse')
sys.path.insert(0, 'D:/Code/AH_analyse/tools')

from theory_ladder import simulate_ladder

TARGETS = [('1.510300', '510300', '沪深300ETF', '2012'),
           ('1.515180', '515180', '红利ETF', '2018'),
           ('1.589720', '589720', '科创创新药ETF', '2025'),
           ('0.159363', '159363', '创业板人工智能ETF', '2024')]
GAPS = [D('0.03'), D('0.045'), D('0.06')]
LOTS = [2000, 3000, 5000]
WINDOWS = [('2015单边', '2015-06-01', '2016-02-29'),
           ('2018单边', '2018-01-01', '2018-12-31'),
           ('2022单边', '2022-01-01', '2022-12-31')]
OUT = Path(r'C:\Users\Administrator\.dsh\bot\workspace\回测_理论刻度验证_20261104.json')


CACHE_DIR = Path(r'C:\Users\Administrator\.dsh\bot\workspace\回测缓存')


def fetch_tencent(code):
    """腾讯 proxy 日K（前复权）。只对深市通（2026-11-04 实测沪市一律 param error），
    且单次约 300 根——仅作东财首页失败时的回退。"""
    param = f'{code},day,,,640,qfq'
    url = 'https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?param=' + param
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode('utf-8'))
    if data.get('msg'):
        return []
    node = data['data'][code]
    arr = node.get('qfqday') or node.get('day') or []
    return [{'date': row[0], 'close': float(row[2])} for row in arr]


def fetch_page(secid, end, lmt='1000'):
    """拉一页日K，失败指数退避重试 6 次。返回 (lines, raw_data_or_None)。"""
    params = {
        'secid': secid, 'fields1': 'f1,f2,f3,f4,f5,f6',
        'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
        'klt': '101', 'fqt': '1', 'end': end, 'lmt': lmt,
    }
    url = ('https://push2his.eastmoney.com/api/qt/stock/kline/get?'
           + urllib.parse.urlencode(params))
    last = None
    for attempt in range(10):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0',
                'Referer': 'https://quote.eastmoney.com/'})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode('utf-8'))
            return (data.get('data') or {}).get('klines') or [], data
        except Exception as e:
            last = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f'{secid} end={end} 拉取失败: {last}')


def fetch_all(secid, listed_year):
    """分页拉全历史日K（前复权），每页落盘缓存，断点可续。

    最早一根已进入上市年份即视为完整：东财尾页常被限流掐断，
    而缺的只是上市当月前后的几天，三段窗口都不依赖它。
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f'{secid.replace(".", "_")}.json'
    bars = []
    if cache_file.exists():
        bars = json.loads(cache_file.read_text(encoding='utf-8'))
    seen = {b['date'] for b in bars}
    end = min(seen).replace('-', '') if seen else '20500101'
    if seen and min(seen)[:4] <= listed_year:
        bars.sort(key=lambda b: b['date'])
        return bars
    # 515180 特例：东财深历史页持续被限流掐断（2026-11-04 实测重试全部失败），
    # 腾讯对沪市 ETF 日线返回 param error。已有 2022-09 起的页就先用。
    if secid == '1.515180' and seen:
        bars.sort(key=lambda b: b['date'])
        return bars
    while True:
        try:
            lines, _ = fetch_page(secid, end)
        except RuntimeError:
            if not seen:
                # 东财首页失败：回退腾讯（深市可用，约 300 根）
                code = secid.split('.')[1]
                bars = fetch_tencent(('sz' if secid.startswith('0') else 'sh') + code)
                if bars:
                    cache_file.write_text(json.dumps(bars, ensure_ascii=False), encoding='utf-8')
                    print(f'    东财失败，腾讯回退 {len(bars)} 根', flush=True)
                    bars.sort(key=lambda b: b['date'])
                    return bars
            raise
        fresh = []
        for l in lines:
            p = l.split(',')
            if p[0] not in seen:
                seen.add(p[0])
                fresh.append({'date': p[0], 'close': float(p[2])})
        if not fresh:
            break
        bars.extend(fresh)
        cache_file.write_text(json.dumps(bars, ensure_ascii=False), encoding='utf-8')
        oldest = min(seen)
        print(f'    页 +{len(fresh)}，最早 {oldest}，累计 {len(bars)}', flush=True)
        if len(lines) < 900:
            break
        end = oldest.replace('-', '')
        time.sleep(3)
    bars.sort(key=lambda b: b['date'])
    return bars


def window_result(bars, start, end, gap, lot):
    sub = sorted((b for b in bars if start <= b['date'] <= end), key=lambda b: b['date'])
    if len(sub) < 20:
        return {'status': '无数据', 'days': len(sub)}
    r = simulate_ladder(sub, gap=float(gap), lot_budget=lot)
    r.pop('curve')
    r.pop('cycle_detail')
    r['status'] = 'ok'
    return r


def main():
    report = {'generated': time.strftime('%Y-%m-%d %H:%M'), 'targets': []}
    for secid, code, name, listed in TARGETS:
        print(f'拉取 {name} {code} ...', flush=True)
        bars = fetch_all(secid, listed)
        print(f'  {len(bars)} bars, {bars[0]["date"]} -> {bars[-1]["date"]}', flush=True)
        entry = {'code': code, 'name': name,
                 'data_start': bars[0]['date'], 'data_end': bars[-1]['date'],
                 'bars': len(bars), 'runs': []}
        for gap in GAPS:
            for lot in LOTS:
                full = window_result(bars, '1990-01-01', '2099-01-01', gap, lot)
                windows = {label: window_result(bars, s, e, gap, lot)
                           for label, s, e in WINDOWS}
                entry['runs'].append({'gap': str(gap), 'lot': lot,
                                      'full': full, 'windows': windows})
                print(f'  gap={gap} lot={lot}: 全程往返{full.get("cycles")} '
                      f'最深{full.get("deepest_k")}格 回撤{full.get("max_drawdown_pct")}%', flush=True)
        report['targets'].append(entry)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'已写 {OUT}')


if __name__ == '__main__':
    main()
