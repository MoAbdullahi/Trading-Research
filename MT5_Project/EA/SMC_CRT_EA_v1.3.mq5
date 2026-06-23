//+------------------------------------------------------------------+
//|                                              SMC_CRT_EA_v1.3.mq5 |
//|                  CRT (Candle Range Theory) + ICT PD Array EA     |
//|                          Designed for FTMO via MetaTrader 5      |
//|                                                                  |
//|  v1.3 changes vs v1.2:                                           |
//|    ADD: MODE_H1_M5 — H1 HTF + M5 LTF (validated OOS 78%+ WR)   |
//|    ADD: OB_ONLY / FVG_ONLY entry modes — no fallback to other PD |
//|    ADD: RISK_FIXED mode — risks % of a fixed reference balance   |
//|      (InpFixedRiskBalance) so dollar risk stays constant.        |
//|      FTMO-safe: prevents compounding past the challenge risk cap  |
//|    ADD: InpSessionMask — 8-bit bitmask to enable/disable any     |
//|      combination of the 8 ICT kill-zone / session windows.       |
//|      Default 0xFF = all 8 sessions active (matches validation).  |
//|    All v1.2 fixes retained (FVG backward search, bid-extreme     |
//|      partials, stops-level validation, spread guard).            |
//+-----------------------------------------------------------------+
#property copyright "SMC CRT Research"
#property version   "1.30"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\SymbolInfo.mqh>

//+------------------------------------------------------------------+
//| Session bitmask constants (for InpSessionMask)                   |
//+------------------------------------------------------------------+
#define SESSION_ASIAN_KZ      1    // bit 0  20:00-22:00 NY
#define SESSION_ASIAN         2    // bit 1  22:00-02:00 NY
#define SESSION_LONDON_KZ     4    // bit 2  02:00-05:00 NY
#define SESSION_LONDON        8    // bit 3  05:00-07:00 NY
#define SESSION_NY_AM_KZ     16    // bit 4  07:00-10:00 NY
#define SESSION_LONDON_CLOSE 32    // bit 5  10:00-12:00 NY
#define SESSION_NY_PM        64    // bit 6  12:00-16:00 NY
#define SESSION_OFF_HOURS   128    // bit 7  16:00-20:00 NY

//+------------------------------------------------------------------+
//| Enums                                                            |
//+------------------------------------------------------------------+
enum ENUM_EA_MODE
  {
   MODE_H4_M15 = 0,   // H4 HTF + M15 LTF (original)
   MODE_H4_M5  = 1,   // H4 HTF + M5  LTF
   MODE_H1_M5  = 2,   // H1 HTF + M5  LTF (NEW - highest-performing)
  };

enum ENUM_ENTRY_PREFERENCE
  {
   PREFER_OB  = 0,    // OB primary, FVG fallback
   PREFER_FVG = 1,    // FVG primary, OB fallback
   OB_ONLY    = 2,    // OB only - no FVG fallback (validated OOS)
   FVG_ONLY   = 3,    // FVG only - no OB fallback
  };

enum ENUM_RISK_MODE
  {
   RISK_FIXED       = 0,   // % of InpFixedRiskBalance (FTMO-safe, constant $-risk)
   RISK_COMPOUNDING = 1,   // % of current equity (aggressive compounding)
  };

enum ENUM_NEWS_IMPACT
  {
   IMPACT_HIGH_ONLY   = 0,
   IMPACT_MED_AND_UP  = 1,
  };

enum ENUM_TRADE_STATE
  {
   STATE_IDLE              = 0,
   STATE_TRIGGER_DETECTED  = 1,
   STATE_WAITING_ENTRY     = 2,
   STATE_IN_POSITION       = 3,
   STATE_HALTED            = 99,
  };

//+------------------------------------------------------------------+
//| Inputs                                                           |
//+------------------------------------------------------------------+
input group "=== Strategy Mode ==="
input ENUM_EA_MODE          InpMode        = MODE_H1_M5;   // Timeframe pair (H1+M5 recommended)
input ENUM_ENTRY_PREFERENCE InpEntryPref   = OB_ONLY;      // Entry type (OB_ONLY validated OOS)

input group "=== Risk & Position Sizing ==="
input ENUM_RISK_MODE InpRiskMode           = RISK_FIXED;        // RISK_FIXED = FTMO-safe
input double         InpRiskPercent        = 0.5;               // % risk per trade
input double         InpFixedRiskBalance   = 100000.0;          // Reference balance for RISK_FIXED
input double         InpMaxLotsPerTrade    = 5.0;               // FTMO per-trade lot cap
input double         InpStopBufferATR      = 0.1;
input int            InpMagicNumber        = 202613;

input group "=== Session Filter ==="
input bool InpEnableSessionFilter          = true;
input int  InpSessionMask                  = 0xFF;   // 0xFF=all 8 sessions. See bitmask key in header.
//   bit0=AsianKZ(20-22) bit1=Asian(22-02) bit2=LondonKZ(02-05) bit3=London(05-07)
//   bit4=NYAM_KZ(07-10) bit5=LondonClose(10-12) bit6=NYPM(12-16) bit7=OffHours(16-20)

input group "=== Filters ==="
input bool         InpRequireStrongFilter  = true;
input bool         InpEnableNewsFilter     = true;
input ENUM_NEWS_IMPACT InpNewsImpact       = IMPACT_HIGH_ONLY;
input int          InpNewsBlackoutBefore   = 30;
input int          InpNewsBlackoutAfter    = 30;
input double       InpMaxSpreadMultiplier  = 3.0;

