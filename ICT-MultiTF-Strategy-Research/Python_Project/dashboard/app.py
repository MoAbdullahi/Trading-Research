"""
CRT + ICT PD Array — Strategy Parameter Testing Dashboard
==========================================================
Run:
    cd Python_Project/dashboard
    pip install -r ../requirements.txt
    python app.py
Then open http://127.0.0.1:8050 in your browser.
"""
from __future__ import annotations

import sys
import json
import traceback
import calendar as _cal
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

import dash
from dash import dcc, html, dash_table, Input, Output, State, ctx, no_update
import dash_bootstrap_components as dbc

# ── Import engine from sibling directory ─────────────────────────────────────
ROOT = Path(__file__).parent.parent          # Python_Project/
sys.path.insert(0, str(ROOT))
from engine.phase2_engine import (
    run_backtest, ALL_SESSIONS, GO_SESSIONS,
    SPREADS, DEFAULT_DATA_PATH,
)

DATA_PATH = ROOT.parent / "data"             # CRT+ICT PD Array Research/data/

# ── Colour palette (GitHub Dark) ─────────────────────────────────────────────
C = {
    "bg":        "#0d1117",
    "surface":   "#161b22",
    "surface2":  "#21262d",
    "border":    "#30363d",
    "text":      "#e6edf3",
    "muted":     "#8b949e",
    "green":     "#3fb950",
    "red":       "#f85149",
    "blue":      "#58a6ff",
    "orange":    "#d29922",
    "purple":    "#bc8cff",
    "cyan":      "#39d353",
    "teal":      "#2ea6a6",
}

PLOTLY_TEMPLATE = dict(
    layout=dict(
        paper_bgcolor=C["bg"],
        plot_bgcolor=C["surface"],
        font=dict(color=C["text"], size=12),
        xaxis=dict(gridcolor=C["border"], linecolor=C["border"], zerolinecolor=C["border"]),
        yaxis=dict(gridcolor=C["border"], linecolor=C["border"], zerolinecolor=C["border"]),
        legend=dict(bgcolor=C["surface2"], bordercolor=C["border"]),
        margin=dict(l=50, r=20, t=40, b=40),
    )
)

# ── USD value per 1.0 price-unit move per standard lot ───────────────────────
# EURUSD/GBPUSD: 100k units base → $100k per full price unit
# USDJPY: 100k USD / entry_rate  (computed dynamically per trade)
# XAUUSD: 100 oz per lot → $100 per $1 gold move
# NAS100/US30: $1 per index point per lot (FTMO contract spec)
VALUE_PER_PRICE_UNIT: dict[str, float] = {
    "EURUSD": 100_000.0,
    "GBPUSD": 100_000.0,
    "USDJPY": None,      # computed from entry_price at runtime
    "XAUUSD": 100.0,
    "NAS100": 1.0,
    "US30":   1.0,
}

# ── News calendar ────────────────────────────────────────────────────────────

def _first_friday(year: int, month: int) -> str:
    weeks = _cal.monthcalendar(year, month)
    day = weeks[0][_cal.FRIDAY] or weeks[1][_cal.FRIDAY]
    return f"{year}-{month:02d}-{day:02d}"


def nfp_dates(start_year: int, end_year: int) -> set[str]:
    return {_first_friday(y, m) for y in range(start_year, end_year + 1) for m in range(1, 13)}


# Actual FOMC statement dates 2020-2025
FOMC_DATES: set[str] = {
    "2020-01-29","2020-03-03","2020-03-15","2020-04-29","2020-06-10",
    "2020-07-29","2020-09-16","2020-11-05","2020-12-16",
    "2021-01-27","2021-03-17","2021-04-28","2021-06-16","2021-07-28",
    "2021-09-22","2021-11-03","2021-12-15",
    "2022-01-26","2022-03-16","2022-05-04","2022-06-15","2022-07-27",
    "2022-09-21","2022-11-02","2022-12-14",
    "2023-02-01","2023-03-22","2023-05-03","2023-06-14","2023-07-26",
    "2023-09-20","2023-11-01","2023-12-13",
    "2024-01-31","2024-03-20","2024-05-01","2024-06-12","2024-07-31",
    "2024-09-18","2024-11-07","2024-12-18",
    "2025-01-29","2025-03-19","2025-05-07","2025-06-18","2025-07-30",
    "2025-09-17","2025-11-05","2025-12-17",
}

# Approximate US CPI release dates 2020-2025 (Bureau of Labor Statistics, ~8:30 AM ET)
CPI_DATES: set[str] = {
    "2020-01-14","2020-02-13","2020-03-11","2020-04-10","2020-05-12","2020-06-10",
    "2020-07-14","2020-08-12","2020-09-11","2020-10-13","2020-11-12","2020-12-10",
    "2021-01-13","2021-02-10","2021-03-10","2021-04-13","2021-05-12","2021-06-10",
    "2021-07-13","2021-08-11","2021-09-14","2021-10-13","2021-11-10","2021-12-10",
    "2022-01-12","2022-02-10","2022-03-10","2022-04-12","2022-05-11","2022-06-10",
    "2022-07-13","2022-08-10","2022-09-13","2022-10-13","2022-11-10","2022-12-13",
    "2023-01-12","2023-02-14","2023-03-14","2023-04-12","2023-05-10","2023-06-13",
    "2023-07-12","2023-08-10","2023-09-13","2023-10-12","2023-11-14","2023-12-12",
    "2024-01-11","2024-02-13","2024-03-12","2024-04-10","2024-05-15","2024-06-12",
    "2024-07-11","2024-08-14","2024-09-11","2024-10-10","2024-11-13","2024-12-11",
    "2025-01-15","2025-02-12","2025-03-12","2025-04-10","2025-05-13","2025-06-11",
}

# ECB monetary policy decision dates 2020-2025
ECB_DATES: set[str] = {
    "2020-01-23","2020-03-12","2020-04-30","2020-06-04","2020-07-16",
    "2020-09-10","2020-10-29","2020-12-10",
    "2021-01-21","2021-03-11","2021-04-22","2021-06-10","2021-07-22",
    "2021-09-09","2021-10-28","2021-12-16",
    "2022-02-03","2022-03-10","2022-04-14","2022-06-09","2022-07-21",
    "2022-09-08","2022-10-27","2022-12-15",
    "2023-02-02","2023-03-16","2023-05-04","2023-06-15","2023-07-27",
    "2023-09-14","2023-10-26","2023-12-14",
    "2024-01-25","2024-03-07","2024-04-11","2024-06-06","2024-07-18",
    "2024-09-12","2024-10-17","2024-12-12",
    "2025-01-30","2025-03-06","2025-04-17","2025-06-05","2025-07-24",
}

# ── Timeframe combos ──────────────────────────────────────────────────────────
TF_COMBOS = {
    "H4 → M15":  ("4h",    "15min"),
    "H4 → M5":   ("4h",    "5min"),
    "H1 → M15":  ("1h",    "15min"),
    "H1 → M5":   ("1h",    "5min"),
    "M15 → M5":  ("15min", "5min"),
    "M15 → M1":  ("15min", "1min"),
}

INSTRUMENTS = list(SPREADS.keys())

SESSION_LABELS = {
    "asian_kz":     "Asian Kill Zone  (20–22 NY)",
    "asian":        "Asian Session    (22–02 NY)",
    "london_kz":    "London Kill Zone (02–05 NY)",
    "london":       "London Session   (05–07 NY)",
    "ny_am_kz":     "NY AM Kill Zone  (07–10 NY)",
    "london_close": "London Close     (10–12 NY)",
    "ny_pm":        "NY PM Session    (12–16 NY)",
    "off_hours":    "Off Hours        (16–20 NY)",
}
GO_SESSION_LIST = list(GO_SESSIONS)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _empty_fig(msg="No data"):
    fig = go.Figure()
    fig.add_annotation(text=msg, xref="paper", yref="paper",
                       x=0.5, y=0.5, showarrow=False,
                       font=dict(color=C["muted"], size=14))
    fig.update_layout(**PLOTLY_TEMPLATE["layout"])
    return fig


def _card(title, value, color=C["text"], subtitle=""):
    return dbc.Card([
        dbc.CardBody([
            html.P(title, className="stat-label"),
            html.H3(value, style={"color": color, "marginBottom": "2px"}),
            html.P(subtitle, className="stat-sub") if subtitle else html.Div(),
        ])
    ], className="stat-card")


def _section_header(label):
    return html.Div(label, className="section-header")


def _label(text):
    return html.Label(text, className="param-label")


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar — parameter controls
# ─────────────────────────────────────────────────────────────────────────────

