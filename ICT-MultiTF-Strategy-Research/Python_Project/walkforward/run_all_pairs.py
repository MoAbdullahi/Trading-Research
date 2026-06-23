"""
run_all_pairs.py — Backtest all 6 instruments + master comparison.

Runs the instrumented backtest on EURUSD, GBPUSD, USDJPY, XAUUSD, NAS100, US30
for a chosen period, produces:
    - Per-instrument viz dashboard (viz_output/{INSTRUMENT}/dashboard.html)
    - Master comparison HTML (viz_output/master.html) ranking all instruments

Usage:
    python run_all_pairs.py --start 2024-01-01 --end 2024-12-31
    python run_all_pairs.py --start 2022-05-12 --end 2026-05-12   # full history
"""
from __future__ import annotations
import argparse
import sys
import json
from pathlib import Path
from html import escape
import plotly.graph_objects as go
import plotly.io as pio

from viz_engine import run_instrumented_backtest, summarize_trades
from viz_dashboard import generate_dashboard, COLORS


INSTRUMENTS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "NAS100", "US30"]


# --------------------------------------------------------------------------- #
# Master comparison HTML                                                      #
# --------------------------------------------------------------------------- #
_MASTER_CSS = f"""
<style>
  * {{ box-sizing: border-box }}
  body {{ font-family: Consolas, 'Courier New', monospace;
         background: {COLORS['bg']}; color: {COLORS['text']}; margin: 0; padding: 24px }}
  h1 {{ color: {COLORS['amber']}; margin: 0 0 4px 0 }}
  h2 {{ color: {COLORS['muted']}; font-weight: 400; margin: 4px 0 24px 0; font-size: 1em }}
  h3 {{ color: {COLORS['amber']}; margin: 28px 0 10px 0; font-size: 1.05em }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.88em;
          background: {COLORS['panel']}; border-radius: 6px; overflow: hidden;
          margin-bottom: 24px }}
  th {{ background: {COLORS['panel']}; color: {COLORS['amber']}; padding: 10px 14px;
        text-align: left; border-bottom: 2px solid {COLORS['grid']}; white-space: nowrap }}
  td {{ padding: 8px 14px; border-bottom: 1px solid {COLORS['grid']}; white-space: nowrap }}
  tr:hover td {{ background: {COLORS['grid']} }}
  td.green {{ color: {COLORS['bull']}; font-weight: bold }}
  td.red {{ color: {COLORS['bear']}; font-weight: bold }}
  td.amber {{ color: {COLORS['amber']}; font-weight: bold }}
  td.blue {{ color: {COLORS['blue']}; font-weight: bold }}
  td.muted {{ color: {COLORS['muted']} }}
  a {{ color: {COLORS['blue']}; text-decoration: none }}
  a:hover {{ text-decoration: underline }}
  .rank {{ display: inline-block; width: 22px; height: 22px; line-height: 22px;
           border-radius: 50%; text-align: center; font-weight: bold; font-size: 0.85em }}
  .rank-1 {{ background: #1a4731; color: #2ecc71 }}
  .rank-2 {{ background: #2d2d0a; color: #e6b450 }}
  .rank-3 {{ background: #21262d; color: #8b949e }}
  .chart {{ background: {COLORS['panel']}; border: 1px solid {COLORS['grid']};
            border-radius: 10px; padding: 12px; margin-bottom: 20px }}
  .summary {{ background: {COLORS['panel']}; border-left: 3px solid {COLORS['amber']};
              padding: 14px 18px; margin: 16px 0; border-radius: 0 6px 6px 0; line-height: 1.6 }}
  .summary b {{ color: {COLORS['amber']} }}
  .footer {{ color: #484f58; font-size: 0.78em; margin-top: 28px }}
</style>
"""


def _rank_badge(rank: int) -> str:
    cls = f"rank-{rank}" if rank <= 3 else ""
    return f'<span class="rank {cls}">{rank}</span>'


def _make_comparison_chart(results: dict[str, dict], metric: str,
                            ylabel: str, color: str = "#58a6ff") -> str:
    """Bar chart of one metric across instruments."""
    instruments = list(results.keys())
    values = [results[i].get(metric, 0) or 0 for i in instruments]
    # Color bars: green for positive, red for negative
    bar_colors = [COLORS["bull"] if v > 0 else COLORS["bear"] for v in values]

    fig = go.Figure(go.Bar(
        x=instruments, y=values, marker=dict(color=bar_colors),
        text=[f"{v:.2f}" for v in values], textposition="outside",
    ))
    fig.update_layout(
        title=ylabel,
        paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["panel"],
        font=dict(family="Consolas, monospace", color=COLORS["text"], size=11),
        height=340, margin=dict(l=50, r=30, t=50, b=40),
        xaxis=dict(gridcolor=COLORS["grid"]),
        yaxis=dict(gridcolor=COLORS["grid"], zerolinecolor=COLORS["muted"]),
        showlegend=False,
    )
    return pio.to_html(fig, include_plotlyjs="cdn", full_html=False, default_height=340)


