import csv
import os
from datetime import datetime
from typing import List, Dict
import time

class ExportManager:
    """
    Gestionnaire d'export des données en CSV
    """
    
    def __init__(self, base_dir: str = "exports"):
        self.base_dir = base_dir
        self.ensure_directory_exists()
        
        # Fichiers CSV
        self.trades_file = os.path.join(base_dir, "trade_logs.csv")
        self.pnl_file = os.path.join(base_dir, "pnl_history.csv")
        self.spreads_file = os.path.join(base_dir, "spread_history.csv")
        
        # Initialize CSV files with headers
        self.initialize_csv_files()
        
    def ensure_directory_exists(self):
        """Crée le dossier d'export s'il n'existe pas"""
        os.makedirs(self.base_dir, exist_ok=True)
        
    def initialize_csv_files(self):
        """Initialize CSV files with headers if they don't exist"""
        
        # Trade logs headers
        if not os.path.exists(self.trades_file):
            with open(self.trades_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'datetime', 'side', 'price', 'size', 
                    'trade_id', 'realized_pnl', 'btc_balance', 'usd_balance'
                ])
        
        # P&L history headers  
        if not os.path.exists(self.pnl_file):
            with open(self.pnl_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'datetime', 'btc_balance', 'avg_entry_price',
                    'realized_pnl', 'unrealized_pnl', 'total_pnl', 'current_btc_price',
                    'notional_exposure', 'total_trades'
                ])
                
        # Spread history headers
        if not os.path.exists(self.spreads_file):
            with open(self.spreads_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'datetime', 'best_bid', 'best_ask', 'spread_dollars',
                    'spread_bps', 'mid_price', 'bid_size', 'ask_size'
                ])
    
    def export_trade(self, fill, portfolio_summary: Dict):
        """
        Exporte un trade vers le CSV
        
        Args:
            fill: L'objet Fill du trade
            portfolio_summary: État du portfolio après le trade
        """
        try:
            with open(self.trades_file, 'a', newline='') as f:
                writer = csv.writer(f)
                
                # Convert timestamp to datetime
                dt = datetime.fromtimestamp(fill.timestamp)
                
                writer.writerow([
                    fill.timestamp,
                    dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],  # With milliseconds
                    fill.side,
                    fill.price,
                    fill.size,
                    fill.trade_id,
                    portfolio_summary.get('realized_pnl', 0),
                    portfolio_summary.get('btc_balance', 0),
                    portfolio_summary.get('usd_balance', 0)
                ])
                
        except Exception as e:
            print(f"Erreur export trade: {e}")
    
    def export_pnl_snapshot(self, portfolio_summary: Dict, current_btc_price: float):
        """
        Exporte un snapshot P&L vers le CSV
        
        Args:
            portfolio_summary: État complet du portfolio
            current_btc_price: Prix BTC actuel
        """
        try:
            with open(self.pnl_file, 'a', newline='') as f:
                writer = csv.writer(f)
                
                now = time.time()
                dt = datetime.fromtimestamp(now)
                
                writer.writerow([
                    now,
                    dt.strftime('%Y-%m-%d %H:%M:%S'),
                    portfolio_summary.get('btc_balance', 0),
                    portfolio_summary.get('avg_entry_price', 0),
                    portfolio_summary.get('realized_pnl', 0),
                    portfolio_summary.get('unrealized_pnl', 0),
                    portfolio_summary.get('total_pnl', 0),
                    current_btc_price,
                    portfolio_summary.get('notional_exposure', 0),
                    portfolio_summary.get('total_trades', 0)
                ])
                
        except Exception as e:
            print(f"Erreur export P&L: {e}")
    
    def export_spread_snapshot(self, bids: List, asks: List):
        """
        Exporte un snapshot de spread vers le CSV
        
        Args:
            bids: Liste des bids (OrderBookLevel)
            asks: Liste des asks (OrderBookLevel)
        """
        if not bids or not asks:
            return
            
        try:
            with open(self.spreads_file, 'a', newline='') as f:
                writer = csv.writer(f)
                
                now = time.time()
                dt = datetime.fromtimestamp(now)
                
                best_bid = bids[0].price
                best_ask = asks[0].price
                spread_dollars = best_ask - best_bid
                mid_price = (best_bid + best_ask) / 2
                spread_bps = (spread_dollars / mid_price) * 10000
                
                writer.writerow([
                    now,
                    dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
                    best_bid,
                    best_ask,
                    spread_dollars,
                    spread_bps,
                    mid_price,
                    bids[0].size,
                    asks[0].size
                ])
                
        except Exception as e:
            print(f"Erreur export spread: {e}")
    
    def export_full_portfolio_report(self, portfolio_manager, current_btc_price: float):
        """
        Exporte un rapport complet du portfolio
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = os.path.join(self.base_dir, f"portfolio_report_{timestamp}.csv")
        
        try:
            summary = portfolio_manager.get_detailed_portfolio_summary(current_btc_price)
            
            with open(filename, 'w', newline='') as f:
                writer = csv.writer(f)
                
                # Header
                writer.writerow(['Portfolio Report', timestamp])
                writer.writerow([])  # Empty line
                
                # Summary data
                writer.writerow(['Metric', 'Value'])
                for key, value in summary.items():
                    if key != 'recent_fills':  # Skip complex objects
                        writer.writerow([key, value])
                
                # Recent fills section
                writer.writerow([])
                writer.writerow(['Recent Fills'])
                writer.writerow(['Timestamp', 'Side', 'Price', 'Size', 'Trade ID'])
                
                for fill in summary.get('recent_fills', []):
                    dt = datetime.fromtimestamp(fill.timestamp)
                    writer.writerow([
                        dt.strftime('%Y-%m-%d %H:%M:%S'),
                        fill.side,
                        fill.price,
                        fill.size,
                        fill.trade_id
                    ])
            
            print(f"✅ Rapport portfolio exporté: {filename}")
            return filename
            
        except Exception as e:
            print(f"Erreur export rapport: {e}")
            return None
    
    def get_export_summary(self) -> Dict:
        """
        Retourne un résumé des exports disponibles
        """
        summary = {
            'trades_count': 0,
            'pnl_snapshots': 0,
            'spread_snapshots': 0,
            'files': []
        }
        
        try:
            # Count lines in each file
            if os.path.exists(self.trades_file):
                with open(self.trades_file, 'r') as f:
                    summary['trades_count'] = sum(1 for line in f) - 1  # -1 for header
                    
            if os.path.exists(self.pnl_file):
                with open(self.pnl_file, 'r') as f:
                    summary['pnl_snapshots'] = sum(1 for line in f) - 1
                    
            if os.path.exists(self.spreads_file):
                with open(self.spreads_file, 'r') as f:
                    summary['spread_snapshots'] = sum(1 for line in f) - 1
            
            # List all files in export directory
            if os.path.exists(self.base_dir):
                summary['files'] = [f for f in os.listdir(self.base_dir) if f.endswith('.csv')]
                
        except Exception as e:
            print(f"Erreur lecture exports: {e}")
            
        return summary