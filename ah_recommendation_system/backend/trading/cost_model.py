from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    """Very simple transaction cost model.

    All rates are in fraction terms (e.g. 0.0003 = 3 bps).
    Output of estimate_* methods is in percent units.
    """

    # A-share
    a_commission_rate: float = 0.0003
    a_stamp_duty_sell_rate: float = 0.001

    # H-share (HK)
    h_commission_rate: float = 0.0003
    h_stamp_duty_rate: float = 0.0013
    h_trading_levy_rate: float = 0.000027
    h_trading_fee_rate: float = 0.00005

    # FX
    fx_spread_rate: float = 0.0002

    def estimate_round_trip_cost_pct(self) -> float:
        """Estimate a naive round-trip cost % for a pair trade.

        We approximate: open and close both legs.
        """
        # A: buy then sell
        a_cost = (2 * self.a_commission_rate) + self.a_stamp_duty_sell_rate

        # H: sell then buy (or buy then sell), stamp duty typically applies on both sides
        h_cost = (
            (2 * self.h_commission_rate)
            + (2 * self.h_stamp_duty_rate)
            + (2 * self.h_trading_levy_rate)
            + (2 * self.h_trading_fee_rate)
        )

        # FX both ways
        fx_cost = 2 * self.fx_spread_rate

        return (a_cost + h_cost + fx_cost) * 100.0


DEFAULT_COST_MODEL = CostModel()
