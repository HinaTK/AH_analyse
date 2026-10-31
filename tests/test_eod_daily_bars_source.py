"""EOD daily bars must not depend on a single Tencent endpoint.

2026-10-23: ifzq.gtimg.cn fqkline started returning HTTP 501, breaking the
15:20 EOD job. fetch_daily_bars must try the proxy.finance.qq.com mirror and
fall back to the legacy ifzq host, and fail loudly when all sources fail.
"""
import io
import json
import unittest
from unittest.mock import patch
import confirmed_runtime as r


def _response(code, close='0.813'):
    payload = {'code': 0, 'data': {code: {'day': [['2026-10-23', '0.775', close]]}}}
    return io.BytesIO(json.dumps(payload).encode())


class FetchDailyBarsTests(unittest.TestCase):
    def test_primary_source_is_proxy_mirror(self):
        calls = []

        def urlopen(request, timeout):
            calls.append(request.full_url)
            self.assertIn('proxy.finance.qq.com', request.full_url)
            self.assertIn('newfqkline/get', request.full_url)
            self.assertIn('param=sh589720,day,,,80,qfq', request.full_url)
            return _response('sh589720')

        with patch('urllib.request.urlopen', side_effect=urlopen):
            bars = r.fetch_daily_bars('sh589720')
        self.assertEqual(bars, [dict(date='2026-10-23', close='0.813')])
        self.assertEqual(len(calls), 1)

    def test_falls_back_to_legacy_ifzq_when_mirror_fails(self):
        calls = []

        def urlopen(request, timeout):
            calls.append(request.full_url)
            if 'proxy.finance.qq.com' in request.full_url:
                raise OSError('HTTP Error 501: Not Implemented')
            self.assertIn('ifzq.gtimg.cn', request.full_url)
            return _response('sh589720')

        with patch('urllib.request.urlopen', side_effect=urlopen):
            bars = r.fetch_daily_bars('sh589720')
        self.assertEqual(bars, [dict(date='2026-10-23', close='0.813')])
        self.assertEqual(len(calls), 2)

    def test_raises_value_error_when_all_sources_fail(self):
        def urlopen(request, timeout):
            raise OSError('HTTP Error 501: Not Implemented')

        with patch('urllib.request.urlopen', side_effect=urlopen):
            with self.assertRaises(ValueError) as ctx:
                r.fetch_daily_bars('sh589720')
        self.assertIn('行情源全部失败', str(ctx.exception))

    def test_rejects_nonzero_code_payload(self):
        def urlopen(request, timeout):
            if 'proxy.finance.qq.com' in request.full_url:
                return io.BytesIO(json.dumps({'code': 1, 'msg': 'bad params'}).encode())
            return _response('sh589720')

        with patch('urllib.request.urlopen', side_effect=urlopen):
            bars = r.fetch_daily_bars('sh589720')
        self.assertEqual(bars, [dict(date='2026-10-23', close='0.813')])


if __name__ == '__main__':
    unittest.main()
