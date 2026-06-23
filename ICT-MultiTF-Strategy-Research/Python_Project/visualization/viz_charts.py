"""
viz_charts.py — Plotly chart generation for trade visualization.

Generates per-trade Plotly figures with full annotations:
    - HTF (H4) panel: candles around trigger, prev range, mid, sweep
    - LTF (M15/M5) panel: candles during trade, MSS, FVG, OB, entry/stop/target/partials
    - Event markers at entry, partials, stop moves, exit
    - R outcome annotation
"""
from __future__ import annotations
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from viz_engine import TradeRecord


# Color palette (terminal-style dark theme)
COLORS = {
    "bg":           "#0d1117",
    "panel":        "#161b22",
    "grid":         "#21262d",
    "text":         "#c9d1d9",
    "muted":        "#8b949e",
    "bull":         "#2ecc71",
    "bear":         "#e74c3c",
    "amber":        "#e6b450",
    "blue":         "#58a6ff",
    "fvg":          "rgba(88, 166, 255, 0.20)",
    "fvg_border":   "#58a6ff",
    "ob":           "rgba(230, 180, 80, 0.25)",
    "ob_border":    "#e6b450",
    "entry":        "#58a6ff",
    "stop":         "#e74c3c",
    "target":       "#2ecc71",
    "mid":          "#e6b450",
    "partial":      "#a371f7",
    "sweep_mark":   "#ff7b72",
}


def _candle_trace(df: pd.DataFrame, name: str) -> go.Candlestick:
    """Create a candlestick trace from an OHLC DataFrame."""
    return go.Candlestick(
        x=df.index, open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name=name,
        increasing=dict(line=dict(color=COLORS["bull"]), fillcolor=COLORS["bull"]),
        decreasing=dict(line=dict(color=COLORS["bear"]), fillcolor=COLORS["bear"]),
        showlegend=False,
    )


def _hline_shape(y: float, x0, x1, color: str, dash: str = "dash",
                  width: int = 1) -> dict:
    return dict(type="line", x0=x0, x1=x1, y0=y, y1=y,
                line=dict(color=color, width=width, dash=dash))


def _rect_shape(x0, x1, y0: float, y1: float, fillcolor: str,
                 line_color: str | None = None) -> dict:
    return dict(type="rect", x0=x0, x1=x1, y0=y0, y1=y1,
                fillcolor=fillcolor,
                line=dict(color=line_color or "rgba(0,0,0,0)", width=1),
                layer="below")


