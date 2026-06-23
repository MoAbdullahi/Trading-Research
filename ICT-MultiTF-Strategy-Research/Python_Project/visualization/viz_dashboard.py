"""
viz_dashboard.py — HTML dashboard generation.

Builds a complete output directory containing:
    - dashboard.html   — summary statistics, equity curve, trade list
    - trade_NNN.html   — one detailed chart page per trade (linked from dashboard)

Style is MT5-Strategy-Tester-like: dark theme, statistics cards at top,
equity curve next, then a clickable trade table.
"""
from __future__ import annotations
from pathlib import Path
from html import escape
import plotly.io as pio
from viz_engine import TradeRecord, summarize_trades
from viz_charts import (make_trade_chart, make_equity_curve,
                          make_r_histogram, COLORS)


# --------------------------------------------------------------------------- #
# Dashboard CSS — embedded, no external deps                                  #
# --------------------------------------------------------------------------- #
_DASH_CSS = f"""
<style>
  * {{ box-sizing: border-box }}
  body {{
    font-family: Consolas, 'Courier New', monospace;
    background: {COLORS['bg']}; color: {COLORS['text']};
    margin: 0; padding: 24px;
  }}
  h1 {{ color: {COLORS['amber']}; margin: 0 0 4px 0 }}
  h2 {{ color: {COLORS['muted']}; font-weight: 400; margin: 4px 0 24px 0; font-size: 1em }}
  h3 {{ color: {COLORS['amber']}; margin: 32px 0 12px 0; font-size: 1.1em }}
  .cards {{ display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 24px }}
  .card {{
    background: {COLORS['panel']}; border: 1px solid {COLORS['grid']};
    border-radius: 10px; padding: 14px 20px; min-width: 145px;
  }}
  .card .lbl {{ font-size: 0.78em; color: {COLORS['muted']};
                text-transform: uppercase; letter-spacing: 0.05em }}
  .card .val {{ font-size: 1.45em; font-weight: 700; margin-top: 6px }}
  .green {{ color: {COLORS['bull']} }}
  .red   {{ color: {COLORS['bear']} }}
  .amber {{ color: {COLORS['amber']} }}
  .blue  {{ color: {COLORS['blue']} }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.82em;
           background: {COLORS['panel']}; border-radius: 6px; overflow: hidden }}
  th {{ background: {COLORS['panel']}; color: {COLORS['amber']};
        padding: 9px 12px; text-align: left; border-bottom: 2px solid {COLORS['grid']};
        white-space: nowrap; cursor: pointer; user-select: none }}
  th:hover {{ background: {COLORS['grid']} }}
  td {{ padding: 7px 12px; border-bottom: 1px solid {COLORS['grid']}; white-space: nowrap }}
  tr {{ transition: background 0.1s }}
  tr:hover td {{ background: {COLORS['grid']} }}
  td.r-pos {{ color: {COLORS['bull']}; font-weight: bold }}
  td.r-neg {{ color: {COLORS['bear']}; font-weight: bold }}
  td.r-zero {{ color: {COLORS['muted']} }}
  td.dir-bear {{ color: {COLORS['bear']}; font-weight: bold }}
  td.dir-bull {{ color: {COLORS['bull']}; font-weight: bold }}
  a {{ color: {COLORS['blue']}; text-decoration: none }}
  a:hover {{ text-decoration: underline }}
  .footer {{ color: #484f58; font-size: 0.78em; margin-top: 32px }}
  .chart {{ background: {COLORS['panel']}; border: 1px solid {COLORS['grid']};
            border-radius: 10px; padding: 12px; margin-bottom: 20px }}
  .back {{ display: inline-block; margin-bottom: 16px; padding: 6px 14px;
            background: {COLORS['panel']}; border: 1px solid {COLORS['grid']};
            border-radius: 6px }}
</style>
"""


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _fmt_pct(v: float) -> str: return f"{v:+.2f}%"
def _fmt_r(v: float) -> str:   return f"{v:+.2f}R"
def _fmt_money(v: float) -> str: return f"${v:,.2f}"


