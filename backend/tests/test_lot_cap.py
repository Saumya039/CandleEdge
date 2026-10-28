"""Alert mode removes the money limits but must never size a simulated trade into absurd lot counts."""

from stratagy.config import ALERT_MODE_LIMITS, CostModel, RiskSettings
from stratagy.risk import size_position


def test_alert_mode_sizes_one_lot_not_thousands():
    risk = RiskSettings(confirmed=True, defaults_in_use=True, **ALERT_MODE_LIMITS)
    sz = size_position(35.68, 32.57, 550, 0.05, CostModel(), risk)
    assert sz.lots == 1


def test_normal_limits_still_size_by_risk_budget():
    risk = RiskSettings(confirmed=True, max_risk_per_trade=5_000.0, max_premium_deployed=100_000.0)
    sz = size_position(35.68, 32.57, 550, 0.05, CostModel(), risk)
    assert 1 <= sz.lots <= 100_000 and sz.lots * sz.per_lot_risk <= 5_000.0