input group "=== FTMO Compliance ==="
input double       InpMaxDailyLossPct      = 4.0;
input double       InpHardKillDailyPct     = 4.5;
input bool         InpEnableFridayClose    = true;
input int          InpFridayCloseHourNY    = 20;

input group "=== Trade Management ==="
input int          InpMaxHoldHours         = 48;
input int          InpEntryWindowHours     = 3;
input int          InpCooldownMinutes      = 30;

input group "=== Diagnostics ==="
input bool         InpEnableLogging        = true;
input bool         InpVerboseLog           = true;
input bool         InpDrawLevelsOnChart    = true;

//+------------------------------------------------------------------+
//| Globals                                                          |
//+------------------------------------------------------------------+
CTrade         Trade;
CPositionInfo  Position;
CSymbolInfo    SymInfo;

ENUM_TIMEFRAMES g_HTF;
ENUM_TIMEFRAMES g_LTF;

datetime g_LastHTFBarTime      = 0;
datetime g_DayStartTime        = 0;
double   g_DayStartEquity      = 0;
datetime g_LastCalendarRefresh = 0;
datetime g_CooldownUntil       = 0;
datetime g_LastEntryAttempt    = 0;
double   g_TypicalSpread       = 0;

ENUM_TRADE_STATE g_State = STATE_IDLE;

struct SetupContext
  {
   datetime trigger_time;
   bool     is_bear;
   double   prev_high;
   double   prev_low;
   double   prev_mid;
   double   sweep_extreme;
   double   target;
   double   r_distance_planned;
   datetime expires_at;
   double   atr_ltf;
  };
SetupContext g_Setup;

//+------------------------------------------------------------------+
//| OnInit                                                           |
//+------------------------------------------------------------------+
int OnInit()
  {
   switch(InpMode)
     {
      case MODE_H4_M15: g_HTF = PERIOD_H4; g_LTF = PERIOD_M15; break;
      case MODE_H4_M5:  g_HTF = PERIOD_H4; g_LTF = PERIOD_M5;  break;
      case MODE_H1_M5:  g_HTF = PERIOD_H1; g_LTF = PERIOD_M5;  break;
      default: Print("ERROR: invalid mode"); return INIT_FAILED;
     }

   Trade.SetExpertMagicNumber(InpMagicNumber);
   Trade.SetDeviationInPoints(20);
   Trade.SetTypeFillingBySymbol(_Symbol);
   SymInfo.Name(_Symbol);

   g_DayStartTime   = GetDayStart();
   g_DayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);

   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   long spread_pts = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   g_TypicalSpread = spread_pts * point;
   if(g_TypicalSpread <= 0) g_TypicalSpread = 0.0001;

   if(HasOpenPosition())
     {
      g_State = STATE_IN_POSITION;
      LogInfo("Restored: open position found, resuming management");
     }
   else g_State = STATE_IDLE;

   string entry_str = "";
   switch(InpEntryPref)
     {
      case PREFER_OB:  entry_str = "PREFER_OB (OB->FVG fallback)";  break;
      case PREFER_FVG: entry_str = "PREFER_FVG (FVG->OB fallback)"; break;
      case OB_ONLY:    entry_str = "OB_ONLY (no fallback)";         break;
      case FVG_ONLY:   entry_str = "FVG_ONLY (no fallback)";        break;
     }
   string risk_str = (InpRiskMode == RISK_FIXED)
                     ? StringFormat("FIXED %.2f%% of %.0f = $%.0f/trade",
                                    InpRiskPercent, InpFixedRiskBalance,
                                    InpFixedRiskBalance * InpRiskPercent / 100.0)
                     : StringFormat("COMPOUNDING %.2f%% of equity", InpRiskPercent);

   LogInfo(StringFormat("EA v1.3 init | mode=%s HTF=%s LTF=%s magic=%d",
                        EnumToString(InpMode), EnumToString(g_HTF),
                        EnumToString(g_LTF), InpMagicNumber));
   LogInfo(StringFormat("  entry=%s | risk=%s", entry_str, risk_str));
   LogInfo(StringFormat("  session_mask=0x%X(%d) spread_base=%.5f stops_level=%d max_lots=%.2f",
                        InpSessionMask, InpSessionMask, g_TypicalSpread,
                        (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL),
                        InpMaxLotsPerTrade));
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
//| OnDeinit                                                         |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   LogInfo(StringFormat("EA stopping reason=%d", reason));
   ClearChartObjects();
  }