def _stat_card(label: str, value: str, color_class: str = "amber") -> str:
    return f"""
    <div class="card">
      <div class="lbl">{escape(label)}</div>
      <div class="val {color_class}">{value}</div>
    </div>"""


def _stats_section(stats: dict, account_size: float, risk_pct: float) -> str:
    if stats["n"] == 0:
        return "<p>No completed trades.</p>"

    total_r = stats["total_r"]
    risk_per_trade = account_size * risk_pct / 100.0
    total_pnl = total_r * risk_per_trade
    return_pct = 100 * total_pnl / account_size
    pnl_color = "green" if total_pnl >= 0 else "red"
    r_color = "green" if total_r >= 0 else "red"
    pf_color = ("green" if stats["profit_factor"] >= 2 else
                "amber" if stats["profit_factor"] >= 1 else "red")
    wr_color = ("green" if stats["win_rate"] >= 55 else
                "amber" if stats["win_rate"] >= 45 else "red")

    cards = [
        _stat_card("Net P&L", _fmt_money(total_pnl), pnl_color),
        _stat_card("Return", _fmt_pct(return_pct), pnl_color),
        _stat_card("Total R", _fmt_r(total_r), r_color),
        _stat_card("Trades", str(stats["n"]), "blue"),
        _stat_card("Win Rate", f"{stats['win_rate']:.1f}%", wr_color),
        _stat_card("Profit Factor", f"{stats['profit_factor']:.2f}", pf_color),
        _stat_card("Avg R/trade", f"{stats['avg_r']:+.3f}", r_color),
        _stat_card("Max DD", f"{stats['max_dd_r']:.2f}R", "red"),
        _stat_card("Best Trade", _fmt_r(stats["best_r"]), "green"),
        _stat_card("Worst Trade", _fmt_r(stats["worst_r"]), "red"),
        _stat_card("Max Loss Streak", str(stats["max_loss_streak"]), "amber"),
        _stat_card("Partials Fired", str(stats["n_partials_filled"]), "blue"),
    ]
    return '<div class="cards">' + "".join(cards) + "</div>"


def _trade_row(rec: TradeRecord, idx: int, link_prefix: str = "trade_") -> str:
    direction = "BEAR" if rec.is_bear else "BULL"
    dir_class = "dir-bear" if rec.is_bear else "dir-bull"
    r_class = ("r-pos" if rec.r_total > 0 else
                "r-neg" if rec.r_total < 0 else "r-zero")
    entry_str = (f"{rec.entry_price:.5f}" if rec.entry_price is not None
                 else "n/a")
    trigger_str = rec.trigger_time.strftime("%Y-%m-%d %H:%M")
    exit_str = (rec.exit_time.strftime("%Y-%m-%d %H:%M") if rec.exit_time
                else "n/a")
    return f"""
    <tr>
      <td><a href="{link_prefix}{idx:03d}.html">#{idx:03d}</a></td>
      <td>{trigger_str}</td>
      <td class="{dir_class}">{direction}</td>
      <td>{escape(rec.entry_type or "n/a")}</td>
      <td>{entry_str}</td>
      <td>{exit_str}</td>
      <td>{escape(rec.exit_reason or "n/a")}</td>
      <td>{rec.n_partials}</td>
      <td class="{r_class}">{rec.r_total:+.2f}R</td>
    </tr>"""


