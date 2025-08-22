import websocket
import json
import threading
from datetime import datetime
from models import OrderBookLevel, Trade

class BinanceWebSocketClient:
    def __init__(self, on_orderbook_update, on_trade_update):
        self.on_orderbook_update = on_orderbook_update
        self.on_trade_update = on_trade_update
        self.ws = None
        self.is_running = False
        
        # Binance WebSocket URLs
        self.base_url = "wss://stream.binance.com/stream?streams="
        self.streams = "btcusdt@depth20@100ms/btcusdt@trade"
        
    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            
            if 'stream' in data:
                stream = data['stream']
                payload = data['data']
                
                if 'depth20' in stream:
                    self.handle_orderbook_update(payload)
                elif 'trade' in stream:
                    self.handle_trade_update(payload)
            else:
                # Direct message format
                if 'lastUpdateId' in data:
                    self.handle_orderbook_update(data)
                elif 'e' in data and data['e'] == 'trade':
                    self.handle_trade_update(data)
                    
        except Exception as e:
            print(f"Error processing message: {e}")
    
    def handle_orderbook_update(self, data):
        try:
            bids = [OrderBookLevel(float(bid[0]), float(bid[1])) 
                   for bid in data['bids'] if float(bid[1]) > 0]
            asks = [OrderBookLevel(float(ask[0]), float(ask[1])) 
                   for ask in data['asks'] if float(ask[1]) > 0]
            
            # Sort bids descending, asks ascending
            bids.sort(key=lambda x: x.price, reverse=True)
            asks.sort(key=lambda x: x.price)
            
            self.on_orderbook_update(bids, asks)
        except Exception as e:
            print(f"Error handling orderbook: {e}")
    
    def handle_trade_update(self, data):
        try:
            trade = Trade(
                timestamp=datetime.fromtimestamp(data['T'] / 1000),
                price=float(data['p']),
                size=float(data['q']),
                side='buy' if data['m'] == False else 'sell'  # m=true means buyer is market maker
            )
            self.on_trade_update(trade)
        except Exception as e:
            print(f"Error handling trade: {e}")
    
    def on_error(self, ws, error):
        print(f"WebSocket error: {error}")
    
    def on_close(self, ws, close_status_code, close_msg):
        print("WebSocket connection closed")
        self.is_running = False
    
    def on_open(self, ws):
        print("WebSocket connection opened")
        self.is_running = True
    
    def start(self):
        websocket.enableTrace(False)
        self.ws = websocket.WebSocketApp(
            f"{self.base_url}{self.streams}",
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self.on_open
        )
        
        # Run in separate thread
        self.ws_thread = threading.Thread(target=self.ws.run_forever)
        self.ws_thread.daemon = True
        self.ws_thread.start()
    
    def stop(self):
        self.is_running = False
        if self.ws:
            self.ws.close()