"""Authoritative 159363 input in user supplied order; labels are derived."""
import argparse
import json
from pathlib import Path
from confirmed_589720 import build
from grid_state import save

INPUT=[('buy',4600,'1.28'),('buy',4700,'1.273'),('buy',4800,'1.197'),('buy',5100,'1.169'),('sell',5100,'1.193'),('buy',5100,'1.156'),('sell',5100,'1.180'),('buy',5100,'1.157'),('buy',5200,'1.142'),('buy',4600,'1.120'),('buy',5400,'1.093'),('sell',5400,'1.115'),('buy',5400,'1.103')]

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    state=build(INPUT,code='sz159363',name='创业板人工智能ETF华宝')
    p=Path(args.output)
    if p.exists():
        raise SystemExit('目标已经存在，禁止未经核验覆盖')
    save(p,state)
    actual=json.loads(p.read_text(encoding='utf-8'))
    assert actual==state
    print(json.dumps(actual,ensure_ascii=False,indent=2))
