import time
from typing import List, Optional
from dataclasses import dataclass
from collections import deque
from models import Trade

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

    # Prix moyen d'entrée de la position COURANTE (long ou short)
    avg_entry_price: float = 0.0

    total_trades: int = 0

class PortfolioManager:
    """
    Gestionnaire de portfolio pour le market making

    Décomposition P&L:
    - cash: flux des fills (réalisé au sens MM)
    - q: position BTC (inventory)
    - nav: q * fair_price (valeur de l'inventaire)
    - pnl: cash + nav (P&L total)
    """

    def __init__(self, initial_usd: float = 1_000_000.0, max_inventory: float = 5.0):
        self.state = PortfolioState(usd_balance=initial_usd)

        # Limites d'inventaire
        self.max_inventory = max_inventory
        self.min_inventory = -max_inventory

        # Historique
        self.fills_history: deque = deque(maxlen=1000)
        self.recent_fills: deque = deque(maxlen=10)
        self.pnl_history: List[float] = []

        print(f"🏦 Portfolio initialized: cash={self.state.cash}, q={self.state.q}, max_inventory=±{self.max_inventory}")

    def simulate_fill_from_trade(
        self,
        market_trade: Trade,
        our_bid_price: Optional[float],
        our_ask_price: Optional[float],
        our_bid_size: float,
        our_ask_size: float
    ) -> Optional[Fill]:
        """
        Simule si un trade du marché exécute nos ordres selon la logique market making
        """
        fill = None

        # Notre bid exécuté (on ACHÈTE)
        if (our_bid_price and our_bid_size > 0 and
            market_trade.side == 'sell' and
            market_trade.price <= our_bid_price):

            fill_size = min(our_bid_size, market_trade.size)
            max_buy_size = self.max_inventory - self.state.q
            if max_buy_size <= 0:
                return None
            fill_size = min(fill_size, max_buy_size)
            if fill_size <= 0:
                return None

            fill = Fill(
                timestamp=time.time(),
                side='buy',
                price=our_bid_price,
                size=fill_size,
                trade_id=f"fill_bid_{int(time.time()*1000000)}"
            )

        # Notre ask exécuté (on VEND)
        elif (our_ask_price and our_ask_size > 0 and
              market_trade.side == 'buy' and
              market_trade.price >= our_ask_price):

            fill_size = min(our_ask_size, market_trade.size)
            max_sell_size = self.state.q - self.min_inventory
            if max_sell_size <= 0:
                return None
            fill_size = min(fill_size, max_sell_size)
            if fill_size <= 0:
                return None

            fill = Fill(
                timestamp=time.time(),
                side='sell',
                price=our_ask_price,
                size=fill_size,
                trade_id=f"fill_ask_{int(time.time()*1000000)}"
            )

        if fill:
            self.process_fill_market_making(fill)

        return fill

    def process_fill_market_making(self, fill: Fill):
        """
        Traite une exécution selon la logique market making

        - BID fill (achat):   new_q = min(q + size, max_inventory), cash -= (new_q - q) * price
        - ASK fill (vente):   new_q = max(q - size, min_inventory), cash += (q - new_q) * price
        """
        old_q = self.state.q

        if fill.side == 'buy':
            new_q = min(old_q + fill.size, self.max_inventory)
            actual_fill_size = new_q - old_q
            if actual_fill_size <= 0:
                return
            self.state.cash -= actual_fill_size * fill.price
            self.state.q = new_q
        else:  # 'sell'
            new_q = max(old_q - fill.size, self.min_inventory)
            actual_fill_size = old_q - new_q
            if actual_fill_size <= 0:
                return
            self.state.cash += actual_fill_size * fill.price
            self.state.q = new_q

        # --- Mise à jour de l'avg entry (sans FIFO) ---
        self._update_avg_entry_price_on_fill(fill.side, fill.price, actual_fill_size, old_q, self.state.q)

        # Historique & compteurs
        self.fills_history.append(fill)
        self.recent_fills.append(fill)
        self.state.total_trades += 1

        # Compteurs simples pour l'UI (utiliser la taille réellement exécutée)
        self.state.btc_balance = self.state.q
        if fill.side == 'buy':
            self.state.total_btc_bought += actual_fill_size
            self.state.total_usd_spent += actual_fill_size * fill.price
        else:
            self.state.total_btc_sold += actual_fill_size
            self.state.total_usd_received += actual_fill_size * fill.price

    def _update_avg_entry_price_on_fill(self, side: str, price: float, executed: float, q_before: float, q_after: float):
        """
        Met à jour avg_entry_price pour la position COURANTE, sans FIFO.

        Règles:
        - Renforcement du même côté: moyenne pondérée.
        - Réduction: inchangé.
        - Croisement de 0: reset au prix du fill (ou 0 si flat exact).
        """
        if executed <= 0:
            return

        avg = self.state.avg_entry_price

        if side == 'buy':
            if q_before >= 0:
                # On renforce / ouvre un long
                base = q_before
                add = executed
                self.state.avg_entry_price = ((avg * base) + (price * add)) / (base + add) if (base + add) > 0 else 0.0
            else:
                # On couvre un short
                cover = min(executed, -q_before)
                remainder = executed - cover  # ouvre un long si > 0
                if q_after < 0:
                    # Toujours short -> average inchangé
                    return
                elif q_after == 0:
                    # Flat -> plus de position
                    self.state.avg_entry_price = 0.0
                else:
                    # On vient d'ouvrir un long
                    self.state.avg_entry_price = price

        else:  # side == 'sell'
            if q_before <= 0:
                # On renforce / ouvre un short
                base = -q_before  # quantité positive
                add = executed
                self.state.avg_entry_price = ((avg * base) + (price * add)) / (base + add) if (base + add) > 0 else 0.0
            else:
                # On réduit un long (ou on bascule short)
                reduce = min(executed, q_before)
                remainder = executed - reduce  # ouvre un short si > 0
                if q_after > 0:
                    # Toujours long -> average inchangé
                    return
                elif q_after == 0:
                    # Flat
                    self.state.avg_entry_price = 0.0
                else:
                    # On vient d'ouvrir un short
                    self.state.avg_entry_price = price

    def update_nav_and_pnl(self, fair_price: float):
        """
        Met à jour la NAV et le P&L (vue market making):
        nav = q * fair_price
        pnl = cash + nav
        """
        self.state.nav = self.state.q * fair_price
        old_pnl = self.state.pnl
        self.state.pnl = self.state.cash + self.state.nav

        # P&L MM exposés
        self.state.realized_pnl = self.state.cash
        self.state.unrealized_pnl = self.state.nav

        # Historique P&L
        self.pnl_history.append(self.state.pnl)
        if len(self.pnl_history) > 1000:
            self.pnl_history.pop(0)

        # if abs(self.state.pnl - old_pnl) > 10 or len(self.pnl_history) % 100 == 0:
        #     print(f"📊 P&L Update: cash=${self.state.cash:.2f}, nav=${self.state.nav:.2f}, total=${self.state.pnl:.2f}")

    def update_unrealized_pnl(self, current_btc_price: float):
        """Alias pour MAJ mark-to-market avec le prix courant"""
        self.update_nav_and_pnl(current_btc_price)

    # ---- Résumés / métriques / exports ----

    def get_portfolio_summary(self) -> dict:
        """Résumé du portfolio - version market making"""
        return {
            'btc_balance': self.state.q,
            'usd_balance': self.state.usd_balance,

            'avg_entry_price': self.state.avg_entry_price,

            'realized_pnl': self.state.cash,    # Cash généré
            'unrealized_pnl': self.state.nav,   # Valeur inventaire
            'total_pnl': self.state.pnl,        # Cash + NAV

            'total_trades': self.state.total_trades,
            'recent_fills': list(self.recent_fills),

            # Compteurs d'activité
            'total_btc_bought': self.state.total_btc_bought,
            'total_btc_sold': self.state.total_btc_sold,
            'total_usd_spent': self.state.total_usd_spent,
            'total_usd_received': self.state.total_usd_received,

            # Exposition notionnelle (USD): ≈ |q| * fair = |nav|
            'notional_exposure': abs(self.state.nav),

            # Nouvelles métriques market making
            'cash': self.state.cash,
            'position_q': self.state.q,
            'nav': self.state.nav,
            'inventory_limit': f"±{self.max_inventory}",
            'inventory_utilization': abs(self.state.q) / self.max_inventory * 100,
        }

    def get_risk_metrics(self, current_price: float) -> dict:
        """Métriques de risque - version market making"""
        notional_exposure = abs(self.state.q) * current_price
        return {
            'notional_exposure': notional_exposure,
            'total_pnl': self.state.pnl,
            'position_size': self.state.q,
            'avg_entry': self.state.avg_entry_price,
            'max_exposure_pct': (notional_exposure / 1_000_000) * 100,
            'loss_pct': (self.state.pnl / 1_000_000) * 100 if self.state.pnl < 0 else 0,
            'inventory_utilization': abs(self.state.q) / self.max_inventory * 100,
            'cash_generated': self.state.cash,
            'inventory_value': self.state.nav,
        }

    def get_market_making_metrics(self) -> dict:
        """Métriques spécifiques au market making"""
        return {
            'total_cash_generated': self.state.cash,
            'current_inventory': self.state.q,
            'inventory_limits': f"[{self.min_inventory:.1f}, {self.max_inventory:.1f}]",
            'inventory_utilization_pct': abs(self.state.q) / self.max_inventory * 100,
            'nav': self.state.nav,
            'total_pnl': self.state.pnl,
            'pnl_history_length': len(self.pnl_history),
            'max_pnl': max(self.pnl_history) if self.pnl_history else 0,
            'min_pnl': min(self.pnl_history) if self.pnl_history else 0,
        }

    def export_trades_csv(self, filepath: str) -> None:
        """Export executed trade logs (fills) to CSV."""
        import csv, datetime
        with open(filepath, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "side", "price", "size", "trade_id"])
            for fill in self.fills_history:
                ts = datetime.datetime.fromtimestamp(fill.timestamp).isoformat()
                w.writerow([ts, fill.side, f"{fill.price:.8f}", f"{fill.size:.8f}", fill.trade_id])

    def export_pnl_csv(self, filepath: str) -> None:
        """Export current P&L snapshot to CSV - Market Making version."""
        import csv
        with open(filepath, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "cash", "position_q", "nav", "total_pnl", "total_trades",
                "inventory_utilization_pct", "max_inventory", "avg_entry_price"
            ])
            inventory_util = abs(self.state.q) / self.max_inventory * 100
            w.writerow([
                f"{self.state.cash:.2f}", f"{self.state.q:.8f}", f"{self.state.nav:.2f}",
                f"{self.state.pnl:.2f}", self.state.total_trades,
                f"{inventory_util:.1f}", self.max_inventory, f"{self.state.avg_entry_price:.2f}"
            ])

    def export_pnl_history_csv(self, filepath: str) -> None:
        """Export P&L history for analysis."""
        import csv
        with open(filepath, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["index", "pnl"])
            for i, pnl in enumerate(self.pnl_history):
                w.writerow([i, f"{pnl:.2f}"])

    # ---- Outils & diagnostics optionnels ----

    def set_debug_mode(self, debug: bool):
        """Active/désactive les logs de debug"""
        self.debug_mode = debug

    def get_detailed_portfolio_summary(self, current_btc_price: float = None) -> dict:
        """Version détaillée (aggrège les métriques MM et le résumé)"""
        if current_btc_price is not None:
            self.update_nav_and_pnl(current_btc_price)
        summary = self.get_portfolio_summary()
        summary.update(self.get_market_making_metrics())
        return summary

    def get_portfolio_health_check(self, current_btc_price: float) -> dict:
        """Évalue la santé du portfolio - version market making"""
        self.update_nav_and_pnl(current_btc_price)

        alerts = []
        risk_level = "LOW"

        # Utilisation de l'inventaire
        inventory_util = abs(self.state.q) / self.max_inventory * 100
        if inventory_util > 80:
            alerts.append("⚠️ High inventory utilization (>80%)")
            risk_level = "HIGH"
        elif inventory_util > 60:
            alerts.append("⚡ Medium inventory utilization (>60%)")
            risk_level = "MEDIUM"

        # P&L
        if self.state.pnl < -50000:
            alerts.append("🚨 Large loss (>$50k)")
            risk_level = "HIGH"
        elif self.state.pnl < -10000:
            alerts.append("📉 Moderate loss (>$10k)")
            if risk_level == "LOW":
                risk_level = "MEDIUM"

        return {
            'risk_level': risk_level,
            'alerts': alerts,
            'health_score': self._calculate_mm_health_score(),
            'recommendations': self._get_mm_recommendations()
        }

    def _calculate_mm_health_score(self) -> int:
        """Score de santé pour market making (0-100)"""
        score = 100

        # Pénalité inventaire élevé
        inventory_util = abs(self.state.q) / self.max_inventory * 100
        if inventory_util > 80:
            score -= 30
        elif inventory_util > 60:
            score -= 15

        # Pénalité P&L négatif
        if self.state.pnl < -50000:
            score -= 25
        elif self.state.pnl < -10000:
            score -= 10

        # Bonus P&L positif
        if self.state.pnl > 0:
            score += min(10, self.state.pnl / 10000)

        return max(0, min(100, score))

    def _get_mm_recommendations(self) -> List[str]:
        """Recommandations pour market making"""
        recommendations = []

        inventory_util = abs(self.state.q) / self.max_inventory * 100

        if inventory_util > 70:
            recommendations.append("Reduce inventory exposure - adjust skew")

        if abs(self.state.q) > self.max_inventory * 0.8:
            recommendations.append("Near inventory limits - consider position reduction")

        if self.state.pnl < -20000:
            recommendations.append("Large drawdown - review strategy parameters")

        if len(self.fills_history) > 20:
            recent_fills = list(self.fills_history)[-20:]
            buy_fills = [f for f in recent_fills if f.side == 'buy']
            sell_fills = [f for f in recent_fills if f.side == 'sell']

            if len(buy_fills) > len(sell_fills) * 1.5:
                recommendations.append("Buying bias detected - consider tightening bid")
            elif len(sell_fills) > len(buy_fills) * 1.5:
                recommendations.append("Selling bias detected - consider tightening ask")

        return recommendations