def make_trade_chart(rec: TradeRecord) -> go.Figure:
    """Build a 2-panel Plotly figure (HTF + LTF) for a single trade."""
    if rec.htf_bars is None or rec.ltf_bars is None:
        raise ValueError("TradeRecord must have htf_bars and ltf_bars populated")

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=False,
        row_heights=[0.40, 0.60],
        subplot_titles=(
            f"{rec.instrument} {rec.htf_freq} — setup context",
            f"{rec.instrument} {rec.ltf_freq} — entry & trade execution"
        ),
        vertical_spacing=0.08,
    )

    # ---------- HTF panel (top) ----------
    htf = rec.htf_bars
    fig.add_trace(_candle_trace(htf, "HTF"), row=1, col=1)

    # Reference lines: prev high/low, mid
    x0_htf, x1_htf = htf.index.min(), htf.index.max()
    htf_shapes = [
        _hline_shape(rec.prev_high, x0_htf, x1_htf, COLORS["text"], "solid"),
        _hline_shape(rec.prev_low,  x0_htf, x1_htf, COLORS["text"], "solid"),
        _hline_shape(rec.prev_mid,  x0_htf, x1_htf, COLORS["mid"],  "dot"),
        _hline_shape(rec.target,    x0_htf, x1_htf, COLORS["target"], "dash", 2),
    ]
    # Highlight the sweep candle with a vertical band
    sweep_x = rec.trigger_time
    htf_period = pd.Timedelta(rec.htf_freq)
    htf_shapes.append(dict(
        type="rect", xref="x1", yref="paper",
        x0=sweep_x, x1=sweep_x + htf_period,
        y0=0, y1=1,
        fillcolor="rgba(255, 123, 114, 0.10)",
        line=dict(color=COLORS["sweep_mark"], width=1, dash="dot"),
        layer="below",
    ))

    # HTF panel annotations
    htf_annots = [
        dict(x=x1_htf, y=rec.prev_high, text=f"prev high {rec.prev_high:.5f}",
             showarrow=False, xanchor="right", yanchor="bottom",
             font=dict(color=COLORS["muted"], size=10)),
        dict(x=x1_htf, y=rec.prev_low, text=f"prev low {rec.prev_low:.5f}",
             showarrow=False, xanchor="right", yanchor="top",
             font=dict(color=COLORS["muted"], size=10)),
        dict(x=x1_htf, y=rec.prev_mid, text=f"mid {rec.prev_mid:.5f}",
             showarrow=False, xanchor="right", yanchor="bottom",
             font=dict(color=COLORS["mid"], size=10)),
        dict(x=x1_htf, y=rec.target,
             text=f"target {rec.target:.5f}",
             showarrow=False, xanchor="right", yanchor="bottom",
             font=dict(color=COLORS["target"], size=10)),
        dict(x=sweep_x, y=rec.sweep_extreme,
             text=f"  SWEEP ({'BEAR' if rec.is_bear else 'BULL'})",
             showarrow=False, xanchor="left",
             font=dict(color=COLORS["sweep_mark"], size=11, family="Consolas")),
    ]

    # ---------- LTF panel (bottom) ----------
    ltf = rec.ltf_bars
    fig.add_trace(_candle_trace(ltf, "LTF"), row=2, col=1)

    x0_ltf, x1_ltf = ltf.index.min(), ltf.index.max()
    ltf_shapes = []
    ltf_annots = []

    # Reference lines: mid, target
    ltf_shapes.append(_hline_shape(rec.prev_mid, x0_ltf, x1_ltf,
                                    COLORS["mid"], "dot"))
    ltf_shapes.append(_hline_shape(rec.target, x0_ltf, x1_ltf,
                                    COLORS["target"], "dash", 2))

    # FVG zone (filled rectangle from j-2 to j bars)
    if rec.fvg_level is not None and rec.fvg_bars is not None:
        # FVG levels — for bear: between low[j-2] and high[j]; for bull: between high[j-2] and low[j]
        # We need actual prices, but only have the midpoint stored — use level ± approximation
        # Better: redo the FVG bounds calculation from the LTF bars
        htf_close = rec.trigger_time + pd.Timedelta(rec.htf_freq)
        after_htf = ltf.loc[ltf.index >= htf_close].reset_index()
        j2, j = rec.fvg_bars
        if j < len(after_htf):
            if rec.is_bear:
                fvg_top = after_htf.loc[j2, "low"]
                fvg_bot = after_htf.loc[j, "high"]
            else:
                fvg_top = after_htf.loc[j, "low"]
                fvg_bot = after_htf.loc[j2, "high"]
            fvg_x0 = after_htf.loc[j2, "time"] if "time" in after_htf.columns \
                     else after_htf.iloc[j2].name
            fvg_x1 = x1_ltf
            ltf_shapes.append(_rect_shape(fvg_x0, fvg_x1, fvg_bot, fvg_top,
                                            COLORS["fvg"], COLORS["fvg_border"]))
            ltf_annots.append(dict(
                x=fvg_x0, y=(fvg_top + fvg_bot) / 2.0,
                text=f"FVG {rec.fvg_level:.5f}", showarrow=False,
                xanchor="left", yanchor="middle",
                font=dict(color=COLORS["fvg_border"], size=10, family="Consolas")))

    # OB body rectangle
    if rec.ob_level is not None and rec.ob_bar_idx is not None:
        htf_close = rec.trigger_time + pd.Timedelta(rec.htf_freq)
        after_htf = ltf.loc[ltf.index >= htf_close].reset_index()
        if rec.ob_bar_idx < len(after_htf):
            ob_bar = after_htf.iloc[rec.ob_bar_idx]
            ob_top = max(ob_bar["open"], ob_bar["close"])
            ob_bot = min(ob_bar["open"], ob_bar["close"])
            ob_x0 = ob_bar["time"] if "time" in after_htf.columns else after_htf.index[rec.ob_bar_idx]
            ob_x1 = x1_ltf
            ltf_shapes.append(_rect_shape(ob_x0, ob_x1, ob_bot, ob_top,
                                            COLORS["ob"], COLORS["ob_border"]))
            ltf_annots.append(dict(
                x=ob_x0, y=(ob_top + ob_bot) / 2.0,
                text=f"OB {rec.ob_level:.5f}", showarrow=False,
                xanchor="left", yanchor="middle",
                font=dict(color=COLORS["ob_border"], size=10, family="Consolas")))

    # MSS marker (vertical line)
    if rec.mss_time is not None:
        ltf_shapes.append(dict(
            type="line", xref="x2", yref="paper",
            x0=rec.mss_time, x1=rec.mss_time, y0=0, y1=1,
            line=dict(color=COLORS["amber"], width=2, dash="dash"),
        ))
        ltf_annots.append(dict(
            x=rec.mss_time, y=1.0, yref="paper",
            text="MSS", showarrow=False,
            xanchor="left", yanchor="top",
            font=dict(color=COLORS["amber"], size=11, family="Consolas")))

    # Entry / Stop / Target / Partial price lines
    if rec.entry_price is not None:
        ltf_shapes.append(_hline_shape(rec.entry_price, x0_ltf, x1_ltf,
                                         COLORS["entry"], "solid", 2))
        ltf_annots.append(dict(
            x=x0_ltf, y=rec.entry_price, text=f"  entry {rec.entry_price:.5f}",
            showarrow=False, xanchor="left", yanchor="bottom",
            font=dict(color=COLORS["entry"], size=10, family="Consolas")))

    if rec.stop_price is not None:
        ltf_shapes.append(_hline_shape(rec.stop_price, x0_ltf, x1_ltf,
                                         COLORS["stop"], "solid", 2))
        ltf_annots.append(dict(
            x=x0_ltf, y=rec.stop_price, text=f"  stop {rec.stop_price:.5f}",
            showarrow=False, xanchor="left", yanchor="bottom",
            font=dict(color=COLORS["stop"], size=10, family="Consolas")))

    # Partial price lines (1R, 2R, target)
    if rec.entry_price is not None and rec.r_distance is not None:
        if rec.is_bear:
            p1 = max(rec.entry_price - rec.r_distance, rec.target)
            p2 = max(rec.entry_price - 2 * rec.r_distance, rec.target)
        else:
            p1 = min(rec.entry_price + rec.r_distance, rec.target)
            p2 = min(rec.entry_price + 2 * rec.r_distance, rec.target)
        # Only show distinct partial levels (collapse to target when target < 1R)
        if abs(p1 - rec.target) > 1e-8:
            ltf_shapes.append(_hline_shape(p1, x0_ltf, x1_ltf,
                                             COLORS["partial"], "dot"))
            ltf_annots.append(dict(
                x=x0_ltf, y=p1, text=f"  P1 (1R)  {p1:.5f}",
                showarrow=False, xanchor="left", yanchor="bottom",
                font=dict(color=COLORS["partial"], size=9)))
        if abs(p2 - rec.target) > 1e-8 and abs(p2 - p1) > 1e-8:
            ltf_shapes.append(_hline_shape(p2, x0_ltf, x1_ltf,
                                             COLORS["partial"], "dot"))
            ltf_annots.append(dict(
                x=x0_ltf, y=p2, text=f"  P2 (2R)  {p2:.5f}",
                showarrow=False, xanchor="left", yanchor="bottom",
                font=dict(color=COLORS["partial"], size=9)))

    # Event markers (entry fill, partials, exit) plotted as scatter
    event_x, event_y, event_text, event_color, event_symbol = [], [], [], [], []
    SYMBOL_MAP = {
        "entry":    "triangle-up",
        "partial1": "diamond",
        "partial2": "diamond",
        "partial3": "diamond-cross",
        "exit":     "x",
        "stop_move":"line-ns-open",
    }
    COLOR_MAP = {
        "entry":    COLORS["entry"],
        "partial1": COLORS["partial"],
        "partial2": COLORS["partial"],
        "partial3": COLORS["target"],
        "exit":     COLORS["bear"] if rec.exit_reason == "stop" else COLORS["target"],
        "stop_move":COLORS["amber"],
    }
    for ev in rec.events:
        if ev.kind in SYMBOL_MAP and ev.price is not None:
            event_x.append(ev.time)
            event_y.append(ev.price)
            event_text.append(f"{ev.kind}: {ev.detail}")
            event_color.append(COLOR_MAP.get(ev.kind, COLORS["text"]))
            event_symbol.append(SYMBOL_MAP[ev.kind])

    if event_x:
        fig.add_trace(go.Scatter(
            x=event_x, y=event_y, mode="markers",
            marker=dict(size=14, color=event_color, symbol=event_symbol,
                        line=dict(width=2, color=COLORS["bg"])),
            text=event_text, hoverinfo="text",
            showlegend=False, name="events",
        ), row=2, col=1)

    # Apply shapes & annotations
    fig.update_layout(shapes=htf_shapes + ltf_shapes,
                       annotations=fig.layout.annotations[:2] + tuple(htf_annots + ltf_annots))

    # ---------- Layout styling ----------
    direction = "BEAR" if rec.is_bear else "BULL"
    r_str = f"{rec.r_total:+.2f}R"
    win_color = COLORS["bull"] if rec.r_total > 0 else COLORS["bear"]
    exit_reason = rec.exit_reason or "n/a"

    title = (f"<b>{rec.instrument}</b> · {direction} · {rec.entry_type or 'n/a'} entry  ·  "
             f"<span style='color:{win_color}'>R: {r_str}</span>  ·  "
             f"exit: {exit_reason}  ·  partials: {rec.n_partials}")

    fig.update_layout(
        title=dict(text=title, x=0.01, font=dict(size=14, color=COLORS["text"],
                                                    family="Consolas")),
        paper_bgcolor=COLORS["bg"],
        plot_bgcolor=COLORS["panel"],
        font=dict(family="Consolas, monospace", color=COLORS["text"], size=11),
        height=720,
        margin=dict(l=50, r=30, t=80, b=40),
        xaxis=dict(rangeslider=dict(visible=False), gridcolor=COLORS["grid"],
                   showline=True, linecolor=COLORS["grid"]),
        xaxis2=dict(rangeslider=dict(visible=False), gridcolor=COLORS["grid"],
                    showline=True, linecolor=COLORS["grid"]),
        yaxis=dict(gridcolor=COLORS["grid"], showline=True, linecolor=COLORS["grid"]),
        yaxis2=dict(gridcolor=COLORS["grid"], showline=True, linecolor=COLORS["grid"]),
        hovermode="x unified",
    )
    fig.update_xaxes(showspikes=True, spikecolor=COLORS["muted"],
                      spikethickness=1, spikedash="dot")
    fig.update_yaxes(showspikes=True, spikecolor=COLORS["muted"],
                      spikethickness=1, spikedash="dot")

    return fig


