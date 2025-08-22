# analyze.py
# Calcule le P&L (cash, realized, unrealized, total) depuis trades.csv,
# sauvegarde pnl_from_trades.csv et trace la courbe P&L (Plotly).
# Peut aussi tracer le spread si spreads.csv est fourni.
#
# Usage:
#   python analyze.py --trades trades.csv [--spreads spreads.csv] [--markcol fair_price] [--max-inventory 5]

import csv, argparse, os, math
from datetime import datetime
import plotly.graph_objects as go

# ---------- I/O ----------
def load_csv(path):
    if not os.path.exists(path):
        print(f"[!] Fichier introuvable: {path}")
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def save_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

def parse_float(x, default=float("nan")):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default

# ---------- time parsing ----------
def parse_time_any(s):
    """
    Parse ISO (gère le 'Z'), ou epoch (secondes/millisecondes).
    Retourne datetime si possible, sinon la chaîne.
    """
    if s is None or s == "":
        return "n/a"
    # epoch ? (numérique)
    try:
        v = float(s)
        if v > 1e12:   # ms
            v /= 1000.0
        return datetime.fromtimestamp(v)
    except Exception:
        pass
    # ISO (avec Z → +00:00)
    s = str(s)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return s

def first_time_field_name(row, candidates=("timestamp_iso","timestamp","time","ts","datetime","date","created_at")):
    for k in candidates:
        if k in row and row.get(k) not in (None, ""):
            return k
    # heuristique
    for k in row.keys():
        kk = k.lower()
        if "time" in kk or "date" in kk or kk == "ts":
            return k
    return None

# ---------- résumé ----------
def summarize_trades(rows):
    print("\n=== TRADES ===")
    if not rows:
        print("Aucune donnée.")
        return
    n = len(rows)
    buys = [r for r in rows if str(r.get("side","")).lower().startswith("b")]
    sells = [r for r in rows if str(r.get("side","")).lower().startswith("s")]
    vol_buy = sum(abs(parse_float(r.get("size"))) for r in buys)
    vol_sell = sum(abs(parse_float(r.get("size"))) for r in sells)
    print(f"Nombre de trades : {n}")
    print(f" - Buys  : {len(buys)} | Volume ~ {vol_buy:.8f}")
    print(f" - Sells : {len(sells)} | Volume ~ {vol_sell:.8f}")
    tcol = first_time_field_name(rows[0]) or "timestamp"
    print("Période : {} → {}".format(rows[0].get(tcol, "n/a"), rows[-1].get(tcol, "n/a")))

# ---------- calcul PnL depuis trades ----------
def compute_pnl_from_trades(trades_rows, mark_col=None, max_inventory=None):
    """
    Calcule q, cash, realized, unrealized, total P&L depuis une séquence de fills.
    Convention:
      - BUY (notre bid exécuté)  -> dq = +size
      - SELL (notre ask exécuté) -> dq = -size
      - cash -= dq * price  (paie à l'achat, encaisse à la vente)

    Décomposition:
      - realized_pnl   = cash + q * avg_cost
      - unrealized_pnl = (mark - avg_cost) * q
      - total_pnl      = realized_pnl + unrealized_pnl = cash + q * mark

    Si max_inventory est fourni: new_q = clip(q + dq, [-max_inv, +max_inv]).
    """
    if not trades_rows:
        return []

    # Tri temporel stable
    tcol = first_time_field_name(trades_rows[0]) or "timestamp"
    rows = sorted(trades_rows, key=lambda r: parse_time_any(r.get(tcol)))

    q = 0.0           # position (BTC)
    ac = 0.0          # average cost de la jambe ouverte (USD/BTC)
    cash = 0.0        # compte cash (USD)
    realized = 0.0    # réalisé cumulé (USD)

    out = []
    for r in rows:
        side = str(r.get("side","")).lower()
        price = parse_float(r.get("price"))
        size  = abs(parse_float(r.get("size")))
        if not (math.isfinite(price) and math.isfinite(size)):
            continue

        # direction: +1 buy, -1 sell
        s = +1.0 if side.startswith("b") else -1.0
        desired_q = q + s * size

        # Clip inventaire si demandé
        if max_inventory is not None and math.isfinite(max_inventory) and max_inventory > 0:
            new_q = max(-max_inventory, min(desired_q, +max_inventory))
        else:
            new_q = desired_q

        dq = new_q - q  # quantité effectivement échangée
        if abs(dq) < 1e-15:
            # rien exécuté (tout a été clippé)
            mark = price if (mark_col is None or mark_col not in r) else parse_float(r.get(mark_col), price)
            unrealized = (mark - ac) * q
            total = realized + unrealized
            out.append({
                "timestamp": r.get(tcol),
                "side": r.get("side"),
                "price": price,
                "size": 0.0,
                "position": q,
                "avg_entry_price": ac,
                "cash": cash,
                "realized_pnl": realized,
                "unrealized_pnl": unrealized,
                "total_pnl": total,
                "mark_price": mark,
                "trade_id": r.get("trade_id", "")
            })
            continue

        # MàJ cash (formule compacte et correcte)
        cash -= dq * price

        # Réalisation via average cost (traiter la partie qui ferme d'abord)
        if dq > 0:  # net BUY
            # ferme un short existant ?
            if q < 0:
                close = min(-q, dq)
                realized += (ac - price) * close  # short pnl
                q += close
                dq -= close
                if q == 0:
                    ac = 0.0
            # éventuelle ouverture/augmentation d'un long
            if dq > 0:
                new_long = q + dq
                ac = (q * ac + dq * price) / new_long if new_long != 0 else 0.0
                q = new_long

        else:  # dq < 0, net SELL
            sell_qty = -dq
            # ferme un long existant ?
            if q > 0:
                close = min(q, sell_qty)
                realized += (price - ac) * close  # long pnl
                q -= close
                sell_qty -= close
                if q == 0:
                    ac = 0.0
            # éventuelle ouverture/augmentation d'un short
            if sell_qty > 0:
                new_short = (-q) + sell_qty  # quantités côté short (positif)
                ac = (((-q) * ac) + sell_qty * price) / new_short if new_short != 0 else 0.0
                q -= sell_qty

        # Prix de marquage
        if mark_col is not None and mark_col in r and r.get(mark_col) not in (None, ""):
            mark = parse_float(r.get(mark_col), price)
        else:
            mark = price  # fallback: dernier prix exécuté

        unrealized = (mark - ac) * q
        total = realized + unrealized  # == cash + q*mark

        out.append({
            "timestamp": r.get(tcol),
            "side": r.get("side"),
            "price": price,
            "size": abs(dq),                 # taille effectivement prise après clip
            "position": q,
            "avg_entry_price": ac,
            "cash": cash,
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "total_pnl": total,
            "mark_price": mark,
            "trade_id": r.get("trade_id", "")
        })

    return out

