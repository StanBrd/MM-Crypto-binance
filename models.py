from dataclasses import dataclass
from datetime import datetime

@dataclass
class OrderBookLevel:
    price: float
    size: float

@dataclass
class Trade:
    timestamp: datetime
    price: float
    size: float
    side: str

@dataclass
class Position:
    btc_balance: float
    usd_exposure: float
    avg_entry: float
    realized_pnl: float
    unrealized_pnl: float

@dataclass
class SpreadMetrics:
    avg_spread: float
    med_spread: float
    min_spread: float
    max_spread: float

@dataclass
class Fill:
    """Représente une exécution d'ordre"""
    timestamp: float
    side: str  # 'buy' ou 'sell'
    price: float
    size: float
    trade_id: str

@dataclass
class PortfolioState:
    """État du portfolio à un instant donné - Market Making approach"""
    # Variables Market Making
    q: float = 0.0             # Position BTC (inventory)
    cash: float = 0.0          # Cash généré par les trades
    nav: float = 0.0           # Net Asset Value (q * fair)
    pnl: float = 0.0           # P&L total (cash + nav)

    # Compteurs utiles pour l'affichage
    btc_balance: float = 0.0
    usd_balance: float = 1_000_000.0
    total_btc_bought: float = 0.0
    total_btc_sold: float = 0.0
    total_usd_spent: float = 0.0
    total_usd_received: float = 0.0

    # P&L exposés (alignés sur la vue MM)
    realized_pnl: float = 0.0   # = cash
    unrealized_pnl: float = 0.0 # = nav

    # Compat éventuelle UI (laissée à 0, non maintenue)
    avg_entry_price: float = 0.0

    total_trades: int = 0