def build_sidebar():
    return html.Div([
        html.Div([
            html.Span("CRT", className="brand-crt"),
            html.Span(" + ICT PD Array", className="brand-sub"),
        ], className="brand"),
        html.P("Strategy Backtester", className="brand-tagline"),
        html.Hr(className="sidebar-hr"),

        dbc.Accordion([

            # ── Universe ────────────────────────────────────────────────────
            dbc.AccordionItem([
                _label("Instruments"),
                dcc.Checklist(
                    id="inst-checklist",
                    options=[{"label": s, "value": s} for s in INSTRUMENTS],
                    value=["EURUSD"],
                    className="checklist-dark",
                    inputClassName="checklist-input",
                    labelClassName="checklist-label",
                ),
                html.Div([
                    dbc.Button("All", id="btn-all-inst", size="sm", className="preset-btn"),
                    dbc.Button("FX Only", id="btn-fx-inst", size="sm", className="preset-btn ms-1"),
                ], className="mt-2"),

                html.Div(style={"height": "12px"}),
                _label("Timeframe Pair"),
                dcc.Dropdown(
                    id="tf-combo",
                    options=[{"label": k, "value": k} for k in TF_COMBOS],
                    value="H4 → M15",
                    clearable=False,
                    className="dropdown-dark",
                ),

                html.Div(style={"height": "12px"}),
                _label("Partial Scheme"),
                dbc.RadioItems(
                    id="scheme-radio",
                    options=[
                        {"label": "Scheme A  (Fixed-R partials)", "value": "A"},
                        {"label": "Scheme B  (Structure partials)", "value": "B"},
                    ],
                    value="A",
                    className="radio-dark",
                ),

                html.Div(style={"height": "12px"}),
                _label("Date Range"),
                dbc.Row([
                    dbc.Col(dcc.DatePickerSingle(
                        id="date-start", date="2023-01-01",
                        display_format="YYYY-MM-DD",
                        className="date-picker",
                    ), width=6),
                    dbc.Col(dcc.DatePickerSingle(
                        id="date-end", date="2024-12-31",
                        display_format="YYYY-MM-DD",
                        className="date-picker",
                    ), width=6),
                ], className="g-1 mx-0"),
            ], title="Universe & Timeframe", item_id="universe"),

            # ── News Filter ───────────────────────────────────────────────────
            dbc.AccordionItem([
                dbc.Switch(id="news-filter-on", value=False,
                           label="Enable news blackout filter",
                           className="switch-dark mb-2"),

                _label("Exclude event types"),
                dcc.Checklist(
                    id="news-types",
                    options=[
                        {"label": "NFP  (Non-Farm Payrolls — 1st Fri/month)",  "value": "nfp"},
                        {"label": "FOMC (Fed rate decisions)",                   "value": "fomc"},
                        {"label": "CPI  (US inflation releases)",                "value": "cpi"},
                        {"label": "ECB  (ECB rate decisions)",                   "value": "ecb"},
                    ],
                    value=["nfp", "fomc"],
                    className="checklist-dark session-list",
                    inputClassName="checklist-input",
                    labelClassName="checklist-label",
                ),
                html.Div(style={"height": "10px"}),

                _label("Blackout window"),
                dbc.RadioItems(
                    id="news-window",
                    options=[
                        {"label": "Full day  (safest — skip entire date)",   "value": "day"},
                        {"label": "±4 hours around event",                    "value": "4h"},
                        {"label": "±2 hours around event",                    "value": "2h"},
                    ],
                    value="day",
                    className="radio-dark mb-2",
                ),

                _label("Custom blackout dates  (YYYY-MM-DD, one per line)"),
                dcc.Textarea(
                    id="custom-news-dates",
                    placeholder="2024-03-08\n2024-06-07\n...",
                    style={
                        "width": "100%", "height": "80px",
                        "backgroundColor": "#21262d", "color": "#e6edf3",
                        "border": "1px solid #30363d", "borderRadius": "6px",
                        "fontSize": "11px", "fontFamily": "JetBrains Mono, monospace",
                        "padding": "6px", "resize": "vertical",
                    },
                ),
                html.Div(id="news-filter-status", className="hint-text mt-1"),
            ], title="News Filter", item_id="news"),

            # ── CRT Filters ──────────────────────────────────────────────────
            dbc.AccordionItem([
                _label("Strong Filter"),
                dbc.Switch(id="strong-filter", value=True, label="Require close past 0.5 midpoint",
                           className="switch-dark"),
                html.Div(style={"height": "10px"}),

                _label("Min ATR Ratio (range candle size)"),
                dcc.Slider(id="atr-ratio", min=0.0, max=2.0, step=0.1, value=0.5,
                           marks={0: "0", 0.5: "0.5", 1: "1", 1.5: "1.5", 2: "2"},
                           className="slider-dark", tooltip={"placement": "bottom"}),

                html.Div(style={"height": "10px"}),
                _label("Sessions"),
                dcc.Checklist(
                    id="session-checklist",
                    options=[{"label": SESSION_LABELS[s], "value": s} for s in ALL_SESSIONS],
                    value=GO_SESSION_LIST,
                    className="checklist-dark session-list",
                    inputClassName="checklist-input",
                    labelClassName="checklist-label",
                ),
                html.Div([
                    dbc.Button("GO Sessions", id="btn-go-sess", size="sm", className="preset-btn"),
                    dbc.Button("All", id="btn-all-sess", size="sm", className="preset-btn ms-1"),
                ], className="mt-2"),
            ], title="CRT Filters", item_id="crt"),

            # ── Entry Settings ───────────────────────────────────────────────
            dbc.AccordionItem([
                _label("Entry Preference"),
                dbc.RadioItems(
                    id="entry-pref",
                    options=[
                        {"label": "Order Block + FVG  (Both)", "value": "BOTH"},
                        {"label": "Order Block only",           "value": "OB"},
                        {"label": "Fair Value Gap only",        "value": "FVG"},
                    ],
                    value="BOTH",
                    className="radio-dark",
                ),
                html.Div(style={"height": "10px"}),

                _label("Max Entry Window (LTF bars)"),
                dcc.Slider(id="entry-window", min=4, max=48, step=2, value=12,
                           marks={4: "4", 12: "12", 24: "24", 48: "48"},
                           className="slider-dark", tooltip={"placement": "bottom"}),
                html.Div(style={"height": "10px"}),

                _label("Market Structure Shift"),
                dbc.Switch(id="require-mss", value=True, label="Require MSS before entry",
                           className="switch-dark"),
                html.Div(style={"height": "10px"}),

                _label("Premium / Discount Filter"),
                dbc.Switch(id="require-pd", value=True, label="Entry must be in P/D array",
                           className="switch-dark"),
                html.Div(style={"height": "10px"}),

                _label("Stop Buffer (× ATR)"),
                dcc.Slider(id="stop-buffer", min=0.0, max=0.5, step=0.05, value=0.1,
                           marks={0: "0", 0.1: "0.1", 0.25: "0.25", 0.5: "0.5"},
                           className="slider-dark", tooltip={"placement": "bottom"}),
            ], title="Entry Settings", item_id="entry"),

            # ── Scheme A Partials ────────────────────────────────────────────
            dbc.AccordionItem([
                html.P("Only applies when Scheme A is selected.", className="hint-text"),
                dbc.Row([
                    dbc.Col([_label("P1 target (R)"),
                             dcc.Slider(id="p1r", min=0.5, max=3.0, step=0.25, value=1.0,
                                        marks={0.5: "0.5R", 1: "1R", 2: "2R", 3: "3R"},
                                        className="slider-dark", tooltip={"placement": "bottom"})]),
                ]),
                html.Div(style={"height": "8px"}),
                dbc.Row([
                    dbc.Col([_label("P2 target (R)"),
                             dcc.Slider(id="p2r", min=1.0, max=5.0, step=0.25, value=2.0,
                                        marks={1: "1R", 2: "2R", 3: "3R", 5: "5R"},
                                        className="slider-dark", tooltip={"placement": "bottom"})]),
                ]),
                html.Div(style={"height": "8px"}),
                _label("Partial Weights  (P1 % / P2 % / Runner %)"),
                dbc.Row([
                    dbc.Col(dbc.Input(id="w-p1", type="number", value=50, min=0, max=100,
                                      className="input-dark", placeholder="P1 %"), width=4),
                    dbc.Col(dbc.Input(id="w-p2", type="number", value=30, min=0, max=100,
                                      className="input-dark", placeholder="P2 %"), width=4),
                    dbc.Col(dbc.Input(id="w-run", type="number", value=20, min=0, max=100,
                                      className="input-dark", placeholder="Run %"), width=4),
                ]),
                html.Div(id="weight-warning", className="hint-text mt-1"),
            ], title="Scheme A Partials", item_id="scheme_a"),

            # ── Risk & Execution ─────────────────────────────────────────────
            dbc.AccordionItem([
                _label("Starting Balance ($)"),
                dbc.Input(id="starting-balance", type="number", value=100000,
                          min=1000, step=1000, className="input-dark mb-2"),

                _label("Position Sizing Mode"),
                dbc.RadioItems(
                    id="sizing-mode",
                    options=[
                        {"label": "Auto — % of balance", "value": "auto"},
                        {"label": "Fixed lot size",      "value": "fixed"},
                    ],
                    value="auto",
                    className="radio-dark mb-2",
                ),

                # Auto mode — risk % slider
                html.Div(id="auto-sizing-panel", children=[
                    _label("Risk per Trade (% of balance)"),
                    dcc.Slider(id="risk-pct", min=0.25, max=5.0, step=0.25, value=1.0,
                               marks={0.25: "0.25%", 1: "1%", 2: "2%", 5: "5%"},
                               className="slider-dark", tooltip={"placement": "bottom"}),
                ]),

                # Fixed mode — lot size input
                html.Div(id="fixed-sizing-panel", style={"display": "none"}, children=[
                    _label("Lot Size (standard lots)"),
                    dbc.Input(id="fixed-lot-size", type="number", value=0.10,
                              min=0.01, step=0.01, className="input-dark"),
                    html.P("Same lot size applied to every trade.", className="hint-text mt-1"),
                ]),

                html.Div(style={"height": "10px"}),
                _label("Spread Multiplier"),
                dcc.Slider(id="spread-mult", min=0.5, max=5.0, step=0.5, value=1.0,
                           marks={0.5: "0.5×", 1: "1×", 2: "2×", 3: "3×", 5: "5×"},
                           className="slider-dark", tooltip={"placement": "bottom"}),
                html.Div(style={"height": "10px"}),

                _label("Stop Slippage (× ATR)"),
                dcc.Slider(id="stop-slip", min=0.0, max=0.5, step=0.05, value=0.0,
                           marks={0: "0", 0.1: "0.1", 0.25: "0.25", 0.5: "0.5"},
                           className="slider-dark", tooltip={"placement": "bottom"}),
            ], title="Risk & Execution", item_id="risk"),

        ], start_collapsed=False, active_item="universe", always_open=True,
           className="accordion-dark"),

        html.Div(style={"height": "16px"}),
        dbc.Button([
            dbc.Spinner(size="sm", id="run-spinner", spinner_style={"display": "none"}),
            html.Span(" RUN BACKTEST", id="btn-label"),
        ], id="btn-run", n_clicks=0, className="run-btn w-100"),
        html.Div(id="run-status", className="run-status"),

        html.Hr(style={"borderColor": "#30363d", "margin": "16px 0 12px"}),
        html.Div("OR IMPORT RESULTS", className="section-header"),
        dcc.Upload(
            id="upload-results",
            children=html.Div([
                html.Span("Drag & drop  ", style={"color": "#8b949e", "fontSize": "12px"}),
                html.A("or browse CSV / Parquet",
                       style={"color": "#58a6ff", "cursor": "pointer", "fontSize": "12px"}),
            ]),
            style={
                "width": "100%",
                "border": "1px dashed #30363d",
                "borderRadius": "6px",
                "textAlign": "center",
                "padding": "12px 8px",
                "backgroundColor": "#21262d",
                "cursor": "pointer",
            },
            multiple=False,
            accept=".csv,.parquet",
        ),
        html.Div(id="upload-status", className="run-status"),

    ], className="sidebar")