//+------------------------------------------------------------------+
//| OnTick                                                           |
//+------------------------------------------------------------------+
void OnTick()
  {
   SymInfo.RefreshRates();

   datetime day_now = GetDayStart();
   if(day_now != g_DayStartTime)
     {
      g_DayStartTime   = day_now;
      g_DayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      LogInfo(StringFormat("Day rollover. Day start equity = %.2f", g_DayStartEquity));
     }

   double daily_loss_pct = ComputeDailyLossPct();
   if(daily_loss_pct >= InpHardKillDailyPct)
     {
      LogWarning(StringFormat("HARD KILL: daily loss %.2f%%.", daily_loss_pct));
      CloseAllOurPositions("hard_kill");
      g_State = STATE_HALTED;
      return;
     }
   if(daily_loss_pct >= InpMaxDailyLossPct && g_State != STATE_IN_POSITION)
     {
      if(g_State != STATE_HALTED)
        {
         LogWarning(StringFormat("SOFT HALT: daily loss %.2f%%.", daily_loss_pct));
         g_State = STATE_HALTED;
        }
     }

   if(InpEnableFridayClose && IsFridayCloseTime())
     {
      if(HasOpenPosition())
        {
         LogInfo("Friday close trigger - closing position.");
         CloseAllOurPositions("friday_close");
        }
      return;
     }

   if(HasOpenPosition())
     {
      g_State = STATE_IN_POSITION;
      ManageOpenPosition();
      return;
     }
   else if(g_State == STATE_IN_POSITION)
     {
      g_CooldownUntil = TimeCurrent() + InpCooldownMinutes * 60;
      g_State = STATE_IDLE;
      ClearChartObjects();
     }

   if(g_State == STATE_HALTED) return;
   if(TimeCurrent() < g_CooldownUntil) return;

   if(g_State == STATE_WAITING_ENTRY && TimeCurrent() > g_Setup.expires_at)
     {
      LogInfo("Entry window expired. Cancelling pending orders.");
      CancelAllOurPendingOrders();
      g_State = STATE_IDLE;
      ClearChartObjects();
     }

   if(g_State == STATE_TRIGGER_DETECTED)
     {
      if(TimeCurrent() > g_Setup.expires_at)
        {
         LogInfo("Entry window expired without LTF setup.");
         g_State = STATE_IDLE;
         ClearChartObjects();
        }
      else if(TimeCurrent() - g_LastEntryAttempt >= 15)
        {
         g_LastEntryAttempt = TimeCurrent();
         TryPlaceEntries();
        }
     }

   datetime current_htf_bar = iTime(_Symbol, g_HTF, 1);
   if(current_htf_bar > g_LastHTFBarTime)
     {
      g_LastHTFBarTime = current_htf_bar;
      OnNewHTFBarClose();
     }
  }

//+------------------------------------------------------------------+
//| OnNewHTFBarClose                                                 |
//+------------------------------------------------------------------+
void OnNewHTFBarClose()
  {
   if(g_State != STATE_IDLE) return;

   double prev_h      = iHigh(_Symbol, g_HTF, 2);
   double prev_l      = iLow(_Symbol, g_HTF, 2);
   double sweep_high  = iHigh(_Symbol, g_HTF, 1);
   double sweep_low   = iLow(_Symbol, g_HTF, 1);
   double sweep_close = iClose(_Symbol, g_HTF, 1);
   datetime sweep_time= iTime(_Symbol, g_HTF, 1);

   bool swept_high = sweep_high > prev_h;
   bool swept_low  = sweep_low  < prev_l;

   if(InpVerboseLog)
      LogInfo(StringFormat("HTF close @ %s: prev=[%.5f,%.5f] sweep=[%.5f,%.5f] close=%.5f sweepHi=%s sweepLo=%s",
                           TimeToString(sweep_time, TIME_DATE|TIME_MINUTES),
                           prev_l, prev_h, sweep_low, sweep_high, sweep_close,
                           swept_high ? "Y":"n", swept_low ? "Y":"n"));

   if(swept_high && swept_low)  { if(InpVerboseLog) LogInfo("  Rejected: both-side sweep"); return; }
   if(!swept_high && !swept_low){ if(InpVerboseLog) LogInfo("  Rejected: no sweep"); return; }

   double prev_mid = (prev_h + prev_l) / 2.0;
   bool is_bear, valid_strong;
   if(swept_high)
     { is_bear = true;  valid_strong = (sweep_close <= prev_mid); }
   else
     { is_bear = false; valid_strong = (sweep_close >= prev_mid); }

   if(InpRequireStrongFilter && !valid_strong)
     {
      if(InpVerboseLog)
         LogInfo(StringFormat("  Rejected: not strong (close=%.5f vs mid=%.5f, %s)",
                              sweep_close, prev_mid, is_bear ? "BEAR":"BULL"));
      return;
     }

   if(InpEnableSessionFilter && !IsGoSession(sweep_time))
     {
      if(InpVerboseLog)
         LogInfo(StringFormat("  Rejected: not in enabled session (NY hour=%d mask=0x%X)",
                              NYHour(sweep_time), InpSessionMask));
      return;
     }

   if(InpEnableNewsFilter && IsNewsBlackout())
     { if(InpVerboseLog) LogInfo("  Rejected: news blackout"); return; }

   if(IsSpreadAbnormal())
     { if(InpVerboseLog) LogInfo("  Rejected: spread abnormal"); return; }

   g_Setup.trigger_time  = sweep_time;
   g_Setup.is_bear       = is_bear;
   g_Setup.prev_high     = prev_h;
   g_Setup.prev_low      = prev_l;
   g_Setup.prev_mid      = prev_mid;
   g_Setup.sweep_extreme = is_bear ? sweep_high : sweep_low;
   g_Setup.target        = is_bear ? prev_l : prev_h;
   g_Setup.expires_at    = TimeCurrent() + InpEntryWindowHours * 3600;
   g_Setup.atr_ltf       = ComputeATR(g_LTF, 14, 1);

   g_State = STATE_TRIGGER_DETECTED;
   g_LastEntryAttempt = 0;

   LogInfo(StringFormat("CRT trigger ACCEPTED: %s %s target=%.5f mid=%.5f atr_ltf=%.5f",
                        TimeToString(sweep_time, TIME_DATE|TIME_MINUTES),
                        is_bear ? "BEAR":"BULL",
                        g_Setup.target, prev_mid, g_Setup.atr_ltf));
  }

