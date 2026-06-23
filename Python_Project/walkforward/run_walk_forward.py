"""
run_walk_forward.py — 80/20 walk-forward test across all instruments × both modes.

Splits 4 years of data into:
    IS (in-sample, 80%):  2022-05-12 → 2025-07-23  (~3.2 years)
    OOS (out-of-sample, 20%): 2025-07-24 → 2026-05-12 (~0.8 years)

Runs every (instrument, mode) combo, then compares IS vs OOS metrics to
answer: does the edge survive on unseen data?

Stability tags per metric:
    🟢 stable     — OOS within 20% of IS (or both very similar)
    🟡 acceptable — OOS within 20–50% of IS
    🔴 unstable   — OOS >50% degradation or sign flip

Usage:
    python run_walk_forward.py
    python run_walk_forward.py --split 2025-01-01     # custom split
    python run_walk_forward.py --out ./walk_output     # custom output dir
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from html import escape
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

from viz_engine import run_instrumented_backtest, summarize_trades, TradeRecord
from viz_dashboard import COLORS


INSTRUMENTS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "NAS100", "US30"]
MODES = [
    ("h4_m15", "4h", "15min"),
    ("h4_m5",  "4h", "5min"),
]

# Data range and 80/20 split
DATA_START_DEFAULT = "2022-05-12"
DATA_END_DEFAULT   = "2026-05-12"
SPLIT_DATE_DEFAULT = "2025-07-24"


# --------------------------------------------------------------------------- #
# Stability classification                                                    #
# --------------------------------------------------------------------------- #
def stability_tag(is_val: float, oos_val: float, metric_type: str = "higher_better") -> str:
    """
    Classify stability of OOS vs IS:
      'stable'     — OOS within 20% of IS
      'acceptable' — OOS 20-50% degradation
      'unstable'   — OOS >50% degradation or sign flip
      'n/a'        — insufficient data
    """
    if is_val is None or oos_val is None:
        return "n/a"
    # Sign flip = bad
    if (is_val > 0 and oos_val < 0) or (is_val < 0 and oos_val > 0):
        return "unstable"
    if is_val == 0:
        return "stable" if abs(oos_val) < 0.1 else "n/a"

    if metric_type == "higher_better":
        # Degradation = (is - oos) / is
        if is_val > 0:
            deg = (is_val - oos_val) / abs(is_val)
        else:
            deg = (oos_val - is_val) / abs(is_val)  # less negative is better
    else:  # lower_better (e.g., drawdown)
        # Degradation = (oos - is) / is when oos > is is bad
        deg = (oos_val - is_val) / abs(is_val) if is_val != 0 else 0

    if deg <= 0.20: return "stable"
    if deg <= 0.50: return "acceptable"
    return "unstable"


# --------------------------------------------------------------------------- #
# Backtest runner                                                             #
# --------------------------------------------------------------------------- #
def run_one_combo(instrument: str, htf: str, ltf: str,
                   data_start: str, data_end: str,
                   split_date: str) -> dict:
    """Run a single (instrument, mode) combo and split into IS/OOS stats."""
    trades = run_instrumented_backtest(
        instrument, htf, ltf, "A",
        start=data_start, end=data_end,
    )
    # Split by trigger_time (preserves whole trades on either side)
    split_ts = pd.Timestamp(split_date, tz="UTC")
    is_trades = [t for t in trades if t.trigger_time < split_ts]
    oos_trades = [t for t in trades if t.trigger_time >= split_ts]

    return {
        "full_stats": summarize_trades(trades),
        "is_stats":   summarize_trades(is_trades),
        "oos_stats":  summarize_trades(oos_trades),
        "n_total":    len(trades),
        "n_is":       len(is_trades),
        "n_oos":      len(oos_trades),
    }


# --------------------------------------------------------------------------- #
# HTML generation                                                             #
# --------------------------------------------------------------------------- #
_CSS = f"""
<style>
  * {{ box-sizing: border-box }}
  body {{ font-family: Consolas, 'Courier New', monospace;
          background: {COLORS['bg']}; color: {COLORS['text']}; margin: 0; padding: 24px }}
  h1 {{ color: {COLORS['amber']}; margin: 0 0 4px 0 }}
  h2 {{ color: {COLORS['muted']}; font-weight: 400; margin: 4px 0 24px 0; font-size: 1em }}
  h3 {{ color: {COLORS['amber']}; margin: 32px 0 12px 0; font-size: 1.1em }}
  h4 {{ color: {COLORS['blue']}; margin: 20px 0 8px 0; font-size: 1em }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.82em;
           background: {COLORS['panel']}; border-radius: 6px; overflow: hidden;
           margin-bottom: 24px }}
  th {{ background: {COLORS['panel']}; color: {COLORS['amber']}; padding: 9px 12px;
        text-align: left; border-bottom: 2px solid {COLORS['grid']}; white-space: nowrap }}
  td {{ padding: 8px 12px; border-bottom: 1px solid {COLORS['grid']}; white-space: nowrap }}
  tr:hover td {{ background: {COLORS['grid']} }}
  td.pos {{ color: {COLORS['bull']}; font-weight: bold }}
  td.neg {{ color: {COLORS['bear']}; font-weight: bold }}
  td.amber {{ color: {COLORS['amber']}; font-weight: bold }}
  td.blue {{ color: {COLORS['blue']}; font-weight: bold }}
  td.muted {{ color: {COLORS['muted']} }}
  .tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px;
          font-size: 0.85em; font-weight: bold }}
  .tag-stable     {{ background: #1a4731; color: {COLORS['bull']} }}
  .tag-acceptable {{ background: #2d2d0a; color: {COLORS['amber']} }}
  .tag-unstable   {{ background: #3d1010; color: {COLORS['bear']} }}
  .tag-na         {{ background: {COLORS['grid']}; color: {COLORS['muted']} }}
  .verdict {{ background: {COLORS['panel']}; border-left: 3px solid {COLORS['amber']};
              padding: 14px 18px; margin: 12px 0; border-radius: 0 6px 6px 0;
              line-height: 1.6; font-size: 0.92em }}
  .verdict.good {{ border-color: {COLORS['bull']} }}
  .verdict.warn {{ border-color: {COLORS['bear']} }}
  .verdict b {{ color: {COLORS['amber']} }}
  .verdict.good b {{ color: {COLORS['bull']} }}
  .verdict.warn b {{ color: {COLORS['bear']} }}
  .periods {{ background: {COLORS['panel']}; border: 1px solid {COLORS['grid']};
              border-radius: 8px; padding: 12px 18px; margin-bottom: 24px;
              font-size: 0.88em; line-height: 1.7 }}
  .periods b {{ color: {COLORS['amber']} }}
  .chart {{ background: {COLORS['panel']}; border: 1px solid {COLORS['grid']};
            border-radius: 10px; padding: 12px; margin-bottom: 20px }}
  .footer {{ color: #484f58; font-size: 0.78em; margin-top: 28px }}
</style>
"""


def _cls_R(v: float) -> str:
    return "pos" if v > 0 else "neg" if v < 0 else "muted"


def _mode_table(results: dict, mode_label: str) -> str:
    """Build the IS-vs-OOS comparison table for one mode."""
    header = f"""
    <thead><tr>
      <th rowspan="2">Instrument</th>
      <th colspan="4" style="text-align:center;color:{COLORS['blue']}">In-Sample (80%)</th>
      <th colspan="4" style="text-align:center;color:{COLORS['amber']}">Out-of-Sample (20%)</th>
      <th rowspan="2">Edge Stable?</th>
    </tr>
    <tr>
      <th>Trades</th><th>WR</th><th>Avg R</th><th>Total R</th>
      <th>Trades</th><th>WR</th><th>Avg R</th><th>Total R</th>
    </tr></thead>"""

    rows = []
    for inst in INSTRUMENTS:
        key = (inst, mode_label)
        if key not in results:
            continue
        r = results[key]
        is_s, oos_s = r["is_stats"], r["oos_stats"]

        if is_s["n"] == 0:
            rows.append(f"<tr><td><b>{inst}</b></td><td colspan='9' class='muted'>No IS data</td></tr>")
            continue

        # Overall stability tag (based on avg_r)
        tag = stability_tag(is_s.get("avg_r", 0), oos_s.get("avg_r", 0))

        # If OOS has 0 trades, separate handling
        if oos_s["n"] == 0:
            tag = "n/a"
            oos_cells = "<td class='muted'>0</td>" * 4
        else:
            oos_cells = f"""
            <td class="blue">{oos_s['n']}</td>
            <td class="{_cls_R(oos_s['win_rate']-50)}">{oos_s['win_rate']:.1f}%</td>
            <td class="{_cls_R(oos_s['avg_r'])}">{oos_s['avg_r']:+.3f}</td>
            <td class="{_cls_R(oos_s['total_r'])}">{oos_s['total_r']:+.2f}R</td>"""

        rows.append(f"""
        <tr>
          <td><b>{inst}</b></td>
          <td class="blue">{is_s['n']}</td>
          <td class="{_cls_R(is_s['win_rate']-50)}">{is_s['win_rate']:.1f}%</td>
          <td class="{_cls_R(is_s['avg_r'])}">{is_s['avg_r']:+.3f}</td>
          <td class="{_cls_R(is_s['total_r'])}">{is_s['total_r']:+.2f}R</td>
          {oos_cells}
          <td><span class="tag tag-{tag.replace('/', '')}">{tag}</span></td>
        </tr>""")

    # Compute overall mode-level totals
    is_totals_r = sum(results[(i, mode_label)]["is_stats"]["total_r"]
                     for i in INSTRUMENTS if (i, mode_label) in results
                     and results[(i, mode_label)]["is_stats"]["n"] > 0)
    oos_totals_r = sum(results[(i, mode_label)]["oos_stats"]["total_r"]
                      for i in INSTRUMENTS if (i, mode_label) in results
                      and results[(i, mode_label)]["oos_stats"]["n"] > 0)
    is_n = sum(results[(i, mode_label)]["is_stats"]["n"]
              for i in INSTRUMENTS if (i, mode_label) in results)
    oos_n = sum(results[(i, mode_label)]["oos_stats"]["n"]
               for i in INSTRUMENTS if (i, mode_label) in results)

    # Aggregate tag based on total R proportion
    if is_totals_r > 0 and oos_n > 0:
        # Annualize: IS covers ~3.2 years, OOS covers ~0.8 years (4× factor)
        expected_oos = is_totals_r / 4.0
        if oos_totals_r >= expected_oos * 0.8:
            agg_tag = "stable"
        elif oos_totals_r >= expected_oos * 0.5:
            agg_tag = "acceptable"
        else:
            agg_tag = "unstable"
    else:
        agg_tag = "n/a"

    rows.append(f"""
    <tr style="background:{COLORS['grid']}">
      <td><b>TOTAL</b></td>
      <td class="blue"><b>{is_n}</b></td>
      <td>—</td>
      <td>—</td>
      <td class="{_cls_R(is_totals_r)}"><b>{is_totals_r:+.2f}R</b></td>
      <td class="blue"><b>{oos_n}</b></td>
      <td>—</td>
      <td>—</td>
      <td class="{_cls_R(oos_totals_r)}"><b>{oos_totals_r:+.2f}R</b></td>
      <td><span class="tag tag-{agg_tag.replace('/', '')}">{agg_tag}</span></td>
    </tr>""")

    return f"<table>{header}<tbody>{''.join(rows)}</tbody></table>"


def _annualized_chart(results: dict, mode_label: str) -> str:
    """Bar chart comparing IS (annualized) vs OOS (annualized) avg R per trade."""
    instruments = []
    is_vals = []
    oos_vals = []
    for inst in INSTRUMENTS:
        key = (inst, mode_label)
        if key not in results: continue
        is_s = results[key]["is_stats"]
        oos_s = results[key]["oos_stats"]
        if is_s["n"] == 0: continue
        instruments.append(inst)
        is_vals.append(is_s.get("avg_r", 0))
        oos_vals.append(oos_s.get("avg_r", 0) if oos_s["n"] > 0 else None)

    fig = go.Figure()
    fig.add_trace(go.Bar(name="IS (80%)", x=instruments, y=is_vals,
                          marker_color=COLORS["blue"],
                          text=[f"{v:+.3f}" for v in is_vals], textposition="outside"))
    fig.add_trace(go.Bar(name="OOS (20%)", x=instruments, y=oos_vals,
                          marker_color=COLORS["amber"],
                          text=[f"{v:+.3f}" if v is not None else "—" for v in oos_vals],
                          textposition="outside"))
    fig.add_hline(y=0, line=dict(color=COLORS["muted"], dash="dash"))
    fig.update_layout(
        title=f"Avg R per trade — IS vs OOS  ({mode_label})",
        barmode="group",
        paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["panel"],
        font=dict(family="Consolas, monospace", color=COLORS["text"], size=11),
        height=380, margin=dict(l=50, r=30, t=50, b=40),
        xaxis=dict(gridcolor=COLORS["grid"]),
        yaxis=dict(gridcolor=COLORS["grid"], title="Avg R per trade"),
        legend=dict(bgcolor=COLORS["panel"]),
    )
    return pio.to_html(fig, include_plotlyjs="cdn", full_html=False, default_height=380)


def _build_verdict(results: dict, mode_label: str) -> str:
    """Generate a written verdict for one mode based on IS vs OOS stability."""
    stable_count = 0
    acceptable_count = 0
    unstable_count = 0
    no_oos_count = 0
    profitable_oos = []
    losing_oos = []

    for inst in INSTRUMENTS:
        key = (inst, mode_label)
        if key not in results: continue
        is_s = results[key]["is_stats"]
        oos_s = results[key]["oos_stats"]
        if is_s["n"] == 0: continue
        if oos_s["n"] == 0:
            no_oos_count += 1
            continue
        tag = stability_tag(is_s.get("avg_r", 0), oos_s.get("avg_r", 0))
        if tag == "stable":     stable_count += 1
        if tag == "acceptable": acceptable_count += 1
        if tag == "unstable":   unstable_count += 1
        if oos_s.get("total_r", 0) > 0:
            profitable_oos.append((inst, oos_s["total_r"]))
        else:
            losing_oos.append((inst, oos_s["total_r"]))

    n_tested = stable_count + acceptable_count + unstable_count
    if n_tested == 0:
        return f'<div class="verdict warn">No OOS data for {mode_label} — cannot validate edge.</div>'

    verdict_class = "good" if (stable_count + acceptable_count) >= n_tested * 0.66 else "warn"
    profitable_oos.sort(key=lambda x: -x[1])

    text = (f"<b>{mode_label}:</b> Of {n_tested} instruments with OOS data, "
            f"<b>{stable_count} were stable, {acceptable_count} acceptable, "
            f"and {unstable_count} unstable</b>. ")
    if profitable_oos:
        winners = ", ".join(f"{i} ({r:+.2f}R)" for i, r in profitable_oos)
        text += f"Profitable OOS: {winners}. "
    if losing_oos:
        losers = ", ".join(f"{i} ({r:+.2f}R)" for i, r in losing_oos)
        text += f"Losing OOS: {losers}. "
    if no_oos_count:
        text += f"{no_oos_count} instruments had no OOS trades. "

    return f'<div class="verdict {verdict_class}">{text}</div>'


def generate_walk_forward_html(results: dict, period_str: str, split_date: str,
                                  out_path: Path):
    """Generate the main walk-forward comparison HTML."""
    mode_sections = []
    for mode_label, htf, ltf in MODES:
        verdict = _build_verdict(results, mode_label)
        chart = _annualized_chart(results, mode_label)
        table = _mode_table(results, mode_label)
        mode_sections.append(f"""
        <h3>{mode_label.upper()}  (HTF: {htf}, LTF: {ltf})</h3>
        {verdict}
        <div class="chart">{chart}</div>
        {table}""")

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>SMC CRT — 80/20 Walk-Forward Test</title>
{_CSS}
</head><body>

<h1>SMC CRT Strategy — 80/20 Walk-Forward Validation</h1>
<h2>4 years of data across 6 instruments × 2 timeframes ·
    $100,000 account · 1% risk/trade</h2>

<div class="periods">
  <b>Data period:</b> {period_str}<br>
  <b>Split date:</b> {split_date}<br>
  <b>In-Sample (80%):</b> 2022-05-12 → {split_date} &nbsp;(~3.2 years)<br>
  <b>Out-of-Sample (20%):</b> {split_date} → 2026-05-12 &nbsp;(~0.8 years, ~unseen data)
</div>

<div class="verdict">
  <b>Purpose:</b> The strategy has no learnable parameters — its rules came from ICT/CRT
  methodology, not from optimizing on data. This walk-forward test confirms that the
  edge persists on data we haven't deep-analyzed. If OOS metrics align with IS metrics
  (within 20% per instrument), the edge is genuinely structural; if OOS diverges
  sharply, the strategy is regime-dependent.
</div>

{''.join(mode_sections)}

<div class="footer">
  Generated by run_walk_forward.py · Stability classifier: stable ≤20%, acceptable ≤50%, unstable &gt;50%
</div>
</body></html>"""

    out_path.write_text(html, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", default=DATA_START_DEFAULT, help="Data start (YYYY-MM-DD)")
    p.add_argument("--end", default=DATA_END_DEFAULT, help="Data end (YYYY-MM-DD)")
    p.add_argument("--split", default=SPLIT_DATE_DEFAULT,
                    help=f"IS/OOS split date (default {SPLIT_DATE_DEFAULT})")
    p.add_argument("--out", default="./walk_output", help="Output directory")
    args = p.parse_args()

    print(f"\nWalk-Forward 80/20 Test")
    print(f"   Data period: {args.start} → {args.end}")
    print(f"   Split date:  {args.split}")
    print(f"   IS:  {args.start} → {args.split}")
    print(f"   OOS: {args.split} → {args.end}")
    print("=" * 70)

    results = {}
    for inst in INSTRUMENTS:
        for mode_label, htf, ltf in MODES:
            print(f"\n→ {inst}  {mode_label}")
            try:
                r = run_one_combo(inst, htf, ltf,
                                   args.start, args.end, args.split)
                results[(inst, mode_label)] = r
                is_s, oos_s = r["is_stats"], r["oos_stats"]
                is_str = (f"IS: {is_s['n']} trades, {is_s.get('avg_r', 0):+.3f} R/trade, "
                          f"{is_s.get('total_r', 0):+.2f}R total")
                oos_str = (f"OOS: {oos_s['n']} trades, {oos_s.get('avg_r', 0):+.3f} R/trade, "
                           f"{oos_s.get('total_r', 0):+.2f}R total"
                           if oos_s['n'] > 0 else "OOS: 0 trades")
                print(f"   {is_str}")
                print(f"   {oos_str}")
            except FileNotFoundError as e:
                print(f"   ⚠ Data missing: {e}")
                results[(inst, mode_label)] = {
                    "full_stats": {"n": 0}, "is_stats": {"n": 0}, "oos_stats": {"n": 0},
                }
            except Exception as e:
                print(f"   ⚠ Error: {e}")
                results[(inst, mode_label)] = {
                    "full_stats": {"n": 0}, "is_stats": {"n": 0}, "oos_stats": {"n": 0},
                }

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "walk_forward.html"

    print("\n" + "=" * 70)
    print("Generating comparison HTML...")
    generate_walk_forward_html(
        results, period_str=f"{args.start} → {args.end}",
        split_date=args.split, out_path=html_path,
    )

    # Also save raw stats for downstream tools
    json_path = out_dir / "walk_forward_stats.json"
    json_path.write_text(json.dumps({
        "period": f"{args.start} → {args.end}",
        "split_date": args.split,
        "results": {f"{k[0]}_{k[1]}": v for k, v in results.items()},
    }, indent=2, default=str))

    print(f"\n✓ Walk-forward report: {html_path.resolve()}")
    print(f"  Stats JSON:           {json_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