# ─────────────────────────────────────────────────────────────────────────────
# Stats row
# ─────────────────────────────────────────────────────────────────────────────

def build_stats_row():
    return dbc.Row([
        dbc.Col(_card("Trades",        "—", C["text"],   "total"), width=2),
        dbc.Col(_card("Win Rate",      "—", C["blue"],   "% winners"), width=2),
        dbc.Col(_card("Avg R / Trade", "—", C["green"],  "expectancy"), width=2),
        dbc.Col(_card("Total R",       "—", C["green"],  "cumulative"), width=2),
        dbc.Col(_card("Profit Factor", "—", C["purple"], "gross W / gross L"), width=2),
        dbc.Col(_card("Max DD",        "—", C["red"],    "peak-to-trough R"), width=2),
    ], id="stats-row", className="stats-row g-2")


# ─────────────────────────────────────────────────────────────────────────────
# Main panel — tabs
# ─────────────────────────────────────────────────────────────────────────────

def build_dollar_stats_row():
    return dbc.Row([
        dbc.Col(_card("Starting Balance", "—", C["muted"],   "$"),         width=2),
        dbc.Col(_card("Net Profit ($)",   "—", C["green"],   "total $"),   width=2),
        dbc.Col(_card("Ending Balance",   "—", C["blue"],    "$"),         width=2),
        dbc.Col(_card("Best Trade ($)",   "—", C["green"],   "single"),    width=2),
        dbc.Col(_card("Worst Trade ($)",  "—", C["red"],     "single"),    width=2),
        dbc.Col(_card("Max DD ($)",       "—", C["red"],     "peak→trough"), width=2),
    ], id="dollar-stats-row", className="stats-row g-2")


def build_main():
    return html.Div([
        build_stats_row(),
        html.Div(style={"height": "6px"}),
        build_dollar_stats_row(),
        html.Div(style={"height": "12px"}),
        dbc.Tabs([
            dbc.Tab(label="Overview", tab_id="tab-overview", children=[
                dbc.Row([
                    dbc.Col(dcc.Graph(id="equity-curve", config={"displayModeBar": False},
                                     style={"height": "340px"}), width=8),
                    dbc.Col(dcc.Graph(id="win-loss-bar", config={"displayModeBar": False},
                                     style={"height": "340px"}), width=4),
                ], className="g-2 mt-2"),
                html.Div(style={"height": "10px"}),
                html.Div([
                    html.Div([
                        _section_header("Trade Log"),
                        dbc.Button(
                            "↓ Export CSV", id="btn-export", size="sm",
                            className="preset-btn",
                            style={"marginBottom": "6px"},
                        ),
                    ], style={"display": "flex", "justifyContent": "space-between",
                              "alignItems": "flex-end"}),
                    dash_table.DataTable(
                        id="trade-table",
                        columns=[
                            {"name": "#",          "id": "idx"},
                            {"name": "Instrument", "id": "instrument"},
                            {"name": "Direction",  "id": "direction"},
                            {"name": "Entry Time", "id": "entry_time"},
                            {"name": "Entry",      "id": "entry_price", "type": "numeric",
                             "format": {"specifier": ".5f"}},
                            {"name": "Stop",       "id": "stop",        "type": "numeric",
                             "format": {"specifier": ".5f"}},
                            {"name": "R Result",   "id": "realized_r",  "type": "numeric",
                             "format": {"specifier": "+.3f"}},
                            {"name": "P&L ($)",    "id": "pnl_usd",     "type": "numeric",
                             "format": {"specifier": "+,.0f"}},
                            {"name": "Lots",       "id": "lot_size",    "type": "numeric",
                             "format": {"specifier": ".2f"}},
                            {"name": "Exit",       "id": "exit_reason"},
                            {"name": "Session",    "id": "session"},
                        ],
                        data=[],
                        style_table={"overflowX": "auto"},
                        style_header={
                            "backgroundColor": C["surface2"],
                            "color": C["muted"],
                            "fontWeight": "600",
                            "borderBottom": f"1px solid {C['border']}",
                            "fontSize": "11px",
                            "textTransform": "uppercase",
                            "letterSpacing": "0.05em",
                        },
                        style_cell={
                            "backgroundColor": C["surface"],
                            "color": C["text"],
                            "border": f"1px solid {C['border']}",
                            "fontSize": "12px",
                            "padding": "6px 10px",
                            "fontFamily": "'JetBrains Mono', 'Fira Code', monospace",
                        },
                        style_data_conditional=[
                            {"if": {"filter_query": "{realized_r} > 0"},
                             "color": C["green"]},
                            {"if": {"filter_query": "{realized_r} < 0"},
                             "color": C["red"]},
                            {"if": {"filter_query": "{pnl_usd} > 0",
                                    "column_id": "pnl_usd"},
                             "color": C["green"]},
                            {"if": {"filter_query": "{pnl_usd} < 0",
                                    "column_id": "pnl_usd"},
                             "color": C["red"]},
                            {"if": {"state": "selected"},
                             "backgroundColor": C["surface2"],
                             "border": f"1px solid {C['blue']}"},
                            {"if": {"row_index": "odd"},
                             "backgroundColor": C["bg"]},
                        ],
                        row_selectable="single",
                        selected_rows=[],
                        page_size=20,
                        page_action="native",
                        sort_action="native",
                        filter_action="native",
                        filter_options={"placeholder_text": "Filter…"},
                    ),
                ], className="table-container"),
            ], className="tab-content"),

            dbc.Tab(label="Analysis", tab_id="tab-analysis", children=[
                dbc.Row([
                    dbc.Col(dcc.Graph(id="session-heatmap", config={"displayModeBar": False},
                                     style={"height": "320px"}), width=6),
                    dbc.Col(dcc.Graph(id="monthly-pnl",     config={"displayModeBar": False},
                                     style={"height": "320px"}), width=6),
                ], className="g-2 mt-2"),
                dbc.Row([
                    dbc.Col(dcc.Graph(id="r-dist",    config={"displayModeBar": False},
                                     style={"height": "300px"}), width=6),
                    dbc.Col(dcc.Graph(id="drawdown",  config={"displayModeBar": False},
                                     style={"height": "300px"}), width=6),
                ], className="g-2 mt-2"),
            ], className="tab-content"),

            dbc.Tab(label="Trade Explorer", tab_id="tab-explorer", children=[
                html.Div([
                    html.P("Click a row in the Trade Log to explore that trade.",
                           className="hint-text mt-3"),
                    dcc.Graph(id="trade-detail", config={"displayModeBar": True},
                              style={"height": "600px"}),
                ], className="p-2"),
            ], className="tab-content"),

            dbc.Tab(label="Playback", tab_id="tab-playback", children=[
                # ── Filter bar ───────────────────────────────────────────────
                dbc.Row([
                    dbc.Col([
                        _label("Entry Type"),
                        dbc.RadioItems(id="pb-type-filter",
                            options=[{"label": "All",      "value": "ALL"},
                                     {"label": "FVG only", "value": "FVG"},
                                     {"label": "OB only",  "value": "OB"}],
                            value="ALL", inline=True, className="radio-dark"),
                    ], width=3),
                    dbc.Col([
                        _label("Instrument"),
                        dcc.Dropdown(id="pb-inst-filter",
                            options=[{"label": "All", "value": "ALL"}] +
                                    [{"label": i, "value": i} for i in INSTRUMENTS],
                            value="ALL", clearable=False, className="dropdown-dark"),
                    ], width=2),
                    dbc.Col([
                        _label("Direction"),
                        dbc.RadioItems(id="pb-dir-filter",
                            options=[{"label": "All",   "value": "ALL"},
                                     {"label": "Long",  "value": "LONG"},
                                     {"label": "Short", "value": "SHORT"}],
                            value="ALL", inline=True, className="radio-dark"),
                    ], width=3),
                    dbc.Col([
                        _label("Result"),
                        dbc.RadioItems(id="pb-result-filter",
                            options=[{"label": "All",   "value": "ALL"},
                                     {"label": "Wins",  "value": "WIN"},
                                     {"label": "Losses","value": "LOSS"}],
                            value="ALL", inline=True, className="radio-dark"),
                    ], width=3),
                    dbc.Col([
                        _label("Context bars"),
                        dcc.Dropdown(id="pb-context",
                            options=[{"label": "48 bars", "value": 48},
                                     {"label": "96 bars", "value": 96},
                                     {"label": "192 bars","value": 192}],
                            value=96, clearable=False, className="dropdown-dark"),
                    ], width=1),
                ], className="g-2 mt-2 align-items-end"),

                html.Div(style={"height": "10px"}),

                # ── Navigation bar ────────────────────────────────────────────
                dbc.Row([
                    dbc.Col(dbc.Button("← Prev", id="pb-prev", n_clicks=0,
                                       size="sm", className="preset-btn"), width="auto"),
                    dbc.Col(html.Div(id="pb-counter",
                                     style={"textAlign": "center", "color": C["muted"],
                                            "fontFamily": "JetBrains Mono, monospace",
                                            "fontSize": "13px", "padding": "4px 0"}),
                            width=True),
                    dbc.Col(dbc.Button("Next →", id="pb-next", n_clicks=0,
                                       size="sm", className="preset-btn"), width="auto"),
                ], className="align-items-center g-2"),

                html.Div(style={"height": "6px"}),
                dcc.Graph(id="pb-chart", config={"displayModeBar": True},
                          style={"height": "520px"}),

                # ── Trade info strip ─────────────────────────────────────────
                html.Div(id="pb-trade-info", className="mt-2"),
            ], className="tab-content"),

            dbc.Tab(label="Comparison", tab_id="tab-compare", children=[
                dbc.Row([
                    dbc.Col(dcc.Graph(id="cmp-equity",   config={"displayModeBar": False},
                                     style={"height": "340px"}), width=12),
                ], className="g-2 mt-2"),
                dbc.Row([
                    dbc.Col(dcc.Graph(id="cmp-avg-r",    config={"displayModeBar": False},
                                     style={"height": "280px"}), width=6),
                    dbc.Col(dcc.Graph(id="cmp-winrate",  config={"displayModeBar": False},
                                     style={"height": "280px"}), width=6),
                ], className="g-2 mt-2"),
            ], className="tab-content"),

        ], id="main-tabs", active_tab="tab-overview", className="tabs-dark"),
    ], className="main-panel")


