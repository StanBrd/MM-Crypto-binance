import statistics
from typing import List
from collections import deque
from models import OrderBookLevel, SpreadMetrics
import time


import csv

class SpreadAnalyzer:
    def __init__(self, window_size=100):
        self.window_size = window_size
        self.timestamps = deque(maxlen=window_size) 
        self.spread_history = {
            0.1: deque(maxlen=window_size),
            1.0: deque(maxlen=window_size),
            5.0: deque(maxlen=window_size),
            10.0: deque(maxlen=window_size)
        }

        self.timestamps_full = deque()
        self.spread_history_full = {
            0.1: deque(),
            1.0: deque(),
            5.0: deque(),
            10.0: deque(),
        }


    
    def calculate_spread_for_size(self, bids: List[OrderBookLevel], asks: List[OrderBookLevel], target_size: float) -> float:
        """Calculate effective spread for a given order size"""
        if not bids or not asks:
            return 0.0
        
        # Calculate weighted average bid price
        remaining_size = target_size
        total_cost = 0.0
        
        for bid in bids:
            if remaining_size <= 0:
                break
            size_to_take = min(remaining_size, bid.size)
            total_cost += size_to_take * bid.price
            remaining_size -= size_to_take
        
        if remaining_size > 0:
            # Not enough liquidity, use last available price
            if bids:
                total_cost += remaining_size * bids[-1].price
        
        avg_bid_price = total_cost / target_size if target_size > 0 else 0
        
        # Calculate weighted average ask price
        remaining_size = target_size
        total_cost = 0.0
        
        for ask in asks:
            if remaining_size <= 0:
                break
            size_to_take = min(remaining_size, ask.size)
            total_cost += size_to_take * ask.price
            remaining_size -= size_to_take
        
        if remaining_size > 0:
            # Not enough liquidity, use last available price
            if asks:
                total_cost += remaining_size * asks[-1].price
        
        avg_ask_price = total_cost / target_size if target_size > 0 else 0
        
        return avg_ask_price - avg_bid_price
    
        # --- Order Book Imbalance (−1..+1) ---
    @staticmethod
    def _ratio(bid_vol: float, ask_vol: float) -> float:
        denom = bid_vol + ask_vol
        return 0.0 if denom <= 0 else (bid_vol - ask_vol) / denom

    def calc_imbalance_levels(self, bids: List[OrderBookLevel], asks: List[OrderBookLevel], levels: int = 1) -> float:
        """Imbalance en sommant les 'levels' premiers niveaux bid/ask."""
        if not bids or not asks:
            return 0.0
        bid_vol = sum(l.size for l in bids[:levels])
        ask_vol = sum(l.size for l in asks[:levels])
        return self._ratio(bid_vol, ask_vol)

    def calc_imbalance_volume(self, bids: List[OrderBookLevel], asks: List[OrderBookLevel], target_btc: float = 1.0) -> float:
        """Imbalance en sommant le volume cumulé jusqu'à atteindre 'target_btc' des deux côtés."""
        if not bids or not asks or target_btc <= 0:
            return 0.0
        # Bid (liquidité pour VENDRE)
        rem = target_btc
        bid_vol = 0.0
        for l in bids:
            if rem <= 0: break
            take = min(rem, l.size)
            bid_vol += take
            rem -= take
        # Ask (liquidité pour ACHETER)
        rem = target_btc
        ask_vol = 0.0
        for l in asks:
            if rem <= 0: break
            take = min(rem, l.size)
            ask_vol += take
            rem -= take
        return self._ratio(bid_vol, ask_vol)

    
    def update_spreads(self, bids: List[OrderBookLevel], asks: List[OrderBookLevel]):
        self.timestamps.append(time.time())
        self.timestamps_full.append(time.time())
        for size in self.spread_history.keys():
            spread = self.calculate_spread_for_size(bids, asks, size)
            self.spread_history[size].append(spread)
            self.spread_history_full[size].append(spread)
    
    def get_spread_metrics(self, size: float) -> SpreadMetrics:
        spreads = list(self.spread_history[size])
        if not spreads:
            return SpreadMetrics(0, 0, 0, 0)
        
        return SpreadMetrics(
            avg_spread=statistics.mean(spreads),
            med_spread=statistics.median(spreads),
            min_spread=min(spreads),
            max_spread=max(spreads)
        )
    
    def export_spreads_csv(self, filepath: str, use_full: bool = False):
        """Exporte soit la fenêtre roulante, soit l'historique complet."""
        if use_full:
            timestamps = list(self.timestamps_full)
            src = self.spread_history_full
    
        else:
            timestamps = list(self.timestamps)
            src = self.spread_history

        sizes = sorted(src.keys(), key=float)
        rows = []
        for i, ts in enumerate(timestamps):
            row = {"timestamp": ts}
            for size in sizes:
                # sécurise l'index si tailles de listes différentes
                row[str(size)] = src[size][i] if i < len(src[size]) else None
            rows.append(row)

        import csv
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp"] + [str(s) for s in sizes])
            writer.writeheader()
            writer.writerows(rows)