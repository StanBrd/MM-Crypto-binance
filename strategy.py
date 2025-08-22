import time
from typing import List, Optional, Tuple
from dataclasses import dataclass
from models import OrderBookLevel, Trade

@dataclass
class Quote:
    """Représente une quote (bid ou ask) à poster"""
    side: str  # 'bid' ou 'ask'
    price: float
    size: float
    timestamp: float

@dataclass
class MarketMakingConfig:
    """Configuration de la stratégie de market making"""
    # Paramètres de spread
    base_spread_bps: float = 10.0  # Spread de base en points de base 
    min_spread_bps: float = 5.0    # Spread minimum
    max_spread_bps: float = 50.0   # Spread maximum
    
    # Tailles des ordres
    base_order_size: float = 0.05   # Taille de base en BTC
    max_order_size: float = 1.0    # Taille maximum
    

    
    # Limites de risque
    max_notional_exposure: float = 1_000_000  # $1M max
    max_loss_allowed: float = 100_000         # $100k max loss
    
    # Paramètres de timing
    quote_refresh_interval: float = 0.1# Secondes entre refresh des quotes
    tick_size: float = 0.01              # taille de tick pour éviter de croiser

    asym_deadband_pct: float = 0.20   # zone morte: pas d'ajustement ≤ 20%
    asym_bps_step: float = 2.0        # taille d’un palier en bps (ex: 2 → 2/4/6 bps)