# ─────────────────────────────────────────────────────────────────────────────
# App layout
# ─────────────────────────────────────────────────────────────────────────────

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    suppress_callback_exceptions=True,
    title="CRT+ICT Backtester",
)
server = app.server

app.layout = html.Div([
    dcc.Store(id="trades-store"),    # List[dict] — all trade records
    dcc.Store(id="params-store"),    # dict — last run params snapshot
    dcc.Store(id="playback-idx", data=0),  # current playback position
    dcc.Download(id="download-csv"),
    html.Div([
        build_sidebar(),
        build_main(),
    ], className="app-container"),
], style={"backgroundColor": C["bg"], "minHeight": "100vh"})


# ─────────────────────────────────────────────────────────────────────────────
# Utility — build summary metrics from trades list
# ─────────────────────────────────────────────────────────────────────────────

def _compute_stats(trades: list[dict]) -> dict:
    if not trades:
        return {}
    df = pd.DataFrame(trades)
    r = df["realized_r"].astype(float)
    wins = r[r > 0]
    losses = r[r < 0]
    gross_w = wins.sum()
    gross_l = abs(losses.sum())
    pf = gross_w / gross_l if gross_l > 0 else float("inf")

    equity = r.cumsum()
    roll_max = equity.cummax()
    dd = equity - roll_max
    max_dd = dd.min()

    return {
        "n":       len(r),
        "wr":      100 * len(wins) / len(r),
        "avg_r":   r.mean(),
        "total_r": r.sum(),
        "pf":      pf,
        "max_dd":  max_dd,
    }


def _equity_fig(trades: list[dict]) -> go.Figure:
    if not trades:
        return _empty_fig("Run a backtest to see the equity curve.")
    df = pd.DataFrame(trades).sort_values("entry_time")
    df["r_cum"] = df.groupby("instrument")["realized_r"].cumsum()
    combined = df.groupby("entry_time")["realized_r"].sum().cumsum().reset_index()
    combined.columns = ["entry_time", "r_cum"]

    fig = go.Figure()
    for inst, grp in df.groupby("instrument"):
        grp = grp.sort_values("entry_time")
        fig.add_trace(go.Scatter(
            x=grp["entry_time"], y=grp["r_cum"],
            mode="lines", name=inst, line=dict(width=1.5),
            opacity=0.7,
        ))
    fig.add_trace(go.Scatter(
        x=combined["entry_time"], y=combined["r_cum"],
        mode="lines", name="Combined",
        line=dict(color=C["blue"], width=2.5),
    ))
    fig.add_hline(y=0, line_color=C["border"], line_dash="dash")
    fig.update_layout(title="Equity Curve (R)", **PLOTLY_TEMPLATE["layout"])
    return fig


def _win_loss_bar(trades: list[dict]) -> go.Figure:
    if not trades:
        return _empty_fig()
    df = pd.DataFrame(trades)
    df["bucket"] = df["realized_r"].apply(
        lambda r: "Win" if r > 0 else ("BE" if r == 0 else "Loss"))
    counts = df.groupby(["instrument", "bucket"]).size().reset_index(name="n")
    color_map = {"Win": C["green"], "Loss": C["red"], "BE": C["orange"]}
    fig = px.bar(counts, x="instrument", y="n", color="bucket",
                 barmode="group", color_discrete_map=color_map)
    fig.update_layout(title="Win / Loss by Instrument",
                      legend_title="", **PLOTLY_TEMPLATE["layout"])
    return fig


def _session_heatmap(trades: list[dict]) -> go.Figure:
    if not trades:
        return _empty_fig()
    df = pd.DataFrame(trades)
    if "session" not in df.columns:
        return _empty_fig("No session data.")
    piv = df.pivot_table(index="session", columns="instrument",
                         values="realized_r", aggfunc="sum").fillna(0)
    fig = go.Figure(go.Heatmap(
        z=piv.values, x=piv.columns.tolist(), y=piv.index.tolist(),
        colorscale=[[0, C["red"]], [0.5, C["surface"]], [1, C["green"]]],
        zmid=0, colorbar=dict(title="R"),
    ))
    fig.update_layout(title="Session P&L Heatmap (R)",
                      **PLOTLY_TEMPLATE["layout"])
    return fig


def _monthly_pnl(trades: list[dict]) -> go.Figure:
    if not trades:
        return _empty_fig()
    df = pd.DataFrame(trades)
    df["month"] = pd.to_datetime(df["entry_time"]).dt.to_period("M").astype(str)
    monthly = df.groupby("month")["realized_r"].sum().reset_index()
    colors = [C["green"] if v >= 0 else C["red"] for v in monthly["realized_r"]]
    fig = go.Figure(go.Bar(
        x=monthly["month"], y=monthly["realized_r"],
        marker_color=colors, name="Monthly R",
    ))
    fig.add_hline(y=0, line_color=C["border"], line_dash="dash")
    fig.update_layout(title="Monthly P&L (R)", **PLOTLY_TEMPLATE["layout"])
    return fig


def _r_distribution(trades: list[dict]) -> go.Figure:
    if not trades:
        return _empty_fig()
    df = pd.DataFrame(trades)
    r = df["realized_r"].astype(float)
    fig = go.Figure(go.Histogram(
        x=r, nbinsx=40,
        marker_color=C["blue"], opacity=0.8,
        marker_line=dict(color=C["border"], width=0.5),
    ))
    fig.add_vline(x=0, line_color=C["red"], line_dash="dash")
    fig.add_vline(x=r.mean(), line_color=C["green"], line_dash="dot",
                  annotation_text=f"Mean {r.mean():+.3f}R",
                  annotation_font_color=C["green"])
    fig.update_layout(title="R Distribution", **PLOTLY_TEMPLATE["layout"])
    return fig


def _drawdown_fig(trades: list[dict]) -> go.Figure:
    if not trades:
        return _empty_fig()
    df = pd.DataFrame(trades).sort_values("entry_time")
    eq = df["realized_r"].cumsum()
    dd = eq - eq.cummax()
    fig = go.Figure(go.Scatter(
        x=df["entry_time"], y=dd,
        fill="tozeroy", mode="lines",
        line=dict(color=C["red"], width=1.5),
        fillcolor="rgba(248,81,73,0.15)",
    ))
    fig.add_hline(y=0, line_color=C["border"], line_dash="dash")
    fig.update_layout(title="Drawdown (R)", **PLOTLY_TEMPLATE["layout"])
    return fig