//+------------------------------------------------------------------+
//| TryPlaceEntries — strict OB_ONLY / FVG_ONLY support             |
//+------------------------------------------------------------------+
void TryPlaceEntries()
  {
   datetime htf_close = g_Setup.trigger_time + PeriodSeconds(g_HTF);
   int bars_per_hour  = (g_LTF == PERIOD_M5) ? 12 : 4;
   int max_bars       = InpEntryWindowHours * bars_per_hour;

   MqlRates rates[];
   ArraySetAsSeries(rates, false);

   int copied = CopyRates(_Symbol, g_LTF, htf_close, TimeCurrent(), rates);
   if(copied < 5)
     {
      if(InpVerboseLog) LogInfo(StringFormat("    LTF bars insufficient (%d); will retry.", copied));
      return;
     }

   int n = MathMin(copied, max_bars + 5);

   double highs[], lows[], opens[], closes[];
   ArrayResize(highs, n); ArrayResize(lows, n);
   ArrayResize(opens, n); ArrayResize(closes, n);
   for(int i = 0; i < n; i++)
     {
      highs[i]  = rates[i].high;
      lows[i]   = rates[i].low;
      opens[i]  = rates[i].open;
      closes[i] = rates[i].close;
     }

   int mss_idx = FindMSS(highs, lows, closes, n, g_Setup.is_bear);
   if(mss_idx < 0)
     {
      if(InpVerboseLog) LogInfo("    No MSS yet on LTF; will retry.");
      return;
     }
   if(InpVerboseLog) LogInfo(StringFormat("    MSS at LTF bar %d", mss_idx));

   double ob_level  = FindOB(highs, lows, opens, closes, mss_idx, g_Setup.is_bear, g_Setup.prev_mid);
   double fvg_level = FindFVG(highs, lows, n, mss_idx, g_Setup.is_bear, g_Setup.prev_mid);

   double entry_level = EMPTY_VALUE;
   string entry_type  = "";

   switch(InpEntryPref)
     {
      case OB_ONLY:
         if(ob_level != EMPTY_VALUE) { entry_level = ob_level;  entry_type = "OB"; }
         break;
      case FVG_ONLY:
         if(fvg_level != EMPTY_VALUE){ entry_level = fvg_level; entry_type = "FVG"; }
         break;
      case PREFER_OB:
         if(ob_level != EMPTY_VALUE)       { entry_level = ob_level;  entry_type = "OB"; }
         else if(fvg_level != EMPTY_VALUE) { entry_level = fvg_level; entry_type = "FVG"; }
         break;
      case PREFER_FVG:
         if(fvg_level != EMPTY_VALUE)      { entry_level = fvg_level; entry_type = "FVG"; }
         else if(ob_level != EMPTY_VALUE)  { entry_level = ob_level;  entry_type = "OB"; }
         break;
     }

   if(InpVerboseLog)
     {
      string ob_s  = ob_level  == EMPTY_VALUE ? "none" : DoubleToString(ob_level,  _Digits);
      string fvg_s = fvg_level == EMPTY_VALUE ? "none" : DoubleToString(fvg_level, _Digits);
      LogInfo(StringFormat("    OB=%s FVG=%s -> picked %s",
                           ob_s, fvg_s, entry_type == "" ? "NONE" : entry_type));
     }

   if(entry_level == EMPTY_VALUE)
     {
      if(InpVerboseLog) LogInfo("    No valid PD-passing entry; will retry.");
      return;
     }

   double buffer = InpStopBufferATR * g_Setup.atr_ltf;
   double stop   = g_Setup.is_bear ? g_Setup.sweep_extreme + buffer
                                   : g_Setup.sweep_extreme - buffer;

   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   long stops_level_pts = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double min_stop_dist = (stops_level_pts + 5) * point;

   double current_dist = MathAbs(stop - entry_level);
   if(current_dist < min_stop_dist)
     {
      double old_stop = stop;
      stop = g_Setup.is_bear ? entry_level + min_stop_dist : entry_level - min_stop_dist;
      if(InpVerboseLog)
         LogInfo(StringFormat("    Stop widened: %.5f -> %.5f (stops_level=%d pts)",
                              old_stop, stop, (int)stops_level_pts));
     }

   if(PlaceLimitOrder(entry_level, stop, entry_type))
     {
      g_State = STATE_WAITING_ENTRY;
      if(InpDrawLevelsOnChart) DrawSetupOnChart(stop);
     }
  }

//+------------------------------------------------------------------+
//| FindMSS                                                          |
//+------------------------------------------------------------------+
int FindMSS(const double &highs[], const double &lows[], const double &closes[],
            int n, bool is_bear)
  {
   if(n < 5) return -1;
   if(is_bear)
     {
      double ref_low = lows[0];
      for(int i = 1; i <= 3; i++) ref_low = MathMin(ref_low, lows[i]);
      for(int i = 4; i < n; i++)
        { if(closes[i] < ref_low) return i; ref_low = MathMin(ref_low, lows[i]); }
     }
   else
     {
      double ref_high = highs[0];
      for(int i = 1; i <= 3; i++) ref_high = MathMax(ref_high, highs[i]);
      for(int i = 4; i < n; i++)
        { if(closes[i] > ref_high) return i; ref_high = MathMax(ref_high, highs[i]); }
     }
   return -1;
  }