def _make_equity_overlay(equity_curves: dict[str, list]) -> str:
    """Overlay equity curves of all instruments on one chart."""
    fig = go.Figure()
    colors = ["#58a6ff", "#2ecc71", "#e6b450", "#e74c3c", "#a371f7", "#ff7b72"]
    for i, (inst, curve) in enumerate(equity_curves.items()):
        if not curve: continue
        x = [c["time"] for c in curve]
        y = [c["cum_r"] for c in curve]
        fig.add_trace(go.Scatter(
            x=x, y=y, mode="lines", name=inst,
            line=dict(color=colors[i % len(colors)], width=2),
        ))
    fig.update_layout(
        title="Cumulative R curves — all instruments",
        paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["panel"],
        font=dict(family="Consolas, monospace", color=COLORS["text"], size=11),
        height=420, margin=dict(l=50, r=30, t=50, b=40),
        xaxis=dict(gridcolor=COLORS["grid"]),
        yaxis=dict(gridcolor=COLORS["grid"], zerolinecolor=COLORS["muted"],
                   title="Cumulative R"),
        legend=dict(bgcolor=COLORS["panel"]),
    )
    return pio.to_html(fig, include_plotlyjs="cdn", full_html=False, default_height=420)


def _color_class(value: float, thresholds: tuple) -> str:
    """Return CSS class based on value vs thresholds (low, high)."""
    low, high = thresholds
    if value >= high: return "green"
    if value <= low:  return "red"
    return "amber"


def generate_master_comparison(results: dict[str, dict],
                                  equity_curves: dict[str, list],
                                  out_path: Path, period_str: str,
                                  account_size: float, risk_pct: float):
    """Write master comparison HTML ranking all instruments."""
    # Rank instruments by total R (the most actionable metric for "which is best")
    ranked = sorted(results.items(),
                     key=lambda x: x[1].get("total_r", -999),
                     reverse=True)

    # Build rows
    rows_html = []
    for rank, (inst, stats) in enumerate(ranked, start=1):
        if stats["n"] == 0:
            rows_html.append(f"""
            <tr>
              <td>{_rank_badge(rank)} <a href="{inst}/dashboard.html">{inst}</a></td>
              <td colspan="11" class="muted">No completed trades in this period</td>
            </tr>""")
            continue

        risk_per_trade = account_size * risk_pct / 100.0
        pnl = stats["total_r"] * risk_per_trade
        ret_pct = 100 * pnl / account_size

        wr_class = _color_class(stats["win_rate"], (45, 60))
        avgr_class = _color_class(stats["avg_r"], (0, 0.3))
        pf_val = stats["profit_factor"]
        pf_class = "green" if pf_val >= 2 else "amber" if pf_val >= 1.3 else "red"
        pnl_class = "green" if pnl >= 0 else "red"

        rows_html.append(f"""
        <tr>
          <td>{_rank_badge(rank)} <a href="{inst}/dashboard.html"><b>{inst}</b></a></td>
          <td class="blue">{stats['n']}</td>
          <td class="{wr_class}">{stats['win_rate']:.1f}%</td>
          <td class="{avgr_class}">{stats['avg_r']:+.3f}</td>
          <td class="{pnl_class}">{stats['total_r']:+.2f}R</td>
          <td class="{pnl_class}">${pnl:+,.0f}</td>
          <td class="{pnl_class}">{ret_pct:+.2f}%</td>
          <td class="{pf_class}">{pf_val:.2f}</td>
          <td class="red">{stats['max_dd_r']:.2f}R</td>
          <td class="green">{stats['best_r']:+.2f}R</td>
          <td class="red">{stats['worst_r']:+.2f}R</td>
          <td class="amber">{stats['n_partials_filled']}</td>
        </tr>""")

    # Summary judgment paragraph
    if ranked and ranked[0][1]["n"] > 0:
        top = ranked[0]
        top_inst, top_stats = top
        risk_per_trade = account_size * risk_pct / 100.0
        top_pnl = top_stats["total_r"] * risk_per_trade
        top_pf = top_stats["profit_factor"]

        # How many are profitable?
        profitable = [(i, s) for i, s in ranked if s.get("total_r", 0) > 0]
        unprofitable = [(i, s) for i, s in ranked if s.get("total_r", 0) <= 0 and s["n"] > 0]
        no_trades = [(i, s) for i, s in ranked if s["n"] == 0]

        summary_parts = [
            f"<b>{top_inst}</b> tops the leaderboard with <b>{top_stats['total_r']:+.2f}R "
            f"(${top_pnl:+,.0f}, PF {top_pf:.2f})</b> across {top_stats['n']} trades."
        ]
        if profitable:
            inst_names = ", ".join(i for i, _ in profitable)
            summary_parts.append(f"Profitable instruments ({len(profitable)}): {inst_names}.")
        if unprofitable:
            inst_names = ", ".join(i for i, _ in unprofitable)
            summary_parts.append(f"Unprofitable ({len(unprofitable)}): {inst_names}.")
        if no_trades:
            inst_names = ", ".join(i for i, _ in no_trades)
            summary_parts.append(f"No trades captured for: {inst_names}.")

        summary_html = f'<div class="summary">{" ".join(summary_parts)}</div>'
    else:
        summary_html = ""

    # Comparison charts
    chart_total_r = _make_comparison_chart(results, "total_r", "Total R captured")
    chart_avg_r = _make_comparison_chart(results, "avg_r", "Average R per trade")
    chart_n = _make_comparison_chart(results, "n", "Trade count")
    chart_dd = _make_comparison_chart(results, "max_dd_r", "Max drawdown (R)")
    equity_html = _make_equity_overlay(equity_curves)

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>SMC CRT — All Pairs Comparison</title>
{_MASTER_CSS}
</head><body>