def _cmp_equity(trades: list[dict]) -> go.Figure:
    if not trades:
        return _empty_fig("Run a backtest with multiple instruments.")
    df = pd.DataFrame(trades).sort_values("entry_time")
    fig = go.Figure()
    for inst, grp in df.groupby("instrument"):
        grp = grp.sort_values("entry_time")
        grp["r_cum"] = grp["realized_r"].cumsum()
        fig.add_trace(go.Scatter(
            x=grp["entry_time"], y=grp["r_cum"],
            mode="lines", name=inst, line=dict(width=2),
        ))
    fig.update_layout(title="Per-Instrument Equity (R)",
                      **PLOTLY_TEMPLATE["layout"])
    return fig


def _cmp_bar(trades: list[dict], metric: str, title: str) -> go.Figure:
    if not trades:
        return _empty_fig()
    df = pd.DataFrame(trades)
    if metric == "avg_r":
        vals = df.groupby("instrument")["realized_r"].mean()
    else:
        r = df.groupby("instrument")["realized_r"]
        vals = r.apply(lambda s: 100 * (s > 0).sum() / len(s))
    colors = [C["green"] if v >= 0 else C["red"] for v in vals]
    fig = go.Figure(go.Bar(x=vals.index.tolist(), y=vals.values,
                            marker_color=colors))
    fig.add_hline(y=0, line_color=C["border"], line_dash="dash")
    fig.update_layout(title=title, **PLOTLY_TEMPLATE["layout"])
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Playback helpers
# ─────────────────────────────────────────────────────────────────────────────

ENTRY_TYPE_COLORS = {"FVG": C["blue"], "OB": C["orange"]}
ENTRY_TYPE_SYMBOLS = {"FVG": "circle", "OB": "square"}


def _apply_pb_filters(trades, type_f, inst_f, dir_f, result_f):
    out = []
    for t in (trades or []):
        if type_f   != "ALL" and t.get("entry_type", "").upper() != type_f:   continue
        if inst_f   != "ALL" and t.get("instrument", "") != inst_f:             continue
        if dir_f    != "ALL" and t.get("direction",  "").upper() != dir_f:     continue
        if result_f == "WIN"  and float(t.get("realized_r", 0)) <= 0:           continue
        if result_f == "LOSS" and float(t.get("realized_r", 0)) >= 0:           continue
        out.append(t)
    return out


def _build_playback_chart(t: dict, tf_label: str, context_bars: int) -> go.Figure:
    """Build an annotated candlestick chart for a single trade."""
    inst     = t.get("instrument", "")
    _, ltf_freq = TF_COMBOS.get(tf_label, ("4h", "15min"))

    try:
        from engine.phase2_engine import load_ltf_source
        ltf = load_ltf_source(inst, ltf_freq, data_path=DATA_PATH)
    except Exception as exc:
        return _empty_fig(f"Cannot load {inst} {ltf_freq}: {exc}")

    entry_ts = pd.Timestamp(t["entry_time"])
    exit_ts  = pd.Timestamp(t.get("exit_time", t["entry_time"]))

    # Window: context_bars before entry, min 24 bars after exit
    freq_map = {"15min": 15, "5min": 5, "1min": 1, "1h": 60, "4h": 240}
    mins     = freq_map.get(ltf_freq, 15)
    pre      = pd.Timedelta(minutes=mins * context_bars)
    post     = pd.Timedelta(minutes=max(mins * 48, (exit_ts - entry_ts).total_seconds() / 60 + mins * 24))

    slc = ltf.loc[(ltf.index >= entry_ts - pre) & (ltf.index <= entry_ts + post)]
    if slc.empty:
        return _empty_fig("No LTF bars in this window.")

    fig = go.Figure()

    # ── Candlesticks ──────────────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=slc.index, open=slc["open"], high=slc["high"],
        low=slc["low"], close=slc["close"],
        increasing_line_color=C["green"], decreasing_line_color=C["red"],
        name="Price", showlegend=False,
    ))

    entry_price = float(t.get("entry_price", 0))
    stop        = float(t.get("stop", 0))
    target      = float(t.get("target", 0))
    r_dist      = float(t.get("r_distance", abs(entry_price - stop)))
    direction   = t.get("direction", "LONG")
    entry_type  = t.get("entry_type", "").upper()
    realized_r  = float(t.get("realized_r", 0))
    exit_reason = t.get("exit_reason", "")
    pnl_usd     = t.get("pnl_usd", None)

    sign = 1 if direction == "LONG" else -1

    # Partial targets (Scheme A defaults)
    p1_price = entry_price + sign * r_dist * 1.0
    p2_price = entry_price + sign * r_dist * 2.0

    # ── Trade duration shading ─────────────────────────────────────────────
    shade_color = "rgba(63,185,80,0.08)" if realized_r >= 0 else "rgba(248,81,73,0.08)"
    fig.add_vrect(x0=str(entry_ts), x1=str(exit_ts),
                  fillcolor=shade_color, opacity=1, layer="below", line_width=0)

    # ── Horizontal levels ─────────────────────────────────────────────────
    x_range = [str(slc.index[0]), str(slc.index[-1])]

    def _hline(price, color, dash, label, side="right"):
        fig.add_shape(type="line", x0=x_range[0], x1=x_range[1],
                      y0=price, y1=price,
                      line=dict(color=color, dash=dash, width=1.2))
        fig.add_annotation(x=x_range[1], y=price, text=f" {label}: {price:.5g}",
                           xanchor="left", showarrow=False,
                           font=dict(color=color, size=10))

    _hline(stop,     C["red"],    "dot",   "SL")
    _hline(p1_price, C["cyan"],   "dash",  "P1 (1R)")
    _hline(p2_price, C["green"],  "dash",  "P2 (2R)")
    if target and abs(target - p2_price) > r_dist * 0.1:
        _hline(target, "#39d353",  "longdash", "Target")

    # ── Entry marker ──────────────────────────────────────────────────────
    mcolor = ENTRY_TYPE_COLORS.get(entry_type, C["purple"])
    msym   = ("triangle-up" if direction == "LONG" else "triangle-down")
    fig.add_trace(go.Scatter(
        x=[str(entry_ts)], y=[entry_price],
        mode="markers",
        marker=dict(symbol=msym, size=16, color=mcolor,
                    line=dict(color="#fff", width=1.5)),
        name=f"{entry_type or 'Entry'} ({direction})",
        showlegend=True,
    ))

    # ── Exit marker ───────────────────────────────────────────────────────
    exit_color = C["green"] if realized_r >= 0 else C["red"]
    exit_price = entry_price + sign * r_dist * realized_r   # approximate
    fig.add_trace(go.Scatter(
        x=[str(exit_ts)], y=[exit_price],
        mode="markers",
        marker=dict(symbol="x", size=12, color=exit_color,
                    line=dict(color="#fff", width=1)),
        name=f"Exit ({exit_reason})",
        showlegend=True,
    ))

    # ── Entry / exit vertical lines ───────────────────────────────────────
    fig.add_vline(x=str(entry_ts), line_color=mcolor,     line_dash="dot", opacity=0.6)
    fig.add_vline(x=str(exit_ts),  line_color=exit_color, line_dash="dot", opacity=0.5)

    # ── Title ─────────────────────────────────────────────────────────────
    r_color  = C["green"] if realized_r >= 0 else C["red"]
    pnl_str  = f" | ${pnl_usd:+,.0f}" if pnl_usd is not None else ""
    type_str = f"<span style='color:{mcolor}'>{entry_type or 'ENTRY'}</span>"
    title    = (f"{inst}  {direction}  {type_str}  |  "
                f"<span style='color:{r_color}'>{realized_r:+.3f}R{pnl_str}</span>  |  "
                f"{exit_reason}  |  {str(entry_ts)[:16]}")

    fig.update_layout(
        title=dict(text=title, font=dict(size=13)),
        xaxis_rangeslider_visible=False,
        **PLOTLY_TEMPLATE["layout"],
    )
    fig.update_layout(legend=dict(orientation="h", y=1.05, x=0,
                                  bgcolor=C["surface2"], bordercolor=C["border"]))
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Callbacks — presets
# ─────────────────────────────────────────────────────────────────────────────

@app.callback(
    Output("inst-checklist", "value"),
    Input("btn-all-inst", "n_clicks"),
    Input("btn-fx-inst",  "n_clicks"),
    prevent_initial_call=True,
)
def preset_instruments(_, __):
    triggered = ctx.triggered_id
    if triggered == "btn-all-inst":
        return INSTRUMENTS
    return ["EURUSD", "GBPUSD", "USDJPY"]


@app.callback(
    Output("session-checklist", "value"),
    Input("btn-go-sess",  "n_clicks"),
    Input("btn-all-sess", "n_clicks"),
    prevent_initial_call=True,
)
def preset_sessions(_, __):
    return GO_SESSION_LIST if ctx.triggered_id == "btn-go-sess" else ALL_SESSIONS


@app.callback(
    Output("weight-warning", "children"),
    Input("w-p1", "value"),
    Input("w-p2", "value"),
    Input("w-run", "value"),
)
def check_weights(p1, p2, run):
    total = (p1 or 0) + (p2 or 0) + (run or 0)
    if total != 100:
        return f"Weights sum to {total}% — must equal 100%."
    return ""