class SimpleMarketMaker:
    """
    Stratégie de market making simple
    
    Logique:
    1. Calcule un fair price (mid-price)
    2. Poste des bids/asks autour du fair price avec un spread
    3. Ajuste les quotes selon la position (inventory skew)
    4. Respecte les limites de risque
    """
    
    def __init__(self, config: MarketMakingConfig):
        self.config = config
        
        # État de la stratégie
        self.is_active = False
        self.last_quote_time = 0
        
        # Quotes actuelles
        self.current_bid: Optional[Quote] = None
        self.current_ask: Optional[Quote] = None
        
        # Métriques de performance
        self.quotes_posted = 0
        self.quotes_updated = 0
        
    def calculate_fair_price(self, bids: List[OrderBookLevel], asks: List[OrderBookLevel]) -> Optional[float]:
        """
        Calcule le fair price (prix de référence)
        
        Méthodes possibles:
        - Mid-price simple: (best_bid + best_ask) / 2
        - Weighted mid: selon les volumes
        - Micro-price: selon les probabilités d'exécution
        
        Pour l'instant: mid-price simple
        """
        if not bids or not asks:
            return None
            
        best_bid = bids[0].price
        best_ask = asks[0].price
        
        # Vérification de cohérence
        if best_ask <= best_bid:
            return None
            
        return (best_bid + best_ask) / 2.0
    

    
    def calculate_order_size(self, current_position: float, side: str) -> float:
        """
        Taille d'ordre strictement identique sur bid et ask.
        La gestion d'inventaire se fait uniquement via le prix (skew/spread),
        et via _check_risk_limits qui peut couper les quotes si on dépasse.
        """
        base = self.config.base_order_size
        return max(0.01, min(base, self.config.max_order_size))
    
    def generate_quotes(self, 
                        bids: List[OrderBookLevel], 
                        asks: List[OrderBookLevel],
                        current_position: float = 0.0,
                        total_pnl: float = 0.0,
                        unrealized_pnl: float = 0.0) -> Tuple[Optional[Quote], Optional[Quote]]:

        # 1) Fair et best levels
        fair_price = self.calculate_fair_price(bids, asks)
        if fair_price is None:
            return None, None

        best_bid = bids[0].price
        best_ask = asks[0].price
        if best_ask <= best_bid:
            return None, None

        # 2) RISK: coupe si drawdown / notions / inventaire dépassés
        if self._check_risk_limits(current_position, total_pnl, fair_price):
            return None, None

        # 3) Base: toujours au top-of-book
        bid_price = best_bid
        ask_price = best_ask

        # 4) Tilt unilatéral quand |expo| >= trigger
        #    expo = q / max_inv ; util ~ [-1, +1]
               # 4) Asymétrie par paliers (un seul côté ajusté)
        #    expo = q / max_inv ∈ [-1, +1]

        notional_exposure = abs(current_position) * fair_price
       
        expo = notional_exposure / self.config.max_notional_exposure
  

        expo_abs = abs(expo)
        deadband = getattr(self.config, "asym_deadband_pct", 0.20)  # 20% par défaut
        step_bps = getattr(self.config, "asym_bps_step", 2.0)       # 2 bps par défaut

        # Détermine l'offset en bps selon le palier
        if expo_abs <= deadband:
            off_bps = 0.0
        elif expo_abs <= 0.40:
            off_bps = 1 * step_bps
        elif expo_abs <= 0.60:
            off_bps = 2 * step_bps
        else:
            off_bps = 3 * step_bps

        if off_bps > 0.0:
            off_usd = fair_price * off_bps / 10000.0
            if expo > 0:
                # Long -> on pousse la vente : ask plus agressif (plus bas)
                ask_price = max(best_bid + self.config.tick_size, best_ask - off_usd)
                # bid reste top-of-book (inchangé)
            elif expo < 0:
                # Short -> on pousse le rachat : bid plus agressif (plus haut)
                bid_price = min(best_ask - self.config.tick_size, best_bid + off_usd)
                # ask reste top-of-book (inchangé)
            # si expo == 0 : off_bps==0, donc pas d’ajustement

        # 6) Tailles (inchangé)
        bid_size = self.calculate_order_size(current_position, 'bid')
        ask_size = self.calculate_order_size(current_position, 'ask')

        now = time.time()
        bid_quote = Quote('bid', bid_price, bid_size, now) if bid_size > 0.01 else None
        ask_quote = Quote('ask', ask_price, ask_size, now) if ask_size > 0.01 else None
        return bid_quote, ask_quote

    
    def _check_risk_limits(self, 
                        current_position: float, 
                        total_pnl: float, 
                        current_price: float) -> bool:
        # 1. position max
      
        # 2. notionnel
        notional_exposure = abs(current_position) * current_price
        if notional_exposure > self.config.max_notional_exposure:
            return True
        # 3. perte max – sur le P&L total
        if total_pnl < -self.config.max_loss_allowed:
            return True
        return False
    
    def should_update_quotes(self) -> bool:
        """
        Détermine s'il faut mettre à jour les quotes
        
        Critères:
        - Temps écoulé depuis dernière mise à jour
       
        """
        current_time = time.time()
        
        # Mise à jour périodique
        if current_time - self.last_quote_time > self.config.quote_refresh_interval:
            return True
            
        return False
    
    def update_quotes(self, 
                     bids: List[OrderBookLevel], 
                     asks: List[OrderBookLevel],
                     current_position: float = 0.0,
                     total_pnl: float = 0.0,
                     unrealized_pnl: float = 0.0) -> Tuple[Optional[Quote], Optional[Quote]]:
        """
        Met à jour les quotes si nécessaire
        
        Returns:
            Nouvelles quotes à poster (None si pas de changement)
        """
        if not self.should_update_quotes():
            return None, None
            
        # Génère nouvelles quotes
        new_bid, new_ask = self.generate_quotes(bids, asks, current_position, total_pnl ,unrealized_pnl)
        
        # Vérifie si les quotes ont changé significativementPar contre je veux que dans port
        bid_changed = self._quote_changed(self.current_bid, new_bid)
        ask_changed = self._quote_changed(self.current_ask, new_ask)
        
        if bid_changed or ask_changed:
            self.current_bid = new_bid
            self.current_ask = new_ask
            self.last_quote_time = time.time()
            self.quotes_updated += 1
            
            return new_bid, new_ask
            
        return None, None
    
    
    
    def _quote_changed(self, old_quote: Optional[Quote], new_quote: Optional[Quote]) -> bool:
        """Vérifie si une quote a changé significativement"""
        if old_quote is None and new_quote is None:
            return False
        if old_quote is None or new_quote is None:
            return True
            
        # Changement de prix > $0.01 ou de taille > 0.01 BTC
        price_changed = abs(old_quote.price - new_quote.price) > 0.01
        size_changed = abs(old_quote.size - new_quote.size) > 0.01
        
        return price_changed or size_changed
    
    def start(self):
        """Démarre la stratégie"""
        self.is_active = True
        self.quotes_posted = 0
        self.quotes_updated = 0
        print("🤖 Market Making strategy started")
    
    def stop(self):
        """Arrête la stratégie"""
        self.is_active = False
        self.current_bid = None
        self.current_ask = None
        print("🛑 Market Making strategy stopped")
    
    def get_strategy_status(self) -> dict:
        """Retourne l'état de la stratégie pour l'affichage"""
        return {
            'active': self.is_active,
            'quotes_posted': self.quotes_posted,
            'quotes_updated': self.quotes_updated,
            'current_bid': self.current_bid,
            'current_ask': self.current_ask,
            'last_update': self.last_quote_time
        }