def make_equity_curve(trades: list[TradeRecord]) -> go.Figure:
    """Plot cumulative R curve over time."""
    completed = [t for t in trades if t.exit_reason not in (None, "no_fill")]
    if not completed:
        return go.Figure()
    completed.sort(key=lambda t: t.exit_time)
    times = [t.exit_time for t in completed]
    rs = [t.r_total for t in completed]
    cum_r = np.cumsum(rs)
    peak = np.maximum.accumulate(cum_r)
    dd = peak - cum_r

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                         row_heights=[0.70, 0.30],
                         subplot_titles=("Cumulative R", "Drawdown (R)"),
                         vertical_spacing=0.10)
    fig.add_trace(go.Scatter(x=times, y=cum_r, mode="lines+markers",
                              line=dict(color=COLORS["bull"], width=2),
                              marker=dict(size=4),
                              name="Cumulative R"), row=1, col=1)
    fig.add_trace(go.Scatter(x=times, y=peak, mode="lines",
                              line=dict(color=COLORS["amber"], width=1, dash="dash"),
                              name="Peak"), row=1, col=1)
    fig.add_trace(go.Scatter(x=times, y=-dd, mode="lines", fill="tozeroy",
                              line=dict(color=COLORS["bear"], width=1),
                              fillcolor="rgba(231, 76, 60, 0.25)",
                              showlegend=False), row=2, col=1)

    fig.update_layout(
        paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["panel"],
        font=dict(family="Consolas, monospace", color=COLORS["text"], size=11),
        height=460,
        margin=dict(l=50, r=30, t=50, b=40),
        legend=dict(bgcolor=COLORS["panel"], font=dict(color=COLORS["text"])),
    )
    fig.update_xaxes(gridcolor=COLORS["grid"])
    fig.update_yaxes(gridcolor=COLORS["grid"])
    return fig


def make_r_histogram(trades: list[TradeRecord]) -> go.Figure:
    """Histogram of R outcomes."""
    completed = [t for t in trades if t.exit_reason not in (None, "no_fill")]
    rs = [t.r_total for t in completed]
    if not rs:
        return go.Figure()
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=rs, nbinsx=25,
                                marker=dict(color=COLORS["blue"],
                                            line=dict(color=COLORS["bg"], width=1))))
    fig.add_vline(x=0, line=dict(color=COLORS["muted"], dash="dash"))
    fig.add_vline(x=np.mean(rs), line=dict(color=COLORS["amber"], dash="dot"),
                   annotation_text=f"mean {np.mean(rs):.2f}R",
                   annotation_position="top right",
                   annotation_font=dict(color=COLORS["amber"]))
    fig.update_layout(
        title="R outcome distribution",
        paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["panel"],
        font=dict(family="Consolas, monospace", color=COLORS["text"], size=11),
        height=320, margin=dict(l=50, r=30, t=50, b=40),
        xaxis=dict(title="R per trade", gridcolor=COLORS["grid"]),
        yaxis=dict(title="Trade count", gridcolor=COLORS["grid"]),
    )
    return fig
