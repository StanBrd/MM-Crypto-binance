import threading
import time
from datetime import datetime
from collections import deque
from typing import List

from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.align import Align

from models import OrderBookLevel, Trade, Position
from binance_client import BinanceWebSocketClient
from spread import SpreadAnalyzer
from strategy import SimpleMarketMaker, MarketMakingConfig
from portfolio import PortfolioManager

class TradingDashboard:
    def __init__(self):
        self.console = Console(force_terminal=True)
        self.layout = Layout()

        # Grille compacte : header, body, footer
        self.layout.split_column(
            Layout(name="header", size=1, minimum_size=1),
            Layout(name="body", ratio=1, minimum_size=12),
            Layout(name="footer", size=1, minimum_size=1),
        )

        # 2 colonnes dans le body
        self.layout["body"].split_row(
            Layout(name="left", ratio=1, minimum_size=10),
            Layout(name="right", ratio=1, minimum_size=10),
        )

      
        self.layout["left"].split_column(
        Layout(name="orderbook", ratio=2, minimum_size=8),
        Layout(name="analytics", ratio=1, minimum_size=6),   # <-- AJOUT
        Layout(name="portfolio", ratio=3, minimum_size=8),
        )


        self.layout["right"].split_column(
            Layout(name="trades", ratio=3, size= 20,minimum_size=4),

            Layout(name="strategy_status", ratio=2, size= 20,minimum_size=4),
        )

        
        # Data storage
        self.bids: List[OrderBookLevel] = []
        self.asks: List[OrderBookLevel] = []
        self.recent_trades: deque = deque(maxlen=10)
        self.position = Position(0, 0, 0, 0, 0)
        self.spread_analyzer = SpreadAnalyzer()
        
        # Trading components
        self.portfolio = PortfolioManager()
        self.strategy_config = MarketMakingConfig()
        self.market_maker = SimpleMarketMaker(self.strategy_config)
        
        # Configuration simple - pas de probabilité
        # self.portfolio.set_debug_mode(True)  # Pour voir les logs
        
        # Auto-start strategy
        self.market_maker.start()
        
        # WebSocket client
        self.ws_client = BinanceWebSocketClient(
            on_orderbook_update=self.on_orderbook_update,
            on_trade_update=self.on_trade_update
        )
        
        # Threading lock for data updates
        self.data_lock = threading.Lock()
        
    def on_orderbook_update(self, bids: List[OrderBookLevel], asks: List[OrderBookLevel]):
        with self.data_lock:
            self.bids = bids[:10]  # Keep top 10 levels
            self.asks = asks[:10]
            self.spread_analyzer.update_spreads(bids, asks)
            self.update_unrealized_pnl()
    
    def on_trade_update(self, trade: Trade):
        with self.data_lock:
            self.recent_trades.append(trade)
            
            # Simulation de fills SYSTÉMATIQUE si la stratégie est active
            if self.market_maker.is_active:
                # Récupérer nos quotes actuelles (peut être None)
                our_bid_price = self.market_maker.current_bid.price if self.market_maker.current_bid else None
                our_ask_price = self.market_maker.current_ask.price if self.market_maker.current_ask else None
                our_bid_size = self.market_maker.current_bid.size if self.market_maker.current_bid else 0.0
                our_ask_size = self.market_maker.current_ask.size if self.market_maker.current_ask else 0.0
                
                # Appel systématique de la simulation (même si quotes sont None)
                fill = self.portfolio.simulate_fill_from_trade(
                    trade,
                    our_bid_price,
                    our_ask_price,
                    our_bid_size,
                    our_ask_size
                )
                
                # Log pour debug - TOUJOURS affiché
                # if our_bid_price or our_ask_price:
                #     print(f"📊 Market Trade: {trade.side} {trade.size:.5f} @ ${trade.price:.2f}")
                #     if our_bid_price:
                #         print(f"   Our Bid: ${our_bid_price:.2f} ({our_bid_size:.3f} BTC)")
                #     if our_ask_price:
                #         print(f"   Our Ask: ${our_ask_price:.2f} ({our_ask_size:.3f} BTC)")
                    
                # if fill:
                #     print(f"🎯 SIMULATED FILL: {fill.side.upper()} {fill.size:.5f} BTC @ ${fill.price:.2f}")
                # else:
                #     # Debug: pourquoi pas de fill ?
                #     if our_bid_price and trade.side == 'sell':
                #         if trade.price <= our_bid_price:
                #             print(f"✅ Bid condition met but no fill generated")
                #         else:
                #             print(f"❌ Trade price ${trade.price:.2f} > our bid ${our_bid_price:.2f}")
                #     elif our_ask_price and trade.side == 'buy':
                #         if trade.price >= our_ask_price:
                #             print(f"✅ Ask condition met but no fill generated")
                #         else:
                #             print(f"❌ Trade price ${trade.price:.2f} < our ask ${our_ask_price:.2f}")
    
    def update_unrealized_pnl(self):
        if self.bids and self.asks:
            current_price = (self.asks[0].price + self.bids[0].price) / 2
            
            # Update portfolio unrealized P&L
            self.portfolio.update_unrealized_pnl(current_price)
            
            # Update strategy quotes
            portfolio_state = self.portfolio.get_portfolio_summary()
            new_bid, new_ask = self.market_maker.update_quotes(
                self.bids, 
                self.asks,
                portfolio_state['btc_balance'],
                portfolio_state['total_pnl'],
                portfolio_state['unrealized_pnl']
            )
            
            # Debug: log des quotes générées
            # if new_bid or new_ask:
            #     print(f"📈 NEW QUOTES: Bid={new_bid.price if new_bid else None}, Ask={new_ask.price if new_ask else None}")
            # elif not self.market_maker.current_bid and not self.market_maker.current_ask:
            #     print(f"⚠️  NO QUOTES: spread={self.asks[0].price - self.bids[0].price:.2f}, mid=${(self.asks[0].price + self.bids[0].price)/2:.2f}")
            
            # Legacy position update
            if self.position.btc_balance != 0 and self.position.avg_entry > 0:
                self.position.unrealized_pnl = (current_price - self.position.avg_entry) * self.position.btc_balance
    
    def create_orderbook_table(self) -> Table:
        """Create order book display table"""
        table = Table(title="📈 ORDER BOOK BTC/USDT", show_header=True, header_style="bold blue")
        table.add_column("BID Price", style="green", justify="right", width=14)
        table.add_column("BID Size", style="green", justify="center", width=12)
        table.add_column("SPREAD", style="yellow", justify="center", width=15)
        table.add_column("ASK Size", style="red", justify="center", width=12)
        table.add_column("ASK Price", style="red", justify="left", width=14)

        
        with self.data_lock:
            if not self.bids or not self.asks:
                table.add_row("", "", "[yellow]Loading...[/yellow]", "", "")
                return table
            
            # Calculate spread ONCE outside the loop using fresh data
            current_spread = self.asks[0].price - self.bids[0].price
            mid_price = (self.asks[0].price + self.bids[0].price) / 2
            spread_bps = (current_spread / mid_price) * 10000
            
            # Show top 7 levels
            max_levels = 7
            asks_display = self.asks[:max_levels]
            bids_display = self.bids[:max_levels]
            
            # NO REVERSE - Keep asks in ascending order so best ask (lowest) is first
            # This way asks[0] (best ask) will be on same row as bids[0] (best bid)
            
            for i in range(max_levels):
                bid_price = f"${bids_display[i].price:,.2f}" if i < len(bids_display) else ""
                bid_size = f"{bids_display[i].size:.5f} BTC" if i < len(bids_display) else ""
                
                ask_price = f"${asks_display[i].price:,.2f}" if i < len(asks_display) else ""
                ask_size = f"{asks_display[i].size:.5f} BTC" if i < len(asks_display) else ""
               
                # First row shows spread (best ask vs best bid)
                if i == 0:  # première ligne : meilleurs prix + spread
                    table.add_row(
                        f"[bold green]{bid_price}[/bold green]", f"[bold green]{bid_size}[/bold green]",
                        f"[bold yellow]${current_spread:.3f}\n({spread_bps:.3f} bps)[/bold yellow]",
                        f"[bold red]{ask_size}[/bold red]", f"[bold red]{ask_price}[/bold red]"
                    )
                else:
                    table.add_row(bid_price, bid_size, "", ask_size, ask_price)
            
        return table
    
    def create_analytics_table(self) -> Table:
        """Create spread analytics table"""
        table = Table(title="📊 SPREAD ANALYTICS", show_header=True, header_style="bold cyan")
        table.add_column("Size (BTC)", justify="center")
        table.add_column("Avg Spread", justify="center")
        table.add_column("Med Spread", justify="center")
        table.add_column("Min", justify="center")
        table.add_column("Max", justify="center")
        
        sizes = [0.1, 1.0, 5.0, 10.0]
        with self.data_lock:
            for size in sizes:
                metrics = self.spread_analyzer.get_spread_metrics(size)
                
                table.add_row(
                    f"{size:.1f}",
                    f"[green]${metrics.avg_spread:.2f}[/green]",
                    f"[cyan]${metrics.med_spread:.2f}[/cyan]",
                    f"[blue]${metrics.min_spread:.2f}[/blue]",
                    f"[red]${metrics.max_spread:.2f}[/red]"
                )

        
        
        return table
    
    def create_trades_panel(self) -> Panel:
        """Create recent trades panel"""
        trades_text = Text()
        
        # Trades info
        trades_text.append("📈 RECENT TRADES\n\n", style="bold yellow")
        
        with self.data_lock:
            if not self.recent_trades:
                trades_text.append("Waiting for trades...", style="dim white")
            else:
                # Show last 8 trades
                recent_list = list(self.recent_trades)[-8:]
                for i, trade in enumerate(recent_list):
                    side_color = "green" if trade.side == "buy" else "red"
                    side_symbol = "🟢" if trade.side == "buy" else "🔴"
                    
                    # Time formatting
                    time_str = trade.timestamp.strftime("%H:%M:%S")
                    
                    trades_text.append(f"{side_symbol} ", style=side_color)
                    trades_text.append(f"{time_str} ", style="dim white")
                    trades_text.append(f"{trade.side.upper():4s} ", style=side_color)
                    trades_text.append(f"{trade.size:8.5f} ", style="white")
                    trades_text.append(f"@ ${trade.price:8,.2f}\n", style="cyan")
                
                # Add separator and summary
                trades_text.append("\n" + "─" * 35 + "\n", style="dim")
                
                if recent_list:
                    last_trade = recent_list[-1]
                    trades_text.append(f"Last: ${last_trade.price:,.2f}\n", style="bold white")
                    
        
        return Panel(
            trades_text,
            border_style="cyan",
            padding=(1, 1)
        )
    
    
    # Mise à jour de la méthode create_portfolio_panel dans dashboard.py
    def create_portfolio_panel(self) -> Panel:
        """Create comprehensive portfolio status panel"""
        portfolio_text = Text()
        
        # En-tête principal
        portfolio_text.append("💼 PORTFOLIO STATUS\n", style="bold cyan")
        portfolio_text.append("─" * 35 + "\n", style="dim")
        
        with self.data_lock:
            portfolio_summary = self.portfolio.get_portfolio_summary()
            
            # 1. EXECUTED TRADES SECTION
            portfolio_text.append("📊 EXECUTED TRADES\n", style="bold yellow")
            portfolio_text.append(f"Total Trades: ", style="white")
            portfolio_text.append(f"{portfolio_summary['total_trades']}\n", style="cyan")
            
            portfolio_text.append(f"Volume Bought: ", style="white")
            portfolio_text.append(f"{self.portfolio.state.total_btc_bought:.5f} BTC\n", style="green")
            
            portfolio_text.append(f"Volume Sold: ", style="white")
            portfolio_text.append(f"{self.portfolio.state.total_btc_sold:.5f} BTC\n", style="red")
            
            # 2. CURRENT POSITION
            portfolio_text.append(f"\n🎯 CURRENT POSITION\n", style="bold yellow")
            
            btc_balance = portfolio_summary['btc_balance']
            position_color = "green" if btc_balance > 0 else "red" if btc_balance < 0 else "white"
            position_type = "LONG" if btc_balance > 0 else "SHORT" if btc_balance < 0 else "FLAT"
            
            portfolio_text.append(f"BTC Balance: ", style="white")
            portfolio_text.append(f"{btc_balance:+.5f} BTC ", style=position_color)
            portfolio_text.append(f"[{position_type}]\n", style=f"bold {position_color}")
            
            # 3. AVERAGE ENTRY PRICE
            portfolio_text.append(f"\n💰 AVERAGE ENTRY PRICE\n", style="bold yellow")
            if portfolio_summary['avg_entry_price'] > 0:
                portfolio_text.append(f"Avg Entry: ", style="white")
                portfolio_text.append(f"${portfolio_summary['avg_entry_price']:,.2f}\n", style="cyan")
            else:
                portfolio_text.append(f"Avg Entry: ", style="white")
                portfolio_text.append(f"N/A (No position)\n", style="dim white")
            
            # 4. EXPOSURE (USD)
            portfolio_text.append(f"\n📏 EXPOSURE (USD)\n", style="bold yellow")
            if self.bids and self.asks and btc_balance != 0:
                current_price = (self.asks[0].price + self.bids[0].price) / 2
                notional_exposure = abs(btc_balance) * current_price
                exposure_pct = (notional_exposure / 1_000_000) * 100  # % of initial capital
                
                portfolio_text.append(f"Exposure: ", style="white")
                portfolio_text.append(f"${notional_exposure:,.0f}\n", style="yellow")
                
                portfolio_text.append(f"Exposure %: ", style="white")
                if exposure_pct > 30:
                    portfolio_text.append(f"{exposure_pct:.1f}% ⚠️\n", style="red")
                elif exposure_pct > 15:
                    portfolio_text.append(f"{exposure_pct:.1f}% ⚡\n", style="yellow")
                else:
                    portfolio_text.append(f"{exposure_pct:.1f}%\n", style="dim yellow")
            else:
                portfolio_text.append(f"Exposure: ", style="white")
                portfolio_text.append(f"$0 (No position)\n", style="dim white")
            
            # 5. REALIZED & UNREALIZED P&L
            portfolio_text.append(f"\n💸 PROFIT & LOSS\n", style="bold yellow")
            
            # Realized P&L
            realized_pnl = portfolio_summary['realized_pnl']
            realized_color = "green" if realized_pnl >= 0 else "red"
            portfolio_text.append(f"Realized P&L: ", style="white")
            portfolio_text.append(f"${realized_pnl:+,.2f}\n", style=realized_color)
            
            # Unrealized P&L
            unrealized_pnl = portfolio_summary['unrealized_pnl']
            unrealized_color = "green" if unrealized_pnl >= 0 else "red"
            portfolio_text.append(f"Unrealized P&L: ", style="white")
            portfolio_text.append(f"${unrealized_pnl:+,.2f}\n", style=unrealized_color)
            
            # Total P&L
            total_pnl = portfolio_summary['total_pnl']
            total_color = "bold green" if total_pnl >= 0 else "bold red"
            portfolio_text.append(f"Total P&L: ", style="bold white")
            portfolio_text.append(f"${total_pnl:+,.2f}\n", style=total_color)
            
            # P&L as percentage of initial capital
            pnl_pct = (total_pnl / 1_000_000) * 100
            pnl_pct_color = "green" if pnl_pct >= 0 else "red"
            portfolio_text.append(f"Return %: ", style="white")
            portfolio_text.append(f"{pnl_pct:+.3f}%\n", style=pnl_pct_color)
            
            # 6. ACCOUNT BALANCES
            # portfolio_text.append(f"\n💵 ACCOUNT BALANCES\n", style="bold yellow")
            # portfolio_text.append(f"USD Balance: ", style="white")
            # portfolio_text.append(f"${portfolio_summary['usd_balance']:,.2f}\n", style="green")
            
            # if self.bids and self.asks:
            #     current_price = (self.asks[0].price + self.bids[0].price) / 2
            #     total_portfolio_value = portfolio_summary['usd_balance'] + (btc_balance * current_price)
            #     portfolio_text.append(f"Total Value: ", style="white")
            #     portfolio_text.append(f"${total_portfolio_value:,.2f}\n", style="bold cyan")
            
            # 7. RECENT ACTIVITY (if space allows)
            recent_fills = portfolio_summary.get('recent_fills', [])
            if recent_fills:
                portfolio_text.append(f"\n🔄 RECENT FILLS\n", style="bold yellow")
                for fill in list(recent_fills)[-3:]:  # Show last 3 fills
                    side_symbol = "🟢" if fill.side == "buy" else "🔴"
                    side_color = "green" if fill.side == "buy" else "red"
                    
                    # Format timestamp
                    try:
                        import time
                        time_str = time.strftime("%H:%M:%S", time.localtime(fill.timestamp))
                    except:
                        time_str = "--:--:--"
                    
                    portfolio_text.append(f"{side_symbol} ", style=side_color)
                    portfolio_text.append(f"{time_str} ", style="dim white")
                    portfolio_text.append(f"{fill.side.upper()} ", style=side_color)
                    portfolio_text.append(f"{fill.size:.3f} @ ", style="white")
                    portfolio_text.append(f"${fill.price:.2f}\n", style="cyan")
        
        return Panel(
            portfolio_text,
            title="Portfolio Dashboard",
            border_style="cyan",
            padding=(1, 1)
        )
    
    def create_strategy_panel(self) -> Panel:
        """Create strategy status panel"""
        strategy_text = Text()
        
        strategy_text.append("🤖 STRATEGY STATUS\n\n", style="bold green")
        
        with self.data_lock:
            status = self.market_maker.get_strategy_status()
            
            # Strategy state
            status_color = "green" if status['active'] else "red"
            status_text = "ACTIVE" if status['active'] else "INACTIVE"
            strategy_text.append(f"Status: {status_text}\n", style=f"bold {status_color}")
            
            strategy_text.append(f"Quotes Updated: {status['quotes_updated']}\n", style="white")
            
            # Current quotes
            if status['current_bid']:
                strategy_text.append(f"\nOur Bid: ", style="white")
                strategy_text.append(f"${status['current_bid'].price:.2f} ", style="green")
                strategy_text.append(f"({status['current_bid'].size:.3f} BTC)\n", style="dim green")
            
            if status['current_ask']:
                strategy_text.append(f"Our Ask: ", style="white")
                strategy_text.append(f"${status['current_ask'].price:.2f} ", style="red")
                strategy_text.append(f"({status['current_ask'].size:.3f} BTC)\n", style="dim red")
            
            # Strategy config
            #strategy_text.append(f"\nBase Spread: {self.strategy_config.base_spread_bps:.1f} bps\n", style="cyan")
            strategy_text.append(f"Base Size: {self.strategy_config.base_order_size:.2f} BTC\n", style="cyan")
 
            
            # Risk limits
            # if self.bids and self.asks:
            #     current_price = (self.asks[0].price + self.bids[0].price) / 2
            #     risk_metrics = self.portfolio.get_risk_metrics(current_price)
                
            #     strategy_text.append(f"\nExposure: ${risk_metrics['notional_exposure']:,.0f} ", style="white")
            #     strategy_text.append(f"({risk_metrics['max_exposure_pct']:.1f}%)\n", style="dim white")
        
        return Panel(
            strategy_text,
            border_style="green", 
            padding=(1, 1)
        )
    
    def create_header(self) -> Panel:
        """Create header with timestamp and status"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "🟢 LIVE" if self.ws_client.is_running else "🔴 DISCONNECTED"
        header_text = Text(f"🚀 BINANCE BTC/USDT TRADING DESK - {now} - {status}", style="bold white")
        return Panel(
            Align.center(header_text),
            style="bold blue"
        )
    
    def create_footer(self) -> Panel:
        """Create footer with key metrics"""
        with self.data_lock:
            if self.asks and self.bids:
                spread = self.asks[0].price - self.bids[0].price
                mid_price = (self.asks[0].price + self.bids[0].price) / 2
                spread_bps = (spread / mid_price) * 10000
                
                # Add timestamp to see if data is updating
                now = datetime.now().strftime("%H:%M:%S.%f")[:-3]  # With milliseconds
                
                footer_text = Text()
                footer_text.append(f"Spread: ${spread:.2f} ({spread_bps:.1f} bps) | ", style="cyan")
                footer_text.append(f"Mid: ${mid_price:,.2f} | ", style="white")
                footer_text.append(f"Best Bid: ${self.bids[0].price:,.2f} | ", style="green")
                footer_text.append(f"Best Ask: ${self.asks[0].price:,.2f} | ", style="red")
                footer_text.append(f"Updated: {now}", style="dim yellow")
            else:
                footer_text = Text("Connecting to Binance WebSocket...", style="yellow")
        
        return Panel(
            Align.center(footer_text),
            style="dim"
        )
    
    def render(self):
        self.layout["header"].update(self.create_header())
        self.layout["orderbook"].update(self.create_orderbook_table())
        self.layout["trades"].update(self.create_trades_panel())
        self.layout["portfolio"].update(self.create_portfolio_panel())
        self.layout["strategy_status"].update(self.create_strategy_panel())
        self.layout["analytics"].update(self.create_analytics_table())  # <-- AJOUT
        self.layout["footer"].update(self.create_footer())
        return self.layout

    
    def start(self):
        """Start the WebSocket connection and dashboard"""
        print("🚀 Starting Binance WebSocket connection...")
        self.ws_client.start()
        
        # Wait a moment for connection to establish
        time.sleep(0.1)
        
        # Start live display
        with Live(self.render(), console=self.console, refresh_per_second=10, screen=True) as live:
            try:
                while True:
                    live.update(self.render())
                    time.sleep(0.1)
                    
            except KeyboardInterrupt:
                print("\n👋 Stopping dashboard...")
                self.market_maker.stop()
                self.ws_client.stop()            
                self.portfolio.export_trades_csv("trades.csv")
                self.portfolio.export_pnl_csv("pnl.csv")
                self.spread_analyzer.export_spreads_csv("spreads.csv", use_full=True)