//+------------------------------------------------------------------+
//| FindFVG — backward search, latest PD-valid (v1.2 FIX 1)        |
//+------------------------------------------------------------------+
double FindFVG(const double &highs[], const double &lows[],
               int n, int mss_idx, bool is_bear, double prev_mid)
  {
   for(int j = mss_idx; j >= 2 && j < n; j--)
     {
      double level = EMPTY_VALUE;
      if(is_bear)
        { if(lows[j-2] > highs[j]) level = (lows[j-2] + highs[j]) / 2.0; }
      else
        { if(highs[j-2] < lows[j]) level = (highs[j-2] + lows[j]) / 2.0; }
      if(level == EMPTY_VALUE) continue;
      bool pd_ok = is_bear ? (level >= prev_mid) : (level <= prev_mid);
      if(pd_ok) return level;
     }
   return EMPTY_VALUE;
  }

//+------------------------------------------------------------------+
//| FindOB                                                           |
//+------------------------------------------------------------------+
double FindOB(const double &highs[], const double &lows[],
              const double &opens[], const double &closes[],
              int mss_idx, bool is_bear, double prev_mid)
  {
   for(int j = mss_idx - 1; j >= 0; j--)
     {
      bool is_bull_candle = closes[j] > opens[j];
      double level = EMPTY_VALUE;
      if(is_bear && is_bull_candle)       level = MathMax(opens[j], closes[j]);
      else if(!is_bear && !is_bull_candle) level = MathMin(opens[j], closes[j]);
      if(level == EMPTY_VALUE) continue;
      bool pd_ok = is_bear ? (level >= prev_mid) : (level <= prev_mid);
      if(pd_ok) return level;
     }
   return EMPTY_VALUE;
  }

//+------------------------------------------------------------------+
//| PlaceLimitOrder                                                  |
//+------------------------------------------------------------------+
bool PlaceLimitOrder(double level, double stop, string label)
  {
   double r_distance = MathAbs(level - stop);
   if(r_distance <= 0) return false;

   double lot = ComputeLotSize(r_distance);
   if(lot <= 0)
     {
      if(InpVerboseLog) LogWarning(StringFormat("  %s: lot size 0", label));
      return false;
     }

   double tp = g_Setup.target;
   string comment = StringFormat("SMCCRT|%s|%s|m=%.5f|t=%.5f",
                                 label, g_Setup.is_bear ? "B":"L",
                                 g_Setup.prev_mid, g_Setup.target);

   bool ok = false;
   if(g_Setup.is_bear) ok = Trade.SellLimit(lot, level, _Symbol, stop, tp, ORDER_TIME_GTC, 0, comment);
   else                ok = Trade.BuyLimit (lot, level, _Symbol, stop, tp, ORDER_TIME_GTC, 0, comment);

   if(ok)
     {
      LogInfo(StringFormat("  Pending %s %s: lot=%.2f @%.5f stop=%.5f tp=%.5f R=%.5f",
                           label, g_Setup.is_bear ? "SELL":"BUY",
                           lot, level, stop, tp, r_distance));
      g_Setup.r_distance_planned = r_distance;
     }
   else
      LogWarning(StringFormat("  %s order failed: code=%d msg=%s",
                              label, Trade.ResultRetcode(), Trade.ResultComment()));
   return ok;
  }