@app.callback(
    Output("auto-sizing-panel",  "style"),
    Output("fixed-sizing-panel", "style"),
    Input("sizing-mode", "value"),
)
def toggle_sizing_mode(mode):
    if mode == "fixed":
        return {"display": "none"}, {"display": "block"}
    return {"display": "block"}, {"display": "none"}


# ─────────────────────────────────────────────────────────────────────────────
# Callback — Import results from uploaded CSV / Parquet
# ─────────────────────────────────────────────────────────────────────────────

@app.callback(
    Output("trades-store", "data",     allow_duplicate=True),
    Output("run-status",   "children", allow_duplicate=True),
    Output("upload-status","children"),
    Input("upload-results", "contents"),
    State("upload-results",   "filename"),
    State("starting-balance", "value"),
    State("risk-pct",         "value"),
    State("sizing-mode",      "value"),
    State("fixed-lot-size",   "value"),
    prevent_initial_call=True,
)
def import_results_cb(contents, filename, starting_balance, risk_pct, sizing_mode, fixed_lot_size):
    if not contents:
        return no_update, no_update, ""

    import base64, io as _io
    _ctype, content_string = contents.split(",", 1)
    decoded = base64.b64decode(content_string)

    try:
        fname = (filename or "").lower()
        if fname.endswith(".parquet"):
            df = pd.read_parquet(_io.BytesIO(decoded))
        else:
            df = pd.read_csv(_io.StringIO(decoded.decode("utf-8")))
    except Exception as exc:
        msg = html.Span(f"Parse error: {exc}", style={"color": C["red"]})
        return no_update, no_update, msg

    # Normalise column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Map common aliases to canonical names
    _aliases = {
        "r_result":       "realized_r",
        "r":              "realized_r",
        "result_r":       "realized_r",
        "entry":          "entry_price",
        "price":          "entry_price",
        "sl":             "stop",
        "tp":             "target",
        "pair":           "instrument",
        "symbol":         "instrument",
        "ticker":         "instrument",
        "side":           "direction",
        "type":           "entry_type",
        "entry_datetime": "entry_time",
        "open_time":      "entry_time",
        "close_time":     "exit_time",
        "time":           "entry_time",
        "date":           "entry_time",
    }
    df = df.rename(columns={k: v for k, v in _aliases.items() if k in df.columns})

    if "realized_r" not in df.columns:
        msg = html.Span("CSV must have a 'realized_r' (or 'r_result') column.",
                        style={"color": C["red"]})
        return no_update, no_update, msg

    if "instrument" not in df.columns:
        df["instrument"] = "UNKNOWN"
    if "entry_time" not in df.columns:
        df["entry_time"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

    # Stringify any datetime columns for JSON serialisation
    for col in df.select_dtypes(include=["datetime64[ns]", "datetimetz",
                                          "datetime64[ms, UTC]"]).columns:
        df[col] = df[col].astype(str)

    all_trades = df.to_dict("records")
    all_trades.sort(key=lambda t: str(t.get("entry_time", "")))

    # Compute / recompute dollar P&L using current sidebar risk settings
    balance     = float(starting_balance or 100_000)
    risk_frac   = float(risk_pct or 1.0) / 100.0
    fixed_lots  = float(fixed_lot_size or 0.10)
    use_fixed   = (sizing_mode == "fixed")

    running_balance = balance
    for t in all_trades:
        inst   = t.get("instrument", "EURUSD")
        r_dist = float(t.get("r_distance", 0) or 0)
        vppu   = VALUE_PER_PRICE_UNIT.get(inst, 100_000.0)
        if vppu is None:
            vppu = 100_000.0 / max(float(t.get("entry_price", 145) or 145), 1)

        if use_fixed:
            lots = fixed_lots
            pnl  = round(float(t["realized_r"]) * lots * r_dist * vppu, 2) if r_dist > 0 else 0.0
        else:
            risk_dollars = running_balance * risk_frac
            pnl  = round(float(t["realized_r"]) * risk_dollars, 2)
            lots = round(risk_dollars / (r_dist * vppu), 2) if (r_dist > 0 and vppu > 0) else 0.0

        t["pnl_usd"]       = pnl
        t["lot_size"]      = lots
        t["balance_after"] = round(running_balance + pnl, 2)
        running_balance    = t["balance_after"]

    all_trades[0]["_starting_balance"] = balance

    run_msg = html.Span([
        html.Span(f"{len(all_trades)} trades imported from ",
                  style={"color": C["muted"]}),
        html.Span(filename or "file", style={"color": C["blue"]}),
    ])
    return all_trades, run_msg, ""


# ─────────────────────────────────────────────────────────────────────────────
# Callback — Run backtest
# ─────────────────────────────────────────────────────────────────────────────

@app.callback(
    Output("trades-store",  "data"),
    Output("params-store",  "data"),
    Output("run-status",    "children"),
    Input("btn-run", "n_clicks"),
    State("inst-checklist",   "value"),
    State("tf-combo",         "value"),
    State("scheme-radio",     "value"),
    State("date-start",       "date"),
    State("date-end",         "date"),
    State("strong-filter",    "value"),
    State("atr-ratio",        "value"),
    State("session-checklist","value"),
    State("entry-pref",       "value"),
    State("entry-window",     "value"),
    State("require-mss",      "value"),
    State("require-pd",       "value"),
    State("stop-buffer",      "value"),
    State("p1r",              "value"),
    State("p2r",              "value"),
    State("w-p1",             "value"),
    State("w-p2",             "value"),
    State("w-run",            "value"),
    State("spread-mult",        "value"),
    State("stop-slip",          "value"),
    State("starting-balance",   "value"),
    State("risk-pct",           "value"),
    State("sizing-mode",        "value"),
    State("fixed-lot-size",     "value"),
    State("news-filter-on",     "value"),
    State("news-types",         "value"),
    State("news-window",        "value"),
    State("custom-news-dates",  "value"),
    prevent_initial_call=True,
)
def run_backtest_cb(
    n_clicks,
    instruments, tf_label, scheme, start_date, end_date,
    strong_filter, atr_ratio, sessions,
    entry_pref, entry_window, require_mss, require_pd, stop_buffer,
    p1r, p2r, w_p1, w_p2, w_run,
    spread_mult, stop_slip,
    starting_balance, risk_pct, sizing_mode, fixed_lot_size,
    news_filter_on, news_types, news_window, custom_news_dates,
):
    if not instruments:
        return no_update, no_update, "Select at least one instrument."

    htf_freq, ltf_freq = TF_COMBOS[tf_label]
    weights = (
        (w_p1 or 50) / 100,
        (w_p2 or 30) / 100,
        (w_run or 20) / 100,
    )
    balance      = float(starting_balance or 100000)
    risk_frac    = float(risk_pct or 1.0) / 100.0
    fixed_lots   = float(fixed_lot_size or 0.10)
    use_fixed    = (sizing_mode == "fixed")

    all_trades: list[dict] = []
    errors: list[str] = []

    for inst in instruments:
        try:
            df_trades, skipped = run_backtest(
                instrument=inst,
                htf_freq=htf_freq,
                ltf_freq=ltf_freq,
                scheme=scheme,
                sessions=sessions if sessions else None,
                strong_filter=strong_filter,
                min_atr_ratio=atr_ratio,
                entry_pref=entry_pref,
                require_mss=require_mss,
                require_pd_filter=require_pd,
                stop_buffer_atr=stop_buffer,
                scheme_a_p1_r=p1r,
                scheme_a_p2_r=p2r,
                scheme_a_weights=weights,
                max_entry_window_ltf=entry_window,
                spread_multiplier=spread_mult,
                stop_slippage_atr=stop_slip,
                start_date=start_date,
                end_date=end_date,
                data_path=DATA_PATH,
            )
            if not df_trades.empty:
                df_trades = df_trades.copy()
                df_trades["instrument"] = inst
                for col in df_trades.select_dtypes(include=["datetimetz", "datetime64[ns]",
                                                             "datetime64[ms, UTC]"]).columns:
                    df_trades[col] = df_trades[col].astype(str)
                all_trades.extend(df_trades.to_dict("records"))
        except FileNotFoundError as exc:
            errors.append(f"{inst}: {exc}")
        except Exception as exc:
            errors.append(f"{inst}: {traceback.format_exc(limit=2)}")

    # Compute compounding dollar P&L + lot size (sorted by entry time)
    if all_trades:
        all_trades.sort(key=lambda t: t.get("entry_time", ""))
        running_balance = balance
        for t in all_trades:
            inst   = t.get("instrument", "EURUSD")
            r_dist = float(t.get("r_distance", 0) or 0)
            vppu   = VALUE_PER_PRICE_UNIT.get(inst, 100_000.0)
            if vppu is None:        # USDJPY — computed from entry price
                vppu = 100_000.0 / max(float(t.get("entry_price", 145)), 1)

            if use_fixed:
                # Fixed lot mode: P&L derived from lot size × stop distance × vppu
                lots = fixed_lots
                pnl  = round(t["realized_r"] * lots * r_dist * vppu, 2) if r_dist > 0 else 0.0
            else:
                # Auto mode: risk % of running balance, lots back-calculated
                risk_dollars = running_balance * risk_frac
                pnl  = round(t["realized_r"] * risk_dollars, 2)
                lots = round(risk_dollars / (r_dist * vppu), 2) if (r_dist > 0 and vppu > 0) else 0.0

            t["pnl_usd"]       = pnl
            t["lot_size"]      = lots
            t["balance_after"] = round(running_balance + pnl, 2)
            running_balance   += pnl

        all_trades[0]["_starting_balance"] = balance

    # ── News filter ───────────────────────────────────────────────────────────
    news_removed = 0
    if news_filter_on and all_trades:
        start_y = int((start_date or "2020-01-01")[:4])
        end_y   = int((end_date   or "2025-12-31")[:4])

        blackout_dates: set[str] = set()
        news_types = news_types or []
        if "nfp"  in news_types: blackout_dates |= nfp_dates(start_y, end_y)
        if "fomc" in news_types: blackout_dates |= FOMC_DATES
        if "cpi"  in news_types: blackout_dates |= CPI_DATES
        if "ecb"  in news_types: blackout_dates |= ECB_DATES

        # Parse custom dates from textarea
        if custom_news_dates:
            for line in custom_news_dates.strip().splitlines():
                d = line.strip()[:10]
                if len(d) == 10:
                    blackout_dates.add(d)

        if blackout_dates:
            # Event times in ET (approximate): NFP/CPI 08:30, FOMC 14:00, ECB 08:15
            EVENT_TIMES = {"nfp": 8.5, "fomc": 14.0, "cpi": 8.5, "ecb": 8.25}
            avg_event_hour = sum(EVENT_TIMES[k] for k in (news_types or []) if k in EVENT_TIMES)
            avg_event_hour = avg_event_hour / max(len([k for k in (news_types or []) if k in EVENT_TIMES]), 1)

            before_count = len(all_trades)
            filtered = []
            for t in all_trades:
                entry_date = str(t.get("entry_time", ""))[:10]
                if entry_date not in blackout_dates:
                    filtered.append(t)
                    continue
                if news_window == "day":
                    pass  # skip whole day — don't append
                else:
                    # Check if entry time is within the window
                    try:
                        entry_ts  = pd.Timestamp(t["entry_time"]).tz_convert("America/New_York")
                        entry_hr  = entry_ts.hour + entry_ts.minute / 60
                        buf       = 4.0 if news_window == "4h" else 2.0
                        if abs(entry_hr - avg_event_hour) > buf:
                            filtered.append(t)  # outside window — keep
                    except Exception:
                        pass  # can't parse → skip to be safe

            news_removed = before_count - len(filtered)
            all_trades   = filtered

            # Recompute dollar P&L / lot sizes on filtered list
            running_balance = balance
            for t in all_trades:
                inst   = t.get("instrument", "EURUSD")
                r_dist = float(t.get("r_distance", 0) or 0)
                vppu   = VALUE_PER_PRICE_UNIT.get(inst, 100_000.0)
                if vppu is None:
                    vppu = 100_000.0 / max(float(t.get("entry_price", 145)), 1)
                if use_fixed:
                    lots = fixed_lots
                    pnl  = round(t["realized_r"] * lots * r_dist * vppu, 2) if r_dist > 0 else 0.0
                else:
                    risk_dollars = running_balance * risk_frac
                    pnl  = round(t["realized_r"] * risk_dollars, 2)
                    lots = round(risk_dollars / (r_dist * vppu), 2) if (r_dist > 0 and vppu > 0) else 0.0
                t["pnl_usd"]       = pnl
                t["lot_size"]      = lots
                t["balance_after"] = round(running_balance + pnl, 2)
                running_balance   += pnl

    params_snap = dict(
        instruments=instruments, tf=tf_label, scheme=scheme,
        start=start_date, end=end_date,
    )

    if not all_trades and errors:
        return None, params_snap, html.Div([
            html.Span("Error: ", style={"color": C["red"]}),
            html.Span("; ".join(errors)),
        ])

    status_parts = [f"{len(all_trades)} trades"]
    if news_removed:
        status_parts.append(f"{news_removed} removed by news filter")
    if errors:
        status_parts.append(f"{len(errors)} error(s): {'; '.join(errors)}")
    status = " | ".join(status_parts)
    return all_trades, params_snap, status


# ─────────────────────────────────────────────────────────────────────────────
# Callback — update stats cards
# ─────────────────────────────────────────────────────────────────────────────

@app.callback(
    Output("stats-row", "children"),
    Input("trades-store", "data"),
)
def update_stats(trades):
    def _c(title, val, col, sub):
        return dbc.Col(_card(title, val, col, sub), width=2)

    if not trades:
        return [
            _c("Trades",        "—", C["text"],   "total"),
            _c("Win Rate",      "—", C["blue"],   "% winners"),
            _c("Avg R / Trade", "—", C["green"],  "expectancy"),
            _c("Total R",       "—", C["green"],  "cumulative"),
            _c("Profit Factor", "—", C["purple"], "gross W / gross L"),
            _c("Max DD",        "—", C["red"],    "peak-to-trough R"),
        ]

    s = _compute_stats(trades)
    return [
        _c("Trades",        str(s["n"]),                      C["text"],   "total"),
        _c("Win Rate",      f'{s["wr"]:.1f}%',                C["blue"],   "% winners"),
        _c("Avg R / Trade", f'{s["avg_r"]:+.3f}R',   C["green"] if s["avg_r"] >= 0 else C["red"],   "expectancy"),
        _c("Total R",       f'{s["total_r"]:+.2f}R', C["green"] if s["total_r"] >= 0 else C["red"], "cumulative"),
        _c("Profit Factor", f'{s["pf"]:.2f}' if s["pf"] != float("inf") else "∞", C["purple"], "gross W / gross L"),
        _c("Max DD",        f'{s["max_dd"]:+.2f}R',           C["red"],    "peak-to-trough R"),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Callback — update dollar stats row
# ─────────────────────────────────────────────────────────────────────────────

@app.callback(
    Output("dollar-stats-row", "children"),
    Input("trades-store", "data"),
)
def update_dollar_stats(trades):
    def _c(title, val, col, sub):
        return dbc.Col(_card(title, val, col, sub), width=2)

    if not trades:
        return [
            _c("Starting Balance", "—", C["muted"], "$"),
            _c("Net Profit ($)",   "—", C["green"], "total $"),
            _c("Ending Balance",   "—", C["blue"],  "$"),
            _c("Best Trade ($)",   "—", C["green"], "single"),
            _c("Worst Trade ($)",  "—", C["red"],   "single"),
            _c("Max DD ($)",       "—", C["red"],   "peak→trough"),
        ]

    df = pd.DataFrame(trades)
    start_bal = float(trades[0].get("_starting_balance", 100000))
    pnl       = df["pnl_usd"].astype(float)
    bal_after = df["balance_after"].astype(float)
    end_bal   = bal_after.iloc[-1]
    net       = end_bal - start_bal
    best      = pnl.max()
    worst     = pnl.min()
    # Max drawdown in dollars from balance_after series
    roll_max  = bal_after.cummax()
    max_dd_usd = (bal_after - roll_max).min()

    def _fmt(v): return f"${v:+,.0f}"

    return [
        _c("Starting Balance", f"${start_bal:,.0f}",   C["muted"],                              "$"),
        _c("Net Profit ($)",   _fmt(net),               C["green"] if net >= 0 else C["red"],   "total $"),
        _c("Ending Balance",   f"${end_bal:,.0f}",      C["blue"],                               "$"),
        _c("Best Trade ($)",   _fmt(best),              C["green"],                              "single"),
        _c("Worst Trade ($)",  _fmt(worst),             C["red"],                                "single"),
        _c("Max DD ($)",       _fmt(max_dd_usd),        C["red"],                                "peak→trough"),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Callback — update overview charts + table
# ─────────────────────────────────────────────────────────────────────────────

@app.callback(
    Output("equity-curve",  "figure"),
    Output("win-loss-bar",  "figure"),
    Output("trade-table",   "data"),
    Input("trades-store",   "data"),
)
def update_overview(trades):
    if not trades:
        return _empty_fig("Run a backtest to see the equity curve."), _empty_fig(), []
    df = pd.DataFrame(trades).sort_values("entry_time").reset_index(drop=True)
    df.insert(0, "idx", df.index + 1)
    table_cols = ["idx", "instrument", "direction", "entry_time",
                  "entry_price", "stop", "realized_r", "pnl_usd", "lot_size", "exit_reason", "session"]
    table_data = df[[c for c in table_cols if c in df.columns]].to_dict("records")
    return _equity_fig(trades), _win_loss_bar(trades), table_data


# ─────────────────────────────────────────────────────────────────────────────
# Callback — export trade results to CSV
# ─────────────────────────────────────────────────────────────────────────────

@app.callback(
    Output("download-csv", "data"),
    Input("btn-export",    "n_clicks"),
    State("trades-store",  "data"),
    State("params-store",  "data"),
    prevent_initial_call=True,
)
def export_csv(n_clicks, trades, params):
    if not trades:
        return no_update
    df = pd.DataFrame(trades).sort_values("entry_time").reset_index(drop=True)
    df.insert(0, "idx", df.index + 1)

    # Drop internal helper columns
    df = df.drop(columns=[c for c in ["_starting_balance"] if c in df.columns])

    # Build a descriptive filename from params
    if params:
        inst  = "_".join(params.get("instruments", []))
        start = (params.get("start") or "")[:10].replace("-", "")
        end   = (params.get("end")   or "")[:10].replace("-", "")
        fname = f"backtest_{inst}_{start}_{end}.csv"
    else:
        fname = "backtest_results.csv"

    return dcc.send_data_frame(df.to_csv, fname, index=False)


# ─────────────────────────────────────────────────────────────────────────────
# Callback — update analysis charts
# ─────────────────────────────────────────────────────────────────────────────

@app.callback(
    Output("session-heatmap", "figure"),
    Output("monthly-pnl",     "figure"),
    Output("r-dist",          "figure"),
    Output("drawdown",        "figure"),
    Input("trades-store",     "data"),
)
def update_analysis(trades):
    return (
        _session_heatmap(trades or []),
        _monthly_pnl(trades or []),
        _r_distribution(trades or []),
        _drawdown_fig(trades or []),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Callback — trade detail (row click → candlestick)
# ─────────────────────────────────────────────────────────────────────────────

@app.callback(
    Output("trade-detail", "figure"),
    Input("trade-table",   "selected_rows"),
    State("trades-store",  "data"),
    State("tf-combo",      "value"),
    prevent_initial_call=True,
)
def trade_detail(selected_rows, trades, tf_label):
    if not selected_rows or not trades:
        return _empty_fig("Click a row in the Trade Log.")

    row_idx = selected_rows[0]
    df = pd.DataFrame(trades).sort_values("entry_time").reset_index(drop=True)
    if row_idx >= len(df):
        return _empty_fig("Row out of range.")

    t = df.iloc[row_idx]
    inst = t.get("instrument", "")
    _, ltf_freq = TF_COMBOS[tf_label]

    try:
        from engine.phase2_engine import load_ltf_source
        ltf = load_ltf_source(inst, ltf_freq, data_path=DATA_PATH)
    except Exception as exc:
        return _empty_fig(f"Could not load {inst} {ltf_freq} data: {exc}")

    entry_ts = pd.Timestamp(t["entry_time"])
    window_start = entry_ts - pd.Timedelta(hours=24)
    window_end   = entry_ts + pd.Timedelta(hours=48)
    slice_ = ltf.loc[(ltf.index >= window_start) & (ltf.index <= window_end)]

    if slice_.empty:
        return _empty_fig("No LTF bars in trade window.")

    fig = go.Figure(go.Candlestick(
        x=slice_.index,
        open=slice_["open"], high=slice_["high"],
        low=slice_["low"],   close=slice_["close"],
        increasing_line_color=C["green"],
        decreasing_line_color=C["red"],
        name="Price",
    ))

    ep   = float(t.get("entry_price", 0))
    stop = float(t.get("stop", 0))
    r_res = float(t.get("realized_r", 0))
    r_dist = abs(ep - stop)
    direction = t.get("direction", "LONG")
    target = ep + r_dist * 3 * (1 if direction == "LONG" else -1)

    fig.add_hline(y=ep,   line_color=C["blue"],   line_dash="dash",
                  annotation_text="Entry",  annotation_font_color=C["blue"])
    fig.add_hline(y=stop, line_color=C["red"],    line_dash="dash",
                  annotation_text="Stop",   annotation_font_color=C["red"])
    fig.add_hline(y=target, line_color=C["green"], line_dash="dot",
                  annotation_text="Target", annotation_font_color=C["green"])
    fig.add_vline(x=str(entry_ts), line_color=C["orange"], line_dash="dot", opacity=0.6)

    r_color = C["green"] if r_res >= 0 else C["red"]
    title = (f"{inst} {direction} | Entry {ep:.5f} | Stop {stop:.5f} | "
             f"R = <span style='color:{r_color}'>{r_res:+.3f}</span>")
    fig.update_layout(
        title=dict(text=title, font=dict(size=13)),
        xaxis_rangeslider_visible=False,
        **PLOTLY_TEMPLATE["layout"],
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Callback — comparison charts
# ─────────────────────────────────────────────────────────────────────────────

@app.callback(
    Output("cmp-equity",  "figure"),
    Output("cmp-avg-r",   "figure"),
    Output("cmp-winrate", "figure"),
    Input("trades-store", "data"),
)
def update_comparison(trades):
    return (
        _cmp_equity(trades or []),
        _cmp_bar(trades or [], "avg_r",  "Avg R / Trade by Instrument"),
        _cmp_bar(trades or [], "winrate","Win Rate (%) by Instrument"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Callbacks — Playback tab
# ─────────────────────────────────────────────────────────────────────────────

@app.callback(
    Output("playback-idx", "data"),
    Input("pb-prev",      "n_clicks"),
    Input("pb-next",      "n_clicks"),
    Input("trades-store", "data"),          # reset to 0 on new backtest
    State("playback-idx",     "data"),
    State("pb-type-filter",   "value"),
    State("pb-inst-filter",   "value"),
    State("pb-dir-filter",    "value"),
    State("pb-result-filter", "value"),
    State("trades-store",     "data"),
    prevent_initial_call=True,
)
def update_pb_index(prev_clicks, next_clicks, _trades_trigger,
                    current_idx, type_f, inst_f, dir_f, result_f, trades):
    triggered = ctx.triggered_id
    if triggered == "trades-store":
        return 0
    filtered = _apply_pb_filters(trades, type_f, inst_f, dir_f, result_f)
    n = len(filtered)
    if n == 0:
        return 0
    if triggered == "pb-prev":
        return max(0, (current_idx or 0) - 1)
    if triggered == "pb-next":
        return min(n - 1, (current_idx or 0) + 1)
    return current_idx or 0


@app.callback(
    Output("pb-chart",      "figure"),
    Output("pb-counter",    "children"),
    Output("pb-trade-info", "children"),
    Input("playback-idx",     "data"),
    Input("pb-type-filter",   "value"),
    Input("pb-inst-filter",   "value"),
    Input("pb-dir-filter",    "value"),
    Input("pb-result-filter", "value"),
    Input("pb-context",       "value"),
    State("trades-store",     "data"),
    State("tf-combo",         "value"),
    prevent_initial_call=True,
)
def update_pb_chart(idx, type_f, inst_f, dir_f, result_f, context_bars, trades, tf_label):
    filtered = _apply_pb_filters(trades, type_f or "ALL", inst_f or "ALL",
                                 dir_f or "ALL", result_f or "ALL")
    n = len(filtered)

    if n == 0:
        return _empty_fig("No trades match the current filters."), "No trades", html.Div()

    idx = min(max(idx or 0, 0), n - 1)
    t   = filtered[idx]

    # ── Counter ───────────────────────────────────────────────────────────────
    entry_type  = t.get("entry_type", "?").upper()
    type_color  = ENTRY_TYPE_COLORS.get(entry_type, C["purple"])
    realized_r  = float(t.get("realized_r", 0))
    r_color     = C["green"] if realized_r >= 0 else C["red"]
    counter = html.Span([
        f"Trade {idx + 1} / {n}  —  ",
        html.Span(t.get("instrument",""), style={"color": C["blue"]}),
        "  ",
        html.Span(t.get("direction",""), style={"color": C["muted"]}),
        "  ",
        html.Span(entry_type, style={"color": type_color, "fontWeight": "700"}),
        "  ",
        html.Span(f"{realized_r:+.3f}R", style={"color": r_color, "fontWeight": "700"}),
    ], style={"fontFamily": "JetBrains Mono, monospace", "fontSize": "13px"})

    # ── Chart ─────────────────────────────────────────────────────────────────
    fig = _build_playback_chart(t, tf_label or "H4 → M15", context_bars or 96)

    # ── Trade info strip ──────────────────────────────────────────────────────
    pnl_usd  = t.get("pnl_usd")
    lot_size = t.get("lot_size")
    fields   = [
        ("Instrument",  t.get("instrument", "—"),               C["blue"]),
        ("Direction",   t.get("direction",  "—"),               C["text"]),
        ("Entry Type",  entry_type or "—",                      type_color),
        ("Entry",       f"{float(t.get('entry_price',0)):.5g}", C["text"]),
        ("Stop",        f"{float(t.get('stop',0)):.5g}",        C["red"]),
        ("R Result",    f"{realized_r:+.3f}R",                  r_color),
        ("P&L ($)",     f"${pnl_usd:+,.0f}" if pnl_usd else "—", r_color),
        ("Lots",        f"{lot_size:.2f}" if lot_size else "—", C["muted"]),
        ("Exit",        t.get("exit_reason","—"),               C["muted"]),
        ("Session",     t.get("session","—"),                   C["muted"]),
        ("Date",        str(t.get("entry_time",""))[:16],       C["muted"]),
    ]
    info_cards = dbc.Row([
        dbc.Col(html.Div([
            html.Div(label, style={"fontSize": "9px", "color": C["muted"],
                                   "textTransform": "uppercase", "letterSpacing": "0.08em"}),
            html.Div(val,   style={"fontSize": "13px", "color": color,
                                   "fontFamily": "JetBrains Mono, monospace",
                                   "fontWeight": "600"}),
        ], style={"background": C["surface2"], "border": f"1px solid {C['border']}",
                  "borderRadius": "6px", "padding": "6px 10px"}),
        width="auto")
        for label, val, color in fields
    ], className="g-2 flex-wrap")

    return fig, counter, info_cards


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=8050)
