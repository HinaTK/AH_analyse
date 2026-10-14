"""EOD must fetch every held ETF, including read-only migration positions."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
import confirmed_runtime as r
import confirmed_589720


class EodHoldingsTests(unittest.TestCase):
    def test_real_eod_entry_fetches_all_held_codes_and_saves_report(self):
        now = datetime(2026, 10, 14, 15, 30, tzinfo=timezone(timedelta(hours=8)))
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz) if tz else now.replace(tzinfo=None)
        codes = ('sh589720', 'sz159363', 'sz159992')
        states = {code: confirmed_589720.build(code=code, name=code) for code in codes}
        quotes = {code: {'time': now.strftime('%Y%m%d') + '150000', 'last': '0.800'} for code in codes}
        seen = []
        def response(request, timeout):
            code = request.full_url.split('param=')[1].split(',')[0]
            seen.append(code)
            return io.BytesIO(json.dumps({'code': 0, 'data': {code: {'day': [[now.date().isoformat(), '0.8', '0.8']]}}}).encode())
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch('datetime.datetime', FrozenDatetime), patch.object(r, 'phase', return_value='execute'), patch.object(r.H, 'held_codes', return_value=codes), patch.object(r, 'root_from_home', return_value=root), patch.object(r, 'fetch_quotes', return_value=quotes), patch.object(r, 'plan', return_value={'states': states, 'actions': []}), patch('urllib.request.urlopen', side_effect=response):
                report = json.loads(r.eod_main())
            self.assertEqual(seen, list(codes))
            self.assertEqual(set(report['decisions']), set(codes))
            saved = json.loads((root / 'eod' / f'{now.date().isoformat()}.json').read_text(encoding='utf-8'))
            self.assertEqual(saved, report)
            self.assertFalse(report['executable'])

if __name__ == '__main__':
    unittest.main()
