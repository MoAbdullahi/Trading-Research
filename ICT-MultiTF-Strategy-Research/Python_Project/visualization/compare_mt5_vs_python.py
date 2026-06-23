"""
compare_mt5_vs_python.py — Auto-generate Python vs MT5 comparison page.

Reads:
  1. An MT5 Strategy Tester HTML report (saved via right-click → Report → Save As)
  2. Optionally: rerun the Python backtest with the same date range, OR load
     cached Python stats from a JSON file.

Outputs:
  comparison.html — a single dark-themed page with side-by-side stats and
  per-metric match/close/diverge tags.

Usage:
  # Re-run Python backtest + parse MT5 report:
  python compare_mt5_vs_python.py --mt5-report ~/Downloads/mt5_report.htm \\
                                  --symbol EURUSD --start 2024-01-01 --end 2024-06-30

  # Or use cached Python stats:
  python compare_mt5_vs_python.py --mt5-report ~/Downloads/mt5_report.htm \\
                                  --python-stats ./viz_test/stats.json

  # Output to specific file:
  python compare_mt5_vs_python.py --mt5-report ... --out ./comparison.html
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from html import escape
from pathlib import Path

# --------------------------------------------------------------------------- #
# MT5 HTML report parser                                                      #
# --------------------------------------------------------------------------- #
# MT5 reports come in two main layouts depending on Build. Both store metrics
# as label/value pairs inside <td> cells. We use forgiving regex matching.

# Map of canonical_key -> list of label patterns to look for in the report
MT5_LABELS = {
    "total_net_profit":   [r"Total Net Profit", r"Net Profit"],
    "gross_profit":       [r"Gross Profit"],
    "gross_loss":         [r"Gross Loss"],
    "profit_factor":      [r"Profit Factor"],
    "expected_payoff":    [r"Expected Payoff"],
    "max_dd_money":       [r"Balance Drawdown Maximal",
                          r"Maximal Drawdown",
                          r"Drawdown maximal"],
    "max_dd_pct":         [r"Balance Drawdown Maximal.*?\(([\d.]+)%\)",
                          r"Maximal Drawdown.*?\(([\d.]+)%\)"],
    "total_trades":       [r"Total Trades", r"Trades:"],
    "profit_trades":      [r"Profit Trades", r"Wins"],
    "loss_trades":        [r"Loss Trades", r"Losses"],
    "win_rate_pct":       [r"Profit Trades.*?\(([\d.]+)%\)"],
    "best_trade":         [r"Largest profit trade",
                          r"Maximum consecutive wins.*?\$\s*([\-\d.,]+)",
                          r"Best Trade"],
    "worst_trade":        [r"Largest loss trade",
                          r"Maximum consecutive losses.*?\$\s*([\-\d.,]+)",
                          r"Worst Trade"],
    "avg_win":            [r"Average profit trade"],
    "avg_loss":           [r"Average loss trade"],
    "max_loss_streak":    [r"Maximum consecutive losses\s*\(count\)",
                          r"Maximum consecutive losses\s*\$"],
    "sharpe_ratio":       [r"Sharpe Ratio"],
}


def _to_number(s: str) -> float | None:
    """Parse a string like '$1,234.56' or '(2.79%)' to float."""
    if s is None: return None
    s = s.strip().replace(",", "").replace("$", "").replace("%", "")
    s = s.replace("(", "-").replace(")", "")
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def parse_mt5_report(filepath: str | Path) -> dict:
    """Parse an MT5 HTML strategy tester report. Returns dict of metrics.

    The MT5 HTML format places labels and values in adjacent <td> cells,
    sometimes with values in HTML attributes or split across rows. We extract
    the table cells and scan label-value pairs.
    """
    html = Path(filepath).read_text(encoding="utf-8", errors="ignore")

    # 1) Extract all visible text from <td> cells with their position
    td_pattern = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
    cells_raw = td_pattern.findall(html)
    # Strip nested HTML tags from each cell
    cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells_raw]
    cells = [re.sub(r"\s+", " ", c) for c in cells]

    # 2) Build a (label -> next_value) lookup by scanning adjacent pairs
    pair_lookup: dict[str, str] = {}
    for i, c in enumerate(cells[:-1]):
        if c.endswith(":"):
            label = c[:-1].strip()
            pair_lookup.setdefault(label, cells[i + 1])

    # Also build a wider context lookup for multi-cell metrics
    joined = " | ".join(cells)

    result: dict[str, float | None] = {}

    def search_in_pairs(patterns: list[str]) -> str | None:
        """Find a label match in pair_lookup."""
        for label, value in pair_lookup.items():
            for pat in patterns:
                # Use the first capture group if present, else the value itself
                m = re.search(pat, label, re.IGNORECASE)
                if m:
                    return value
        return None

    def search_in_joined(patterns: list[str]) -> str | None:
        """Find a metric pattern across the joined text (handles inline parens)."""
        for pat in patterns:
            m = re.search(pat, joined, re.IGNORECASE)
            if m:
                if m.groups():
                    return m.group(1)
                # No groups — return the surrounding number after the match
                tail = joined[m.end():m.end() + 80]
                num_m = re.search(r"[\-\d.,$%()]+", tail)
                if num_m:
                    return num_m.group(0)
        return None

    for key, patterns in MT5_LABELS.items():
        raw = search_in_pairs(patterns) or search_in_joined(patterns)
        result[key] = _to_number(raw)

    # Derive win rate if not parsed but trades + wins available
    if result.get("win_rate_pct") is None:
        tt = result.get("total_trades")
        pt = result.get("profit_trades")
        if tt and pt:
            result["win_rate_pct"] = round(100.0 * pt / tt, 2)

    return result


# --------------------------------------------------------------------------- #
# Python stats: load from JSON or recompute                                   #
# --------------------------------------------------------------------------- #
def get_python_stats(symbol: str, start: str, end: str,
                       cached_path: str | None = None,
                       account_size: float = 100_000.0,
                       risk_pct: float = 1.0) -> dict:
    """Either load cached Python stats from JSON or recompute by running viz_engine."""
    if cached_path and Path(cached_path).exists():
        return json.loads(Path(cached_path).read_text())

    # Recompute (requires viz_engine + phase2_engine + data parquets present)
    from viz_engine import run_instrumented_backtest, summarize_trades
    trades = run_instrumented_backtest(
        symbol, "4h", "15min", "A", start=start, end=end,
    )
    stats = summarize_trades(trades)
    completed = [t for t in trades if t.exit_reason not in (None, "no_fill")]

    risk_per_trade = account_size * risk_pct / 100.0
    return {
        "n": stats.get("n", 0),
        "wins": stats.get("wins", 0),
        "losses": stats.get("losses", 0),
        "win_rate": stats.get("win_rate", 0),
        "avg_r": stats.get("avg_r", 0),
        "total_r": stats.get("total_r", 0),
        "profit_factor": stats.get("profit_factor", 0),
        "max_dd_r": stats.get("max_dd_r", 0),
        "best_r": stats.get("best_r", 0),
        "worst_r": stats.get("worst_r", 0),
        "max_loss_streak": stats.get("max_loss_streak", 0),
        "n_partials": stats.get("n_partials_filled", 0),
        "total_pnl": round(stats.get("total_r", 0) * risk_per_trade, 2),
        "return_pct": round(100 * stats.get("total_r", 0) * risk_per_trade / account_size, 3),
        "symbol": symbol,
        "start": start,
        "end": end,
        "trades_detail": [
            {
                "n": i + 1,
                "trigger_time": str(t.trigger_time),
                "is_bear": t.is_bear,
                "entry_type": t.entry_type,
                "entry_price": t.entry_price,
                "exit_time": str(t.exit_time) if t.exit_time else None,
                "exit_reason": t.exit_reason,
                "n_partials": t.n_partials,
                "r_total": round(t.r_total, 3),
            }
            for i, t in enumerate(completed)
        ],
    }


# --------------------------------------------------------------------------- #
# Comparison HTML generation                                                  #
# --------------------------------------------------------------------------- #
COLORS = {
    "bg": "#0d1117", "panel": "#161b22", "grid": "#21262d", "text": "#c9d1d9",
    "muted": "#8b949e", "bull": "#2ecc71", "bear": "#e74c3c", "amber": "#e6b450",
    "blue": "#58a6ff",
}


def _delta(mt5_val: float | None, py_val: float, allowed_pct: float = 10.0) -> tuple:
    """Compute (delta_value, match_tag) where match_tag is 'match' / 'close' / 'diff'."""
    if mt5_val is None or py_val is None:
        return None, "pending"
    delta = mt5_val - py_val
    if py_val == 0:
        pct = 0 if delta == 0 else 999
    else:
        pct = abs(delta / py_val) * 100
    if pct <= 5:
        tag = "match"
    elif pct <= allowed_pct:
        tag = "close"
    else:
        tag = "diff"
    return delta, tag


def _fmt_delta(delta: float | None, fmt: str) -> str:
    if delta is None: return "—"
    return fmt.format(delta)


def _row(metric: str, py_val, mt5_val, delta_val, tag: str,
          py_fmt: str = "{:+.2f}", mt5_fmt: str | None = None,
          delta_fmt: str = "{:+.2f}") -> str:
    mt5_fmt = mt5_fmt or py_fmt
    py_str = py_fmt.format(py_val) if py_val is not None else "—"
    mt5_str = (mt5_fmt.format(mt5_val) if mt5_val is not None
               else '<span class="na">awaiting MT5 run</span>')
    delta_str = _fmt_delta(delta_val, delta_fmt)
    py_class = ("pos" if isinstance(py_val, (int, float)) and py_val > 0
                 else "neg" if isinstance(py_val, (int, float)) and py_val < 0
                 else "")
    mt5_class = ("pos" if isinstance(mt5_val, (int, float)) and mt5_val > 0
                  else "neg" if isinstance(mt5_val, (int, float)) and mt5_val < 0
                  else "")
    return f"""
    <tr>
      <td>{escape(metric)}</td>
      <td class="{py_class}">{py_str}</td>
      <td class="{mt5_class}">{mt5_str}</td>
      <td>{delta_str}</td>
      <td><span class="tag tag-{tag}">{tag}</span></td>
    </tr>"""


def _trade_row(t: dict) -> str:
    direction = "BEAR" if t["is_bear"] else "BULL"
    dir_class = "neg" if t["is_bear"] else "pos"
    r_class = "pos" if t["r_total"] > 0 else "neg" if t["r_total"] < 0 else "muted"
    entry_str = f"{t['entry_price']:.5f}" if t.get("entry_price") else "—"
    return f"""
    <tr>
      <td>#{t['n']:03d}</td>
      <td>{t['trigger_time'][:16]}</td>
      <td class="{dir_class}" style="font-weight:bold">{direction}</td>
      <td>{escape(t.get('entry_type') or 'n/a')}</td>
      <td>{entry_str}</td>
      <td>{(t.get('exit_time') or '—')[:16]}</td>
      <td>{escape(t.get('exit_reason') or 'n/a')}</td>
      <td>{t.get('n_partials', 0)}</td>
      <td class="{r_class}">{t['r_total']:+.2f}R</td>
    </tr>"""


def generate_comparison_html(py_stats: dict, mt5_stats: dict,
                               account_size: float = 100_000.0,
                               risk_pct: float = 1.0) -> str:
    """Generate the side-by-side comparison HTML."""
    has_mt5 = any(v is not None for v in mt5_stats.values()) if mt5_stats else False

    # Compute deltas (only when MT5 data is present)
    py_pnl = py_stats.get("total_pnl", 0)
    py_ret = py_stats.get("return_pct", 0)
    py_n   = py_stats.get("n", 0)
    py_wr  = py_stats.get("win_rate", 0)
    py_pf  = py_stats.get("profit_factor", 0)
    py_avgr= py_stats.get("avg_r", 0)
    py_dd  = py_stats.get("max_dd_r", 0)
    py_best= py_stats.get("best_r", 0)
    py_worst=py_stats.get("worst_r", 0)
    py_streak=py_stats.get("max_loss_streak", 0)

    mt5_pnl = mt5_stats.get("total_net_profit") if has_mt5 else None
    mt5_n   = mt5_stats.get("total_trades") if has_mt5 else None
    mt5_wr  = mt5_stats.get("win_rate_pct") if has_mt5 else None
    mt5_pf  = mt5_stats.get("profit_factor") if has_mt5 else None
    mt5_dd_money = mt5_stats.get("max_dd_money") if has_mt5 else None
    mt5_dd_pct = mt5_stats.get("max_dd_pct") if has_mt5 else None
    mt5_best = mt5_stats.get("best_trade") if has_mt5 else None
    mt5_worst = mt5_stats.get("worst_trade") if has_mt5 else None
    mt5_streak = mt5_stats.get("max_loss_streak") if has_mt5 else None

    # Derived: convert MT5 dollar metrics to R-equivalent (assuming 1% risk = $1000)
    risk_per_trade = account_size * risk_pct / 100.0
    mt5_dd_r = mt5_dd_money / risk_per_trade if mt5_dd_money else None
    mt5_best_r = mt5_best / risk_per_trade if mt5_best else None
    mt5_worst_r = mt5_worst / risk_per_trade if mt5_worst else None
    mt5_ret = 100 * mt5_pnl / account_size if mt5_pnl is not None else None
    mt5_avgr = (mt5_stats.get("expected_payoff") / risk_per_trade
                if mt5_stats.get("expected_payoff") else None)

    # Rows
    rows = []
    d, tag = _delta(mt5_pnl, py_pnl)
    rows.append(_row("Net P&L ($)", py_pnl, mt5_pnl, d, tag, "${:+,.2f}"))
    d, tag = _delta(mt5_ret, py_ret)
    rows.append(_row("Return (%)", py_ret, mt5_ret, d, tag, "{:+.2f}%"))
    d, tag = _delta(mt5_n, py_n)
    mt5_n_int = int(mt5_n) if mt5_n is not None else None
    rows.append(_row("Trades (#)", py_n, mt5_n_int, d, tag, "{:d}", delta_fmt="{:+.0f}"))
    d, tag = _delta(mt5_wr, py_wr)
    rows.append(_row("Win Rate (%)", py_wr, mt5_wr, d, tag, "{:.1f}%"))
    d, tag = _delta(mt5_pf, py_pf)
    rows.append(_row("Profit Factor", py_pf, mt5_pf, d, tag, "{:.2f}"))
    d, tag = _delta(mt5_avgr, py_avgr)
    rows.append(_row("Avg R / trade", py_avgr, mt5_avgr, d, tag, "{:+.3f}"))
    d, tag = _delta(mt5_dd_r, py_dd)
    rows.append(_row("Max DD (R)", py_dd, mt5_dd_r, d, tag, "{:.2f}R"))
    d, tag = _delta(mt5_best_r, py_best)
    rows.append(_row("Best Trade (R)", py_best, mt5_best_r, d, tag, "{:+.2f}R"))
    d, tag = _delta(mt5_worst_r, py_worst)
    rows.append(_row("Worst Trade (R)", py_worst, mt5_worst_r, d, tag, "{:+.2f}R"))
    d, tag = _delta(mt5_streak, py_streak)
    mt5_streak_int = int(mt5_streak) if mt5_streak is not None else None
    rows.append(_row("Max Loss Streak", py_streak, mt5_streak_int, d, tag, "{:d}", delta_fmt="{:+.0f}"))

    rows_html = "".join(rows)

    # Per-trade table from Python
    trade_rows_html = "".join(_trade_row(t) for t in py_stats.get("trades_detail", []))
    if not trade_rows_html:
        trade_rows_html = "<tr><td colspan='9'>No completed trades.</td></tr>"

    status_banner = ("<b>Status:</b> Both Python and MT5 data loaded — see deltas below."
                     if has_mt5
                     else "<b>Status:</b> Python data loaded. MT5 column awaiting Strategy Tester run.")

    # CSS
    css = """
    * { box-sizing: border-box }
    body { font-family: Consolas, 'Courier New', monospace;
           background: %(bg)s; color: %(text)s; margin: 0; padding: 24px }
    h1  { color: %(amber)s; margin: 0 0 4px 0 }
    h2  { color: %(muted)s; font-weight: 400; margin: 4px 0 24px 0; font-size: 1em }
    h3  { color: %(amber)s; margin: 28px 0 10px 0; font-size: 1.05em }
    .status-banner { background: #1c1c0a; border: 1px solid %(amber)s; border-radius: 8px;
                     padding: 14px 20px; margin-bottom: 24px; font-size: 0.9em }
    .status-banner b { color: %(amber)s }
    table { border-collapse: collapse; width: 100%%; font-size: 0.85em;
            background: %(panel)s; border-radius: 6px; overflow: hidden; margin-bottom: 24px }
    th  { background: %(panel)s; color: %(amber)s; padding: 9px 14px;
          text-align: left; border-bottom: 2px solid %(grid)s; white-space: nowrap }
    td  { padding: 8px 14px; border-bottom: 1px solid %(grid)s }
    tr:hover td { background: %(grid)s }
    .pos { color: %(bull)s; font-weight: bold } .neg { color: %(bear)s; font-weight: bold }
    .muted { color: %(muted)s } .na { color: #484f58; font-style: italic }
    .tag { display: inline-block; padding: 2px 8px; border-radius: 4px;
           font-size: 0.82em; font-weight: bold }
    .tag-match { background: #1a4731; color: %(bull)s }
    .tag-close { background: #2d2d0a; color: %(amber)s }
    .tag-diff  { background: #3d1010; color: %(bear)s }
    .tag-pending { background: %(grid)s; color: %(muted)s }
    .cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 24px }
    .card { background: %(panel)s; border: 1px solid %(grid)s;
            border-radius: 10px; padding: 14px 20px; min-width: 145px }
    .card .lbl { font-size: 0.78em; color: %(muted)s;
                 text-transform: uppercase; letter-spacing: 0.05em }
    .card .val { font-size: 1.45em; font-weight: 700; margin-top: 6px }
    .green { color: %(bull)s } .red { color: %(bear)s }
    .amber { color: %(amber)s } .blue { color: %(blue)s }
    .footer { color: #484f58; font-size: 0.78em; margin-top: 28px }
    """ % COLORS

    # Summary cards (Python side)
    pnl_color = "green" if py_pnl >= 0 else "red"
    wr_color = "green" if py_wr >= 55 else "amber" if py_wr >= 45 else "red"

    cards_html = f"""
    <div class="card"><div class="lbl">Net P&amp;L</div>
      <div class="val {pnl_color}">${py_pnl:+,.0f}</div></div>
    <div class="card"><div class="lbl">Return</div>
      <div class="val {pnl_color}">{py_ret:+.2f}%</div></div>
    <div class="card"><div class="lbl">Total R</div>
      <div class="val {pnl_color}">{py_stats.get('total_r', 0):+.2f}R</div></div>
    <div class="card"><div class="lbl">Trades</div>
      <div class="val blue">{py_n}</div></div>
    <div class="card"><div class="lbl">Win Rate</div>
      <div class="val {wr_color}">{py_wr:.1f}%</div></div>
    <div class="card"><div class="lbl">Profit Factor</div>
      <div class="val amber">{py_pf:.2f}</div></div>
    <div class="card"><div class="lbl">Avg R/trade</div>
      <div class="val {pnl_color}">{py_avgr:+.3f}</div></div>
    <div class="card"><div class="lbl">Max DD</div>
      <div class="val red">{py_dd:.2f}R</div></div>
    <div class="card"><div class="lbl">Partials Fired</div>
      <div class="val blue">{py_stats.get('n_partials', 0)}</div></div>
    """

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>SMC CRT — Python vs MT5 Comparison</title>
<style>{css}</style>
</head><body>

<h1>SMC CRT EA v1.2 — Python Backtest vs MT5 Strategy Tester</h1>
<h2>{escape(py_stats.get('symbol', '?'))} · H4/M15 · ${account_size:,.0f} account · {risk_pct}% risk/trade ·
    {escape(py_stats.get('start','?'))} → {escape(py_stats.get('end','?'))}</h2>

<div class="status-banner">{status_banner}</div>

<h3>Python Backtest Results</h3>
<div class="cards">{cards_html}</div>

<h3>Side-by-Side Comparison</h3>
<table>
<thead><tr>
  <th>Metric</th>
  <th>Python Backtest</th>
  <th>MT5 Strategy Tester</th>
  <th>Delta (MT5 − Python)</th>
  <th>Match?</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>

<h3>Python Backtest — Per-Trade Results</h3>
<table>
<thead><tr>
  <th>#</th><th>Trigger</th><th>Dir</th><th>Entry Type</th>
  <th>Entry Price</th><th>Exit</th><th>Exit Reason</th>
  <th>Partials</th><th>R</th>
</tr></thead>
<tbody>{trade_rows_html}</tbody>
</table>

<div class="footer">
  Python source: viz_engine / phase2_engine &nbsp;|&nbsp;
  MT5 source: SMC_CRT_EA_v1.2 on FTMO Global Markets MT5 &nbsp;|&nbsp;
  Generated by compare_mt5_vs_python.py
</div>

</body></html>"""


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mt5-report", default=None,
                    help="Path to MT5 HTML report. If omitted, MT5 column shows 'pending'.")
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--start", default="2024-01-01")
    p.add_argument("--end", default="2024-06-30")
    p.add_argument("--python-stats", default=None,
                    help="Optional cached Python stats JSON (else rerun viz_engine)")
    p.add_argument("--out", default="comparison.html",
                    help="Output HTML path (default: comparison.html)")
    p.add_argument("--account", type=float, default=100_000.0)
    p.add_argument("--risk", type=float, default=1.0)
    args = p.parse_args()

    # 1) Python stats
    print(f"Loading Python stats for {args.symbol} {args.start} → {args.end}...")
    py_stats = get_python_stats(args.symbol, args.start, args.end,
                                  args.python_stats, args.account, args.risk)
    print(f"  Trades: {py_stats['n']}, Win rate: {py_stats['win_rate']}%, "
          f"Total R: {py_stats['total_r']:+.2f}")

    # 2) MT5 stats (if provided)
    mt5_stats = {}
    if args.mt5_report:
        rpt_path = Path(args.mt5_report)
        if not rpt_path.exists():
            print(f"WARNING: MT5 report not found at {rpt_path}")
        else:
            print(f"Parsing MT5 report: {rpt_path}")
            mt5_stats = parse_mt5_report(rpt_path)
            for k, v in mt5_stats.items():
                if v is not None:
                    print(f"  {k}: {v}")
            unparsed = [k for k, v in mt5_stats.items() if v is None]
            if unparsed:
                print(f"  Could not parse: {unparsed}")
                print(f"  (Different MT5 build may use different labels — see MT5_LABELS in this file)")
    else:
        print("No --mt5-report passed; MT5 column will show 'pending'.")

    # 3) Build comparison HTML
    html = generate_comparison_html(py_stats, mt5_stats, args.account, args.risk)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"\n✓ Comparison page written to {Path(args.out).resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