//+------------------------------------------------------------------+
//| ManageOpenPosition — bid-extreme partial detection (v1.2 FIX 2) |
//+------------------------------------------------------------------+
void ManageOpenPosition()
  {
   double cur_bid = SymInfo.Bid();

   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!Position.SelectByIndex(i)) continue;
      if(Position.Symbol() != _Symbol) continue;
      if(Position.Magic()  != InpMagicNumber) continue;

      ulong  ticket  = Position.Ticket();
      double entry   = Position.PriceOpen();
      double stop    = Position.StopLoss();
      double tp      = Position.TakeProfit();
      double volume  = Position.Volume();
      ENUM_POSITION_TYPE type = Position.PositionType();
      bool   is_bear = (type == POSITION_TYPE_SELL);

      double original_lot = GVRead(ticket, "origLot", volume);
      double r_distance   = GVRead(ticket, "rDist", 0);
      int    partials_hit = (int)GVRead(ticket, "partials", 0);
      double mid          = GVRead(ticket, "mid", 0);

      if(r_distance == 0)
        {
         r_distance = MathAbs(entry - GVRead(ticket, "initialStop", stop));
         if(r_distance == 0) r_distance = MathAbs(entry - stop);
         GVWrite(ticket, "origLot",  volume);
         GVWrite(ticket, "rDist",    r_distance);
         GVWrite(ticket, "partials", 0);
         GVWrite(ticket, "mid",      mid > 0 ? mid : ParseMidFromComment(Position.Comment()));
         GVWrite(ticket, "target",   tp);
         GVWrite(ticket, "isBear",   is_bear ? 1.0 : 0.0);
         GVWrite(ticket, "entryTime",(double)TimeCurrent());
         GVWrite(ticket, "minBid",   cur_bid);
         GVWrite(ticket, "maxBid",   cur_bid);
         LogInfo(StringFormat("  Position open ticket=%I64u lot=%.2f entry=%.5f stop=%.5f R=%.5f",
                              ticket, volume, entry, stop, r_distance));
        }

      double min_bid = GVRead(ticket, "minBid", cur_bid);
      double max_bid = GVRead(ticket, "maxBid", cur_bid);
      if(cur_bid < min_bid){ min_bid = cur_bid; GVWrite(ticket, "minBid", min_bid); }
      if(cur_bid > max_bid){ max_bid = cur_bid; GVWrite(ticket, "maxBid", max_bid); }

      datetime entry_time = (datetime)GVRead(ticket, "entryTime", (double)TimeCurrent());
      if(TimeCurrent() - entry_time > InpMaxHoldHours * 3600)
        {
         LogInfo(StringFormat("Max hold on ticket %I64u - closing.", ticket));
         Trade.PositionClose(ticket);
         GVDeleteForTicket(ticket);
         continue;
        }

      double target = GVRead(ticket, "target", tp);
      double p1, p2, p3;
      if(is_bear)
        {
         p1 = MathMax(entry - 1.0 * r_distance, target);
         p2 = MathMax(entry - 2.0 * r_distance, target);
         p3 = target;
        }
      else
        {
         p1 = MathMin(entry + 1.0 * r_distance, target);
         p2 = MathMin(entry + 2.0 * r_distance, target);
         p3 = target;
        }

      bool p1_hit, p2_hit, p3_hit;
      if(is_bear)
        { p1_hit = (min_bid <= p1); p2_hit = (min_bid <= p2); p3_hit = (min_bid <= p3); }
      else
        { p1_hit = (max_bid >= p1); p2_hit = (max_bid >= p2); p3_hit = (max_bid >= p3); }

      double current_volume = volume;
      int local_partials = partials_hit;

      if(local_partials < 1 && p1_hit)
        {
         double close_lot = NormalizeLot(original_lot * 0.5);
         if(close_lot > 0 && close_lot < current_volume)
           {
            if(Trade.PositionClosePartial(ticket, close_lot))
              {
               Trade.PositionModify(ticket, entry, tp);
               GVWrite(ticket, "partials", 1);
               LogInfo(StringFormat("  P1 fired (50%%) @ extreme bid=%.5f p1=%.5f stop->BE ticket=%I64u",
                                    is_bear ? min_bid:max_bid, p1, ticket));
               current_volume -= close_lot;
               local_partials = 1;
              }
           }
        }
      if(local_partials < 2 && p2_hit && p1_hit)
        {
         double close_lot = NormalizeLot(original_lot * 0.3);
         if(close_lot > 0 && close_lot < current_volume)
           {
            if(Trade.PositionClosePartial(ticket, close_lot))
              {
               double new_stop = is_bear ? (entry - r_distance) : (entry + r_distance);
               Trade.PositionModify(ticket, new_stop, tp);
               GVWrite(ticket, "partials", 2);
               LogInfo(StringFormat("  P2 fired (30%%) @ p2=%.5f stop->1R ticket=%I64u", p2, ticket));
               current_volume -= close_lot;
               local_partials = 2;
              }
           }
        }
      if(local_partials < 3 && p3_hit && p2_hit)
        {
         if(Trade.PositionClose(ticket))
           {
            GVDeleteForTicket(ticket);
            LogInfo(StringFormat("  P3/final fired @ p3=%.5f ticket=%I64u", p3, ticket));
           }
        }
     }
  }

//+------------------------------------------------------------------+
//| ComputeLotSize — RISK_FIXED uses InpFixedRiskBalance             |
//+------------------------------------------------------------------+
double ComputeLotSize(double r_distance)
  {
   double ref_bal = (InpRiskMode == RISK_FIXED)
                    ? InpFixedRiskBalance
                    : AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_money = ref_bal * InpRiskPercent / 100.0;

   double tick_size  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   if(tick_size <= 0 || tick_value <= 0) return 0;
   double ticks = r_distance / tick_size;
   double money_per_lot = ticks * tick_value;
   if(money_per_lot <= 0) return 0;

   double lot = risk_money / money_per_lot;
   if(InpMaxLotsPerTrade > 0 && lot > InpMaxLotsPerTrade)
     {
      if(InpVerboseLog)
         LogInfo(StringFormat("  Lot capped: %.2f -> %.2f", lot, InpMaxLotsPerTrade));
      lot = InpMaxLotsPerTrade;
     }
   return NormalizeLot(lot);
  }

double NormalizeLot(double lot)
  {
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double minl = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxl = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   lot = MathFloor(lot / step) * step;
   if(lot < minl) return 0;
   if(lot > maxl) lot = maxl;
   return lot;
  }

//+------------------------------------------------------------------+
//| Spread sanity check                                              |
//+------------------------------------------------------------------+
bool IsSpreadAbnormal()
  {
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   long sp_pts = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   double cur_spread = sp_pts * point;
   if(g_TypicalSpread <= 0) return false;
   return (cur_spread > InpMaxSpreadMultiplier * g_TypicalSpread);
  }