<h1>SMC CRT Strategy — All Pairs Performance</h1>
<h2>Period: {period_str} · ${account_size:,.0f} account · {risk_pct}% risk/trade</h2>

{summary_html}

<h3>Ranked Leaderboard</h3>
<table>
<thead><tr>
  <th>Instrument</th><th>Trades</th><th>Win Rate</th><th>Avg R</th>
  <th>Total R</th><th>P&amp;L</th><th>Return</th><th>PF</th>
  <th>Max DD</th><th>Best</th><th>Worst</th><th>Partials</th>
</tr></thead>
<tbody>{"".join(rows_html)}</tbody>
</table>

<h3>Cumulative R Curves</h3>
<div class="chart">{equity_html}</div>

<h3>Total R Captured by Instrument</h3>
<div class="chart">{chart_total_r}</div>

<h3>Average R per Trade by Instrument</h3>
<div class="chart">{chart_avg_r}</div>

<h3>Trade Count by Instrument</h3>
<div class="chart">{chart_n}</div>

<h3>Maximum Drawdown (R) by Instrument</h3>
<div class="chart">{chart_dd}</div>

<div class="footer">
  Click any instrument name above to drill into its per-trade dashboard.
  Generated by run_all_pairs.py
</div>
</body></html>"""

    out_path.write_text(html, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #
def main():
    import numpy as np

    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", default="2024-01-01")
    p.add_argument("--end", default="2024-12-31")
    p.add_argument("--mode", default="h4_m15", choices=["h4_m15", "h4_m5"])
    p.add_argument("--out", default="./viz_output")
    p.add_argument("--account", type=float, default=100_000.0)
    p.add_argument("--risk", type=float, default=1.0)
    args = p.parse_args()

    htf_freq, ltf_freq = ("4h", "15min") if args.mode == "h4_m15" else ("4h", "5min")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_stats = {}
    all_curves = {}

    print(f"\nBacktesting all {len(INSTRUMENTS)} instruments")
    print(f"Period: {args.start} → {args.end}  |  Mode: {args.mode}")
    print("=" * 70)

    for inst in INSTRUMENTS:
        print(f"\n→ {inst}")
        try:
            trades = run_instrumented_backtest(inst, htf_freq, ltf_freq, "A",
                                                start=args.start, end=args.end)
        except FileNotFoundError as e:
            print(f"   ⚠ Data file missing: {e}")
            all_stats[inst] = {"n": 0}
            all_curves[inst] = []
            continue
        except Exception as e:
            print(f"   ⚠ Error: {e}")
            all_stats[inst] = {"n": 0}
            all_curves[inst] = []
            continue

        stats = summarize_trades(trades)
        all_stats[inst] = stats

        # Build equity curve points for overlay
        completed = sorted(
            [t for t in trades if t.exit_reason not in (None, "no_fill")],
            key=lambda t: t.exit_time
        )
        if completed:
            cum = 0.0
            curve = []
            for t in completed:
                cum += t.r_total
                curve.append({"time": str(t.exit_time), "cum_r": round(cum, 3)})
            all_curves[inst] = curve
        else:
            all_curves[inst] = []

        # Per-instrument dashboard
        try:
            generate_dashboard(
                trades, out_dir / inst,
                title=f"SMC CRT — {inst} {args.mode}",
                account_size=args.account, risk_per_trade_pct=args.risk,
            )
            print(f"   ✓ {stats['n']} trades · {stats.get('win_rate', 0):.1f}% WR · "
                  f"{stats.get('total_r', 0):+.2f}R")
        except Exception as e:
            print(f"   ⚠ Dashboard failed: {e}")

    # Master comparison
    print("\n" + "=" * 70)
    print("Generating master comparison page...")
    master_path = out_dir / "master.html"
    generate_master_comparison(all_stats, all_curves, master_path,
                                  period_str=f"{args.start} → {args.end}",
                                  account_size=args.account, risk_pct=args.risk)
    print(f"\n✓ Master leaderboard:  {master_path.resolve()}")

    # Save stats JSON for downstream tools
    json_path = out_dir / "all_stats.json"
    json_path.write_text(json.dumps({
        "period": f"{args.start} → {args.end}",
        "mode": args.mode,
        "account_size": args.account,
        "risk_pct": args.risk,
        "results": all_stats,
    }, indent=2, default=str))
    print(f"  Stats JSON:          {json_path.resolve()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