def _fig_to_html(fig, div_id: str) -> str:
    """Convert a Plotly figure to embedded HTML div."""
    return pio.to_html(fig, include_plotlyjs="cdn", full_html=False,
                        div_id=div_id, default_height=fig.layout.height or 500)


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #
def generate_dashboard(
    trades: list[TradeRecord],
    out_dir: str | Path,
    title: str = "SMC CRT Strategy — Backtest Results",
    account_size: float = 100_000.0,
    risk_per_trade_pct: float = 1.0,
) -> Path:
    """Generate full HTML dashboard + per-trade pages in `out_dir`.

    Returns path to the dashboard.html entry point.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    stats = summarize_trades(trades)

    # Filter to completed trades for sorting
    completed = [(i, t) for i, t in enumerate(trades, start=1)
                  if t.exit_reason not in (None, "no_fill")]

    # --- Per-trade pages ---
    for idx, rec in completed:
        try:
            fig = make_trade_chart(rec)
        except Exception as e:
            print(f"  Skipping trade {idx} chart: {e}")
            continue
        trade_html = _build_trade_page(rec, idx, fig)
        (out / f"trade_{idx:03d}.html").write_text(trade_html, encoding="utf-8")

    # --- Dashboard ---
    equity_fig = make_equity_curve(trades)
    hist_fig = make_r_histogram(trades)

    rows_html = "".join(_trade_row(t, i) for i, t in completed)
    if not rows_html:
        rows_html = "<tr><td colspan='9' style='text-align:center;color:#888;padding:20px'>No completed trades</td></tr>"

    instruments = sorted(set(t.instrument for t in trades))
    period_str = ""
    if completed:
        first = min(t.trigger_time for _, t in completed)
        last = max(t.exit_time for _, t in completed if t.exit_time is not None)
        period_str = f"{first:%Y-%m-%d} → {last:%Y-%m-%d}"

    dashboard_html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>{escape(title)}</title>
{_DASH_CSS}
</head><body>
<h1>{escape(title)}</h1>
<h2>{', '.join(instruments)} · {period_str} · ${account_size:,.0f} account ·
    {risk_per_trade_pct}% risk/trade</h2>

{_stats_section(stats, account_size, risk_per_trade_pct)}

<h3>Equity curve</h3>
<div class="chart">{_fig_to_html(equity_fig, 'equity')}</div>

<h3>R outcome distribution</h3>
<div class="chart">{_fig_to_html(hist_fig, 'hist')}</div>

<h3>Trades (click # to view detailed chart)</h3>
<table id="trades">
<thead><tr>
  <th>#</th><th>Trigger Time</th><th>Dir</th><th>Entry Type</th>
  <th>Entry Price</th><th>Exit Time</th><th>Exit Reason</th>
  <th>Partials</th><th>R</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>

<div class="footer">
  Generated by SMC CRT visualization framework · {len(completed)} trades displayed
</div>
</body></html>"""

    dashboard_path = out / "dashboard.html"
    dashboard_path.write_text(dashboard_html, encoding="utf-8")
    return dashboard_path


def _build_trade_page(rec: TradeRecord, idx: int, fig) -> str:
    """Build the HTML for a single per-trade page."""
    direction = "BEAR" if rec.is_bear else "BULL"
    r_class = ("green" if rec.r_total > 0 else
                "red" if rec.r_total < 0 else "amber")

    # Event timeline as a small table
    event_rows = []
    for ev in rec.events:
        time_str = ev.time.strftime("%Y-%m-%d %H:%M") if ev.time is not None else "—"
        price_str = f"{ev.price:.5f}" if ev.price is not None else "—"
        event_rows.append(f"""
            <tr><td>{time_str}</td><td>{escape(ev.kind)}</td>
                <td>{price_str}</td><td>{escape(ev.detail)}</td></tr>""")
    events_html = "".join(event_rows) or "<tr><td colspan='4'>no events</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Trade {idx:03d} — {rec.instrument}</title>
{_DASH_CSS}
</head><body>

<a href="dashboard.html" class="back">← Back to dashboard</a>

<h1>Trade #{idx:03d} — {rec.instrument} {direction}</h1>
<h2>Trigger: {rec.trigger_time:%Y-%m-%d %H:%M} ·
    R outcome: <span class="{r_class}">{rec.r_total:+.2f}R</span> ·
    exit: {escape(rec.exit_reason or 'n/a')}</h2>

<div class="chart">{_fig_to_html(fig, f'chart{idx}')}</div>

<h3>Event timeline</h3>
<table>
<thead><tr><th>Time</th><th>Event</th><th>Price</th><th>Detail</th></tr></thead>
<tbody>{events_html}</tbody>
</table>

<div class="footer">
  Trade {idx:03d} · entry type {rec.entry_type} · partials fired {rec.n_partials}
</div>
</body></html>"""