# ---------- plots ----------
def plot_pnl_rows(rows):
    print("\n=== PNL PLOT ===")
    if not rows:
        print("Aucune donnée PnL à tracer.")
        return
    times = [parse_time_any(r.get("timestamp")) for r in rows]
    fig = go.Figure()
    for col, label in [("total_pnl","Total P&L"), ("realized_pnl","Realized P&L"), ("unrealized_pnl","Unrealized P&L")]:
        ys = [parse_float(r.get(col)) for r in rows]
        if all(isinstance(y, float) and math.isnan(y) for y in ys):
            continue
        fig.add_trace(go.Scatter(x=times, y=ys, mode="lines", name=label))
    # Axe droit optionnel pour la position
    pos = [parse_float(r.get("position")) for r in rows]
    if any(math.isfinite(v) for v in pos):
        fig.add_trace(go.Scatter(x=times, y=pos, mode="lines", name="Position", yaxis="y2", opacity=0.3))
        fig.update_layout(
            yaxis=dict(title="P&L (USD)"),
            yaxis2=dict(title="Position (BTC)", overlaying="y", side="right", showgrid=False),
        )
    else:
        fig.update_layout(yaxis_title="P&L (USD)")
    fig.add_hline(y=0, line_dash="dot", opacity=0.5)
    fig.update_layout(title="P&L over Time (from trades)", xaxis_title="Time", legend_title="Series")
    fig.show()

def plot_spreads(rows):
    print("\n=== SPREAD PLOT ===")
    if not rows:
        print("Aucune donnée pour le spread.")
        return
    tcol = first_time_field_name(rows[0])
    times = [parse_time_any(r.get(tcol)) if tcol else i for i, r in enumerate(rows)]
    spread_cols = [c for c in rows[0].keys() if c.startswith("spread_")]
    if not spread_cols:
        print("[i] Aucune colonne 'spread_*' trouvée.")
        return
    fig = go.Figure()
    for c in sorted(spread_cols):
        ys = [parse_float(r.get(c)) for r in rows]
        fig.add_trace(go.Scatter(x=times, y=ys, mode="lines", name=c.replace("spread_", "")))
    fig.update_layout(title="Historical Spread over Time", xaxis_title="Time", yaxis_title="Spread", legend_title="Size")
    fig.show()

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description="Calcule et trace le P&L à partir des trades (et le spread si dispo).")
    ap.add_argument("--trades", default="trades.csv")
    ap.add_argument("--spreads", default="spreads.csv")
    ap.add_argument("--markcol", default=None, help="Nom de colonne à utiliser comme prix de marquage (ex: fair_price). Sinon dernier prix exécuté.")
    ap.add_argument("--max-inventory", type=float, default=None, help="Limite d'inventaire absolue pour clipper la position (optionnel).")
    args = ap.parse_args()

    trades = load_csv(args.trades)
    spreads = load_csv(args.spreads)

    summarize_trades(trades)

    # 1) Calcul PnL à partir des trades
    pnl_rows = compute_pnl_from_trades(trades, mark_col=args.markcol, max_inventory=args.max_inventory)

    # 2) Sauvegarde CSV
    if pnl_rows:
        out_path = "pnl_from_trades.csv"
        fieldnames = list(pnl_rows[0].keys())
        save_csv(out_path, pnl_rows, fieldnames)
        print(f"[✓] PnL calculé et sauvegardé dans {out_path}")
    else:
        print("[!] Impossible de calculer le PnL (liste vide).")

    # 3) Plots
    plot_pnl_rows(pnl_rows)
    plot_spreads(spreads)

    print("\nTerminé.")

if __name__ == "__main__":
    main()
