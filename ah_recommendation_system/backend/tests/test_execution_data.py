import unittest
from types import SimpleNamespace


class QueryResult:
    error_code = "0"
    error_msg = ""
    fields = ["date", "open", "high", "low", "close", "preclose", "volume", "tradestatus", "isST"]

    def __init__(self):
        self.rows = iter([["2026-09-01", "10", "11", "9", "10", "9.5", "5000", "1", "1"]])

    def next(self):
        self.current = next(self.rows, None)
        return self.current is not None

    def get_row_data(self):
        return self.current


class FakeBaostock:
    def __init__(self):
        self.calls = []

    def login(self):
        return SimpleNamespace(error_code="0")

    def logout(self):
        pass

    def query_history_k_data_plus(self, code, fields, **kwargs):
        self.calls.append((code, fields, kwargs))
        return QueryResult()


class TestExecutionData(unittest.TestCase):
    def test_uses_unadjusted_exchange_preclose_and_st_flag(self):
        from ah_recommendation_system.backend.stock_recommend.execution_data import ExecutionDataProvider

        api = FakeBaostock()
        frame = ExecutionDataProvider(api=api).get_stock_bars("600001", "20260901", "20260910")
        self.assertEqual(api.calls[0][0], "sh.600001")
        self.assertEqual(api.calls[0][2]["adjustflag"], "3")
        self.assertIn("preclose", api.calls[0][1])
        self.assertEqual(frame.iloc[0]["prev_close"], 9.5)
        self.assertTrue(frame.iloc[0]["is_st"])
        self.assertEqual(frame.attrs["adjustment"], "none")

    def test_benchmark_is_index_not_equity_with_same_digits(self):
        from ah_recommendation_system.backend.stock_recommend.execution_data import ExecutionDataProvider

        api = FakeBaostock()
        provider = ExecutionDataProvider(api=api)
        provider.get_benchmark_bars("20260901", "20260910")
        self.assertEqual(api.calls[0][0], "sh.000300")

    def test_provider_errors_do_not_generate_mock_prices(self):
        from ah_recommendation_system.backend.stock_recommend.execution_data import ExecutionDataProvider

        api = FakeBaostock()
        api.login = lambda: SimpleNamespace(error_code="1")
        with self.assertRaises(RuntimeError):
            ExecutionDataProvider(api=api).get_stock_bars("600001", "20260901", "20260910")
