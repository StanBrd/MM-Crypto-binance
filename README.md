# 📊 Binance BTC/USDT Market Making Dashboard

A **real-time trading dashboard** for **Binance BTC/USDT**, featuring:

- 📈 Live **order book visualization**
- 🔴🟢 Real-time **trade stream**
- 📊 **Spread analytics** across multiple sizes
- 🤖 **Market making strategy simulation**
- 💼 **Portfolio tracking** with P&L (realized & unrealized)
- 🎯 **Risk monitoring** and simulated fills

This project connects to **Binance WebSocket streams** and provides a **terminal-based dashboard** built with [Rich](https://github.com/Textualize/rich). It also includes a **simple market making engine** with configurable parameters and portfolio management.

---

## 🚀 Features

- **Real-time Binance order book & trades**
  - Top 10 bid/ask levels updated every 100ms  
  - Recent trades with side & timestamp  

- **Market Making Strategy**
  - Configurable spreads, order sizes, inventory limits  
  - Inventory skew and pressure mechanisms  
  - Risk controls (max exposure, max loss)  

- **Portfolio Manager**
  - Tracks executed trades (simulated fills)  
  - Maintains USD & BTC balances  
  - Calculates **realized, unrealized, and total P&L**  
  - Exports trade and P&L history to CSV  

- **Spread Analyzer**
  - Computes spreads for order sizes (0.1, 1, 5, 10 BTC)  
  - Maintains rolling metrics (avg, median, min, max)  

- **Rich Dashboard**
  - 📈 **Order Book Panel**  
  - 📊 **Spread Analytics Panel**  
  - 🟢🔴 **Recent Trades Panel**  
  - 💼 **Portfolio Status Panel**  
  - 🤖 **Strategy Status Panel**  

---

## 📦 Installation

### 1. Clone the repository
```bash
git clone https://github.com/your-username/binance-market-maker-dashboard.git
cd binance-market-maker-dashboard