//+------------------------------------------------------------------+
//| Session filter — uses InpSessionMask bitmask                    |
//+------------------------------------------------------------------+
bool IsGoSession(datetime t)
  {
   int h = NYHour(t);
   int session_bit = 0;
   if     (h >= 20 && h < 22) session_bit = SESSION_ASIAN_KZ;
   else if(h >= 22 || h < 2)  session_bit = SESSION_ASIAN;
   else if(h >= 2  && h < 5)  session_bit = SESSION_LONDON_KZ;
   else if(h >= 5  && h < 7)  session_bit = SESSION_LONDON;
   else if(h >= 7  && h < 10) session_bit = SESSION_NY_AM_KZ;
   else if(h >= 10 && h < 12) session_bit = SESSION_LONDON_CLOSE;
   else if(h >= 12 && h < 16) session_bit = SESSION_NY_PM;
   else if(h >= 16 && h < 20) session_bit = SESSION_OFF_HOURS;
   return ((InpSessionMask & session_bit) != 0);
  }

int NYHour(datetime t)
  {
   MqlDateTime dt; TimeToStruct(t, dt);
   datetime dst_start = ComputeDSTStart(dt.year);
   datetime dst_end   = ComputeDSTEnd(dt.year);
   int offset_hours = (t >= dst_start && t < dst_end) ? -4 : -5;
   datetime ny = t + offset_hours * 3600;
   MqlDateTime ny_dt; TimeToStruct(ny, ny_dt);
   return ny_dt.hour;
  }

datetime ComputeDSTStart(int year)
  {
   for(int day = 8; day <= 14; day++)
     {
      MqlDateTime dt; dt.year=year; dt.mon=3; dt.day=day;
      dt.hour=7; dt.min=0; dt.sec=0;
      datetime t = StructToTime(dt);
      MqlDateTime tt; TimeToStruct(t, tt);
      if(tt.day_of_week == 0) return t;
     }
   return 0;
  }

datetime ComputeDSTEnd(int year)
  {
   for(int day = 1; day <= 7; day++)
     {
      MqlDateTime dt; dt.year=year; dt.mon=11; dt.day=day;
      dt.hour=6; dt.min=0; dt.sec=0;
      datetime t = StructToTime(dt);
      MqlDateTime tt; TimeToStruct(t, tt);
      if(tt.day_of_week == 0) return t;
     }
   return 0;
  }

//+------------------------------------------------------------------+
//| News filter                                                      |
//+------------------------------------------------------------------+
bool IsNewsBlackout()
  {
   if(TimeCurrent() - g_LastCalendarRefresh < 60 && g_LastCalendarRefresh > 0)
      return (GlobalVariableGet("SMCCRT_News_" + IntegerToString(InpMagicNumber)) > 0);
   g_LastCalendarRefresh = TimeCurrent();

   datetime from = TimeCurrent() - InpNewsBlackoutAfter * 60;
   datetime to   = TimeCurrent() + InpNewsBlackoutBefore * 60;

   string base = "", quote = "";
   ExtractCurrencies(_Symbol, base, quote);

   MqlCalendarValue values[];
   string country_codes[] = {"US","EU","GB","JP","DE","CA","AU","NZ","CH"};
   bool blackout = false;

   for(int c = 0; c < ArraySize(country_codes) && !blackout; c++)
     {
      string ccode = country_codes[c];
      if(base != ccode && quote != ccode && !IsGlobalEvent(ccode)) continue;
      int nv = CalendarValueHistory(values, from, to, ccode);
      for(int i = 0; i < nv; i++)
        {
         MqlCalendarEvent evt;
         if(!CalendarEventById(values[i].event_id, evt)) continue;
         bool blocks = (InpNewsImpact == IMPACT_HIGH_ONLY)
                       ? (evt.importance == CALENDAR_IMPORTANCE_HIGH)
                       : (evt.importance >= CALENDAR_IMPORTANCE_MODERATE);
         if(blocks)
           {
            blackout = true;
            if(InpVerboseLog)
               LogInfo(StringFormat("News blackout: %s [%s] @ %s",
                                    evt.name, ccode,
                                    TimeToString(values[i].time, TIME_MINUTES)));
            break;
           }
        }
     }
   GlobalVariableSet("SMCCRT_News_" + IntegerToString(InpMagicNumber), blackout ? 1.0 : 0.0);
   return blackout;
  }

void ExtractCurrencies(string sym, string &base, string &quote)
  {
   if(StringLen(sym) >= 6){ base = StringSubstr(sym,0,3); quote = StringSubstr(sym,3,3); }
   if(StringFind(sym,"XAU") >= 0)                                    { base="XAU"; quote="USD"; }
   else if(StringFind(sym,"NAS") >= 0 || StringFind(sym,"US100") >= 0){ base="US";  quote="";   }
   else if(StringFind(sym,"US30") >= 0 || StringFind(sym,"DJ") >= 0)  { base="US";  quote="";   }
  }

bool IsGlobalEvent(string ccode){ return ccode == "US"; }

//+------------------------------------------------------------------+
//| FTMO compliance helpers                                          |
//+------------------------------------------------------------------+
double ComputeDailyLossPct()
  {
   double cur_eq = AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_DayStartEquity <= 0) return 0;
   double drawdown = g_DayStartEquity - cur_eq;
   if(drawdown <= 0) return 0;
   return 100.0 * drawdown / g_DayStartEquity;
  }

