"""Advice status icons are presentation-only and never imply broker fills."""
import unittest

import confirmed_runtime as runtime


BUY_CODE = 'sh510300'
SELL_CODE = 'sz159915'
BLOCK_CODE = 'sh510500'
DAY = '2026-11-05'


def _ticket():
    return dict(
        states={},
        names={BUY_CODE: '买入测试ETF', SELL_CODE: '卖出测试ETF'},
        actions=[
            dict(code=BUY_CODE, side='buy', lot='B', qty=1000, price='1.000'),
            dict(code=SELL_CODE, side='sell', lot='A', qty=2000, price='2.000'),
        ],
        regime_blocks=[f'{BLOCK_CODE} 暂停买入：测试拦截原因'],
    )


def _quotes(buy_last, buy_high, buy_low, sell_last, sell_high, sell_low):
    return {
        BUY_CODE: dict(last=buy_last, high=buy_high, low=buy_low, time='20261105100000'),
        SELL_CODE: dict(last=sell_last, high=sell_high, low=sell_low, time='20261105100000'),
    }


class AdviceStatusIconTests(unittest.TestCase):
    def assert_allowed_touch_icons(self, message):
        lines = message.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertNotIn('⛔', message)
        self.assertNotIn(BLOCK_CODE, message)
        for line, code, direction in zip(lines, (BUY_CODE, SELL_CODE), ('买', '卖')):
            self.assertTrue(line.startswith(f'✅ {code} '), line)
            self.assertIn(f'条件{direction}', line)
            self.assertIn('触价不等于成交，请核对银河。', line)

    def test_render_marks_allowed_buy_sell_and_preserves_blocked_reason(self):
        output = runtime.render(_ticket())
        lines = output.splitlines()
        self.assertEqual(
            [line for line in lines if '⛔' in line],
            [f'⛔ {BLOCK_CODE} 暂停买入：测试拦截原因'],
        )
        self.assertIn(runtime.WARNING, output)
        self.assertEqual(
            [line for line in lines if line.startswith('- ')],
            [f'- ✅ {BUY_CODE} 买入测试ETF 条件买 B格 **1,000份** @ **1.000**',
             f'- ✅ {SELL_CODE} 卖出测试ETF 条件卖 A格 **2,000份** @ **2.000**'],
        )

    def test_monitor_marks_first_sighting_current_price_touches(self):
        quotes = _quotes('0.990', '1.100', '0.980', '2.010', '2.020', '1.900')
        message = runtime.monitor(_ticket(), quotes, {}, DAY)
        self.assert_allowed_touch_icons(message)
        self.assertEqual(message.count('首见现价触价'), 2)

    def test_monitor_marks_later_new_extreme_touches(self):
        ticket = _ticket()
        state = {}
        baseline = _quotes('1.010', '1.020', '1.005', '1.990', '1.995', '1.980')
        self.assertEqual(runtime.monitor(ticket, baseline, state, DAY), '')
        later = _quotes('1.010', '1.020', '0.990', '1.990', '2.010', '1.980')
        message = runtime.monitor(ticket, later, state, DAY)
        self.assert_allowed_touch_icons(message)
        self.assertIn('建议生成后日内最低=0.990（基准1.005）', message)
        self.assertIn('建议生成后日内最高=2.010（基准1.995）', message)
        self.assertEqual(runtime.monitor(ticket, later, state, DAY), '')


if __name__ == '__main__':
    unittest.main()
