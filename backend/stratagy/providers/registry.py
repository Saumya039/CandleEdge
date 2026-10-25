"""Provider selection and the capability matrix shown in the UI."""

from __future__ import annotations

from datetime import date

from ..config import Settings
from .base import MarketDataProvider
from .kite import KiteProvider
from .simulator import SimulatorProvider


def build_provider(s: Settings) -> MarketDataProvider:
    wl = [x.strip().upper() for x in s.watchlist.split(",") if x.strip()]
    if s.provider == "kite":
        return KiteProvider(s.kite_api_key, s.kite_access_token, wl)
    if s.provider != "simulator":
        raise ValueError(f"Unknown PROVIDER '{s.provider}' (use simulator or kite)")
    sim_date = date.fromisoformat(s.sim_date) if s.sim_date else None
    return SimulatorProvider(seed=s.sim_seed, sim_date=sim_date)


def capability_matrix() -> list[dict]:
    rows = []
    for cls in (SimulatorProvider, KiteProvider):
        c = cls.capabilities.model_dump()
        rows.append({"provider": cls.name, **c})
    return rows