datetime GetDayStart()
  {
   datetime now = TimeCurrent();
   MqlDateTime dt; TimeToStruct(now, dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   return StructToTime(dt);
  }

bool IsFridayCloseTime()
  {
   datetime t = TimeCurrent();
   MqlDateTime dt; TimeToStruct(t, dt);
   if(dt.day_of_week != 5) return false;
   return NYHour(t) >= InpFridayCloseHourNY;
  }

//+------------------------------------------------------------------+
//| Position helpers                                                 |
//+------------------------------------------------------------------+
bool HasOpenPosition()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!Position.SelectByIndex(i)) continue;
      if(Position.Symbol() == _Symbol && Position.Magic() == InpMagicNumber) return true;
     }
   return false;
  }

void CloseAllOurPositions(string reason)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!Position.SelectByIndex(i)) continue;
      if(Position.Symbol() != _Symbol || Position.Magic() != InpMagicNumber) continue;
      ulong tk = Position.Ticket();
      Trade.PositionClose(tk);
      GVDeleteForTicket(tk);
      LogInfo(StringFormat("  Force-closed ticket %I64u (%s)", tk, reason));
     }
   CancelAllOurPendingOrders();
  }

void CancelAllOurPendingOrders()
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong tk = OrderGetTicket(i);
      if(!OrderSelect(tk)) continue;
      if(OrderGetString(ORDER_SYMBOL)  != _Symbol) continue;
      if(OrderGetInteger(ORDER_MAGIC)  != InpMagicNumber) continue;
      Trade.OrderDelete(tk);
     }
  }

//+------------------------------------------------------------------+
//| ATR                                                              |
//+------------------------------------------------------------------+
double ComputeATR(ENUM_TIMEFRAMES tf, int period, int shift)
  {
   int handle = iATR(_Symbol, tf, period);
   if(handle == INVALID_HANDLE) return 0;
   double buf[];
   if(CopyBuffer(handle, 0, shift, 1, buf) <= 0) return 0;
   return buf[0];
  }

//+------------------------------------------------------------------+
//| Per-ticket global variable helpers                               |
//+------------------------------------------------------------------+
string GVKey(ulong ticket, string field)
  { return StringFormat("SMCCRT_%I64u_%s", ticket, field); }

double GVRead(ulong ticket, string field, double dflt)
  {
   string k = GVKey(ticket, field);
   if(GlobalVariableCheck(k)) return GlobalVariableGet(k);
   return dflt;
  }

void GVWrite(ulong ticket, string field, double val)
  { GlobalVariableSet(GVKey(ticket, field), val); }

void GVDeleteForTicket(ulong ticket)
  {
   string fields[] = {"origLot","rDist","partials","mid","target",
                      "isBear","entryTime","initialStop","minBid","maxBid"};
   for(int i = 0; i < ArraySize(fields); i++) GlobalVariableDel(GVKey(ticket, fields[i]));
  }

double ParseMidFromComment(string comment)
  {
   int p = StringFind(comment, "m=");
   if(p < 0) return 0;
   string s = StringSubstr(comment, p+2);
   int e = StringFind(s, "|");
   if(e > 0) s = StringSubstr(s, 0, e);
   return StringToDouble(s);
  }

//+------------------------------------------------------------------+
//| Logging                                                          |
//+------------------------------------------------------------------+
void LogInfo(string msg)    { if(InpEnableLogging) Print("[SMC-CRT] ", msg); }
void LogWarning(string msg) { Print("[SMC-CRT WARN] ", msg); }

//+------------------------------------------------------------------+
//| Chart drawing                                                    |
//+------------------------------------------------------------------+
void DrawSetupOnChart(double stop)
  {
   ClearChartObjects();
   DrawHLine("SMCCRT_stop",  stop,             clrRed);
   DrawHLine("SMCCRT_tgt",   g_Setup.target,   clrLime);
   DrawHLine("SMCCRT_mid",   g_Setup.prev_mid, clrYellow);
   DrawHLine("SMCCRT_sweep", g_Setup.sweep_extreme, clrOrange);
  }

void DrawHLine(string name, double price, color c)
  {
   ObjectDelete(0, name);
   ObjectCreate(0, name, OBJ_HLINE, 0, 0, price);
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DASH);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
  }

void ClearChartObjects() { ObjectsDeleteAll(0, "SMCCRT_"); }

//+------------------------------------------------------------------+
//| OnTrade — capture context on fill                                |
//+------------------------------------------------------------------+
void OnTrade()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!Position.SelectByIndex(i)) continue;
      if(Position.Symbol() != _Symbol) continue;
      if(Position.Magic()  != InpMagicNumber) continue;
      ulong tk = Position.Ticket();
      if(!GlobalVariableCheck(GVKey(tk, "rDist")))
        {
         double cur_bid = SymInfo.Bid();
         GVWrite(tk, "initialStop", Position.StopLoss());
         GVWrite(tk, "rDist",      MathAbs(Position.PriceOpen() - Position.StopLoss()));
         GVWrite(tk, "origLot",    Position.Volume());
         GVWrite(tk, "partials",   0);
         GVWrite(tk, "mid",        ParseMidFromComment(Position.Comment()));
         GVWrite(tk, "target",     Position.TakeProfit());
         GVWrite(tk, "isBear",     Position.PositionType() == POSITION_TYPE_SELL ? 1.0 : 0.0);
         GVWrite(tk, "entryTime",  (double)TimeCurrent());
         GVWrite(tk, "minBid",     cur_bid);
         GVWrite(tk, "maxBid",     cur_bid);
         CancelAllOurPendingOrders();
        }
     }
  }
//+------------------------------------------------------------------+
