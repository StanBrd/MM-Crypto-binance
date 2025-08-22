#!/usr/bin/env python3
"""
Binance BTC/USDT Trading Dashboard
Real-time order book visualization with spread analytics
"""

from dashboard import TradingDashboard
import websocket
import rich

def check_dependencies():
    """Check if required packages are installed"""
    try:
        import websocket
        import rich
        print("✅ All dependencies are installed")
        return True
    except ImportError as e:
        print("❌ Missing dependencies:")
        print("Please install required packages:")
        print("pip install websocket-client rich")
        return False

def main():
    """Main function to run the trading dashboard"""
    print("🚀 Binance BTC/USDT Trading Dashboard with Market Making")
    print("=" * 60)
    print("📊 Features:")
    print("  - Real-time order book & trades")
    print("  - Spread analytics")
    print("  - Market making strategy")
    print("  - Portfolio tracking")
    print("  - Trade simulation")
    print("=" * 60)
    
    if not check_dependencies():
        return
    
    try:
        dashboard = TradingDashboard()
        dashboard.start()
    except Exception as e:
        print(f"❌ Error starting dashboard: {e}")
        print("Please check your internet connection and try again.")

if __name__ == "__main__":
    main()