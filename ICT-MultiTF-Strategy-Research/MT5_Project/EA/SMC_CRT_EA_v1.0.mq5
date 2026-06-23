//+------------------------------------------------------------------+
//|                                                  SMC_CRT_EA.mq5  |
//|                  CRT (Candle Range Theory) + ICT PD Array EA     |
//|                          Designed for FTMO via MetaTrader 5      |
//|                                                                  |
//|  Setup: H4 (or H1) range candle sweep + close back past 0.5      |
//|         M15 (or M5) MSS + FVG/OB entry in premium/discount       |
//|         Fixed-R partials: 50% @ 1R, 30% @ 2R, 20% to target      |
//|                                                                  |
//|  Modes:                                                          |
//|    MODE_H4_M15 - production baseline (PF 5-6, slow tempo)        |
//|    MODE_H4_M5  - finer entries (PF 3, more trades, smaller DD)   |
//|                                                                  |
//|  Notes:                                                          |
//|    - Attach to one chart per traded symbol                       |
//|    - All instances share MagicNumber; FTMO DD tracker is global  |
//|    - Bars use broker time (typically GMT+2/+3 on FTMO)           |
//+------------------------------------------------------------------+
#property copyright "SMC CRT Research"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\SymbolInfo.mqh>

//+------------------------------------------------------------------+
//| Enums                                                            |
//+------------------------------------------------------------------+
enum ENUM_EA_MODE
  {
   MODE_H4_M15 = 0,        // H4 setup + M15 entry (production baseline)
   MODE_H4_M5  = 1,        // H4 setup + M5 entry  (finer precision)
  };

enum ENUM_NEWS_IMPACT
  {
   IMPACT_HIGH_ONLY   = 0, // Block only high-impact events
   IMPACT_MED_AND_UP  = 1, // Block medium AND high impact
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
input ENUM_EA_MODE InpMode               = MODE_H4_M15;   // EA mode

input group "=== Risk & Position Sizing ==="
input double       InpRiskPercent        = 1.0;           // Risk % per trade
input double       InpStopBufferATR      = 0.1;           // Stop buffer (× LTF ATR)
input int          InpMagicNumber        = 202600;        // Magic number

input group "=== Filters ==="
input bool         InpRequireStrongFilter = true;         // Require close past 0.5 of prior range
input bool         InpEnableSessionFilter = true;         // Trade only in go-sessions
input bool         InpEnableNewsFilter   = true;          // Block trades around news
input ENUM_NEWS_IMPACT InpNewsImpact     = IMPACT_HIGH_ONLY; // Which news impact to block
input int          InpNewsBlackoutBefore = 30;            // Minutes before news (block)
input int          InpNewsBlackoutAfter  = 30;            // Minutes after news (block)

input group "=== FTMO Compliance ==="
input double       InpMaxDailyLossPct    = 4.0;           // Halt at this daily loss % (buffer below 5%)
input double       InpHardKillDailyPct   = 4.5;           // Hard close all + stop EA
input bool         InpEnableFridayClose  = true;          // Force-close Friday 20:00 NY
input int          InpFridayCloseHourNY  = 20;            // NY hour to start Friday close

input group "=== Trade Management ==="
input int          InpMaxHoldHours       = 48;            // Max position hold time (hours)
input int          InpEntryWindowHours   = 3;             // LTF entry window after trigger (hours)
input int          InpCooldownMinutes    = 30;            // Cooldown after position close

input group "=== Diagnostics ==="
input bool         InpEnableLogging      = true;          // Detailed logging
input bool         InpDrawLevelsOnChart  = true;          // Draw stop/target/partials on chart

//+------------------------------------------------------------------+
//| Globals                                                          |
//+------------------------------------------------------------------+
CTrade         Trade;
CPositionInfo  Position;
CSymbolInfo    SymInfo;

ENUM_TIMEFRAMES g_HTF;         // H4 derived from mode
ENUM_TIMEFRAMES g_LTF;         // M15 or M5 from mode

datetime g_LastHTFBarTime = 0; // last processed HTF bar open time
datetime g_DayStartTime   = 0; // start of current trading day
double   g_DayStartEquity = 0; // equity at start of day for DD tracking
datetime g_LastCalendarRefresh = 0;
datetime g_CooldownUntil  = 0; // no new trades until this time

ENUM_TRADE_STATE g_State = STATE_IDLE;

// Active setup context (between trigger detection and order placement)
struct SetupContext
  {
   datetime trigger_time;
   bool     is_bear;
   double   prev_high;
   double   prev_low;
   double   prev_mid;
   double   sweep_extreme;     // = prev_high for bear, prev_low for bull
   double   target;            // = prev_low for bear, prev_high for bull
   double   r_distance_planned;// computed when stop is placed
   datetime expires_at;        // LTF entry window expiry
   double   atr_ltf;
  };
SetupContext g_Setup;

//+------------------------------------------------------------------+
//| OnInit                                                           |
//+------------------------------------------------------------------+
int OnInit()
  {
   // Map mode to timeframes
   switch(InpMode)
     {
      case MODE_H4_M15: g_HTF = PERIOD_H4; g_LTF = PERIOD_M15; break;
      case MODE_H4_M5:  g_HTF = PERIOD_H4; g_LTF = PERIOD_M5;  break;
      default: Print("ERROR: invalid mode"); return INIT_FAILED;
     }

   Trade.SetExpertMagicNumber(InpMagicNumber);
   Trade.SetDeviationInPoints(20);
   Trade.SetTypeFillingBySymbol(_Symbol);
   SymInfo.Name(_Symbol);

   // Reset daily DD tracker
   g_DayStartTime   = GetDayStart();
   g_DayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);

   // Restore state from any existing positions with our magic
   if(HasOpenPosition())
     {
      g_State = STATE_IN_POSITION;
      LogInfo("Restored: open position found with our magic, resuming management");
     }
   else
     {
      g_State = STATE_IDLE;
     }

   LogInfo(StringFormat("EA initialized — mode=%s, HTF=%s, LTF=%s, magic=%d",
                        EnumToString(InpMode),
                        EnumToString(g_HTF), EnumToString(g_LTF),
                        InpMagicNumber));
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
//| OnDeinit                                                         |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   LogInfo(StringFormat("EA stopping — reason=%d", reason));
   ClearChartObjects();
  }

//+------------------------------------------------------------------+
//| OnTick — main event loop                                         |
//+------------------------------------------------------------------+
void OnTick()
  {
   // 1) Always refresh symbol data
   SymInfo.RefreshRates();

   // 2) Day rollover — reset DD tracker
   datetime day_now = GetDayStart();
   if(day_now != g_DayStartTime)
     {
      g_DayStartTime   = day_now;
      g_DayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      LogInfo(StringFormat("Day rollover. Day start equity = %.2f", g_DayStartEquity));
     }

   // 3) FTMO compliance: daily DD check
   double daily_loss_pct = ComputeDailyLossPct();
   if(daily_loss_pct >= InpHardKillDailyPct)
     {
      LogWarning(StringFormat("HARD KILL: daily loss %.2f%% >= %.2f%%. Closing all + halting.",
                              daily_loss_pct, InpHardKillDailyPct));
      CloseAllOurPositions("hard_kill");
      g_State = STATE_HALTED;
      return;
     }
   if(daily_loss_pct >= InpMaxDailyLossPct && g_State != STATE_IN_POSITION)
     {
      // Soft halt: no new entries, but existing positions still managed
      if(g_State != STATE_HALTED)
        {
         LogWarning(StringFormat("SOFT HALT: daily loss %.2f%% >= %.2f%%. No new entries.",
                                 daily_loss_pct, InpMaxDailyLossPct));
         g_State = STATE_HALTED;
        }
     }

   // 4) Friday close protection
   if(InpEnableFridayClose && IsFridayCloseTime())
     {
      if(HasOpenPosition())
        {
         LogInfo("Friday close trigger — closing position.");
         CloseAllOurPositions("friday_close");
        }
      // Allow only management today after close
      return;
     }

   // 5) Manage open position (partials, stop moves, max-hold check)
   if(HasOpenPosition())
     {
      g_State = STATE_IN_POSITION;
      ManageOpenPosition();
      return;
     }
   else if(g_State == STATE_IN_POSITION)
     {
      // Just closed — enter cooldown
      g_CooldownUntil = TimeCurrent() + InpCooldownMinutes * 60;
      g_State = STATE_IDLE;
      ClearChartObjects();
     }

   // 6) If halted, do nothing new
   if(g_State == STATE_HALTED) return;

   // 7) Cooldown
   if(TimeCurrent() < g_CooldownUntil) return;

   // 8) Has the active setup's entry window expired?
   if(g_State == STATE_WAITING_ENTRY && TimeCurrent() > g_Setup.expires_at)
     {
      LogInfo("Entry window expired. Cancelling pending orders, returning to IDLE.");
      CancelAllOurPendingOrders();
      g_State = STATE_IDLE;
      ClearChartObjects();
     }

   // 9) Detect new HTF candle close
   datetime current_htf_bar = iTime(_Symbol, g_HTF, 1); // most recently CLOSED HTF bar
   if(current_htf_bar > g_LastHTFBarTime)
     {
      g_LastHTFBarTime = current_htf_bar;
      OnNewHTFBarClose();
     }

   // 10) If waiting for entry, see if M5/M15 has provided fresh MSS/FVG/OB
   //     (we re-scan LTF on every tick within the window)
   if(g_State == STATE_WAITING_ENTRY)
     {
      // Pending orders already placed; just wait. No action needed here.
     }
  }

//+------------------------------------------------------------------+
//| HTF bar close handler — entry point for new triggers             |
//+------------------------------------------------------------------+
void OnNewHTFBarClose()
  {
   if(g_State != STATE_IDLE) return; // only scan when idle

   // Get the HTF bar that just closed (index 1) and its predecessor (index 2)
   double prev_h = iHigh(_Symbol, g_HTF, 2);
   double prev_l = iLow (_Symbol, g_HTF, 2);
   double sweep_high = iHigh(_Symbol, g_HTF, 1);
   double sweep_low  = iLow (_Symbol, g_HTF, 1);
   double sweep_close= iClose(_Symbol, g_HTF, 1);
   datetime sweep_time = iTime(_Symbol, g_HTF, 1);

   bool swept_high = sweep_high > prev_h;
   bool swept_low  = sweep_low  < prev_l;
   if(swept_high && swept_low) return; // both-side sweep, ambiguous
   if(!swept_high && !swept_low) return;

   double prev_mid = (prev_h + prev_l) / 2.0;
   bool is_bear, valid_strong;
   if(swept_high)
     {
      is_bear = true;
      valid_strong = (sweep_close <= prev_mid);
     }
   else
     {
      is_bear = false;
      valid_strong = (sweep_close >= prev_mid);
     }

   if(InpRequireStrongFilter && !valid_strong) return;

   // Session filter
   if(InpEnableSessionFilter && !IsGoSession(sweep_time)) return;

   // News filter
   if(InpEnableNewsFilter && IsNewsBlackout()) return;

   // Build setup context and transition to entry-waiting state
   g_Setup.trigger_time   = sweep_time;
   g_Setup.is_bear        = is_bear;
   g_Setup.prev_high      = prev_h;
   g_Setup.prev_low       = prev_l;
   g_Setup.prev_mid       = prev_mid;
   g_Setup.sweep_extreme  = is_bear ? sweep_high : sweep_low;
   g_Setup.target         = is_bear ? prev_l : prev_h;
   g_Setup.expires_at     = TimeCurrent() + InpEntryWindowHours * 3600;
   g_Setup.atr_ltf        = ComputeATR(g_LTF, 14, 1);

   g_State = STATE_TRIGGER_DETECTED;

   LogInfo(StringFormat("CRT trigger detected: %s %s prev_range=[%.5f, %.5f] mid=%.5f target=%.5f",
                        TimeToString(sweep_time, TIME_DATE|TIME_MINUTES),
                        is_bear ? "BEAR" : "BULL",
                        prev_l, prev_h, prev_mid, g_Setup.target));

   // Immediately try to find MSS + FVG + OB on LTF
   TryPlaceEntries();
  }

//+------------------------------------------------------------------+
//| Look for LTF MSS + FVG + OB and place limit orders               |
//+------------------------------------------------------------------+
void TryPlaceEntries()
  {
   // Scan LTF bars from the moment the HTF bar closed
   datetime htf_close = g_Setup.trigger_time + PeriodSeconds(g_HTF);
   int max_bars = (InpMode == MODE_H4_M5) ? 36 : 12;
   int extra = 5;

   // Find LTF bars starting at htf_close
   int total = max_bars + extra;
   double highs[], lows[], opens[], closes[];
   datetime times[];
   ArrayResize(highs, total); ArrayResize(lows, total);
   ArrayResize(opens, total); ArrayResize(closes, total);
   ArrayResize(times, total);

   // Pull most recent N LTF bars; we'll filter for those >= htf_close
   int copied = CopyTime(_Symbol, g_LTF, 0, total*2, times);
   if(copied <= 0) return;

   // Build arrays of bars at or after htf_close
   int n = 0;
   for(int i = copied-1; i >= 0 && n < total; i--) // iterate forward in time
     {
      if(times[i] >= htf_close)
        {
         times[n]  = times[i];
         highs[n]  = iHigh(_Symbol, g_LTF, i);
         lows[n]   = iLow(_Symbol, g_LTF, i);
         opens[n]  = iOpen(_Symbol, g_LTF, i);
         closes[n] = iClose(_Symbol, g_LTF, i);
         n++;
        }
     }
   if(n < 5) return; // not enough bars yet

   // Detect MSS
   int mss_idx = FindMSS(highs, lows, closes, n, g_Setup.is_bear);
   if(mss_idx < 0) return;

   // Find FVG and OB candidates
   double fvg_level = FindFVG(highs, lows, n, mss_idx, g_Setup.is_bear);
   double ob_level  = FindOB(highs, lows, opens, closes, mss_idx, g_Setup.is_bear);

   // Premium/discount filter
   bool fvg_valid = (fvg_level != EMPTY_VALUE) && PremiumDiscountOK(fvg_level);
   bool ob_valid  = (ob_level  != EMPTY_VALUE) && PremiumDiscountOK(ob_level);

   if(!fvg_valid && !ob_valid) return;

   // Compute stop level
   double buffer = InpStopBufferATR * g_Setup.atr_ltf;
   double stop = g_Setup.is_bear
                 ? g_Setup.sweep_extreme + buffer
                 : g_Setup.sweep_extreme - buffer;

   // Place limit orders for whichever candidates we have
   if(fvg_valid) PlaceLimitOrder(fvg_level, stop, "FVG");
   if(ob_valid)  PlaceLimitOrder(ob_level,  stop, "OB");

   g_State = STATE_WAITING_ENTRY;

   if(InpDrawLevelsOnChart) DrawSetupOnChart(stop);
  }

//+------------------------------------------------------------------+
//| Find MSS - break of recent swing high/low                        |
//+------------------------------------------------------------------+
int FindMSS(const double &highs[], const double &lows[], const double &closes[],
            int n, bool is_bear)
  {
   if(n < 5) return -1;
   if(is_bear)
     {
      double ref_low = lows[0];
      for(int i=1; i<=3 && i<n; i++) ref_low = MathMin(ref_low, lows[i]);
      for(int i=3; i<n; i++)
        {
         if(closes[i] < ref_low) return i;
         ref_low = MathMin(ref_low, lows[i]);
        }
     }
   else
     {
      double ref_high = highs[0];
      for(int i=1; i<=3 && i<n; i++) ref_high = MathMax(ref_high, highs[i]);
      for(int i=3; i<n; i++)
        {
         if(closes[i] > ref_high) return i;
         ref_high = MathMax(ref_high, highs[i]);
        }
     }
   return -1;
  }

//+------------------------------------------------------------------+
//| Find FVG - 3-bar imbalance at or before MSS                      |
//+------------------------------------------------------------------+
double FindFVG(const double &highs[], const double &lows[],
               int n, int mss_idx, bool is_bear)
  {
   for(int j = 2; j <= mss_idx && j < n; j++)
     {
      if(is_bear)
        {
         if(lows[j-2] > highs[j])
            return (lows[j-2] + highs[j]) / 2.0;
        }
      else
        {
         if(highs[j-2] < lows[j])
            return (highs[j-2] + lows[j]) / 2.0;
        }
     }
   return EMPTY_VALUE;
  }

//+------------------------------------------------------------------+
//| Find OB - last opposite-color candle before MSS                  |
//+------------------------------------------------------------------+
double FindOB(const double &highs[], const double &lows[],
              const double &opens[], const double &closes[],
              int mss_idx, bool is_bear)
  {
   for(int j = mss_idx - 1; j >= 0; j--)
     {
      bool is_bull_candle = closes[j] > opens[j];
      if(is_bear && is_bull_candle)
         return MathMax(opens[j], closes[j]); // body high
      if(!is_bear && !is_bull_candle)
         return MathMin(opens[j], closes[j]); // body low
     }
   return EMPTY_VALUE;
  }

//+------------------------------------------------------------------+
//| Premium/discount filter — entry must be on correct side of mid   |
//+------------------------------------------------------------------+
bool PremiumDiscountOK(double level)
  {
   if(g_Setup.is_bear)
      return level >= g_Setup.prev_mid;
   else
      return level <= g_Setup.prev_mid;
  }

//+------------------------------------------------------------------+
//| Place a limit order at given level with given stop               |
//+------------------------------------------------------------------+
bool PlaceLimitOrder(double level, double stop, string label)
  {
   double r_distance = MathAbs(level - stop);
   if(r_distance <= 0) return false;

   // Compute lot size
   double lot = ComputeLotSize(r_distance);
   if(lot <= 0) return false;

   // Take profit = natural target
   double tp = g_Setup.target;

   // Comment encodes context for OnTradeTransaction tracking
   string comment = StringFormat("SMCCRT|%s|%s|m=%.5f|t=%.5f",
                                 label,
                                 g_Setup.is_bear ? "B" : "L",
                                 g_Setup.prev_mid, g_Setup.target);

   bool ok = false;
   if(g_Setup.is_bear)
      ok = Trade.SellLimit(lot, level, _Symbol, stop, tp, ORDER_TIME_GTC, 0, comment);
   else
      ok = Trade.BuyLimit (lot, level, _Symbol, stop, tp, ORDER_TIME_GTC, 0, comment);

   if(ok)
     {
      LogInfo(StringFormat("  Pending %s %s order placed: lot=%.2f level=%.5f stop=%.5f tp=%.5f R=%.5f",
                           label, g_Setup.is_bear ? "SELL" : "BUY",
                           lot, level, stop, tp, r_distance));
      // Save partial-close context to globals keyed by symbol+magic
      // (will be enriched per-ticket once position opens)
      g_Setup.r_distance_planned = r_distance;
     }
   else
     {
      LogWarning(StringFormat("  Order placement failed for %s: %d %s",
                              label, Trade.ResultRetcode(), Trade.ResultComment()));
     }
   return ok;
  }

//+------------------------------------------------------------------+
//| Position management — partials, stop moves                       |
//+------------------------------------------------------------------+
void ManageOpenPosition()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!Position.SelectByIndex(i)) continue;
      if(Position.Symbol() != _Symbol) continue;
      if(Position.Magic()  != InpMagicNumber) continue;

      ulong ticket = Position.Ticket();
      double entry  = Position.PriceOpen();
      double stop   = Position.StopLoss();
      double tp     = Position.TakeProfit();
      double volume = Position.Volume();
      ENUM_POSITION_TYPE type = Position.PositionType();
      bool is_bear  = (type == POSITION_TYPE_SELL);

      // Retrieve partial-close state from globals
      double original_lot = GVRead(ticket, "origLot", volume);
      double r_distance   = GVRead(ticket, "rDist", 0);
      int    partials_hit = (int)GVRead(ticket, "partials", 0);
      double mid          = GVRead(ticket, "mid", 0);

      // First time seeing this ticket — save initial context
      if(r_distance == 0)
        {
         r_distance = MathAbs(entry - GVRead(ticket, "initialStop", stop));
         // Fallback: derive r_distance from current stop if no initial stored
         if(r_distance == 0) r_distance = MathAbs(entry - stop);

         GVWrite(ticket, "origLot", volume);
         GVWrite(ticket, "rDist", r_distance);
         GVWrite(ticket, "partials", 0);
         GVWrite(ticket, "mid", mid > 0 ? mid : ParseMidFromComment(Position.Comment()));
         GVWrite(ticket, "target", tp);
         GVWrite(ticket, "isBear", is_bear ? 1 : 0);
         GVWrite(ticket, "entryTime", (double)TimeCurrent());
         LogInfo(StringFormat("  Position opened, ticket=%I64u lot=%.2f entry=%.5f stop=%.5f R=%.5f",
                              ticket, volume, entry, stop, r_distance));
        }

      // Max hold time check
      datetime entry_time = (datetime)GVRead(ticket, "entryTime", (double)TimeCurrent());
      if(TimeCurrent() - entry_time > InpMaxHoldHours * 3600)
        {
         LogInfo(StringFormat("Max hold reached on ticket %I64u — closing.", ticket));
         Trade.PositionClose(ticket);
         GVDeleteForTicket(ticket);
         continue;
        }

      // Compute current price
      double bid = SymInfo.Bid();
      double ask = SymInfo.Ask();
      double cur_price = is_bear ? ask : bid;

      // Partial levels per Scheme A:
      // p1 = entry ± 1R, capped at target
      // p2 = entry ± 2R, capped at target
      // p3 = target (always)
      double p1, p2, p3;
      double target = GVRead(ticket, "target", tp);
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

      // Check partial firing
      bool p1_hit = is_bear ? (cur_price <= p1) : (cur_price >= p1);
      bool p2_hit = is_bear ? (cur_price <= p2) : (cur_price >= p2);
      bool p3_hit = is_bear ? (cur_price <= p3) : (cur_price >= p3);

      if(partials_hit < 1 && p1_hit)
        {
         double close_lot = NormalizeLot(original_lot * 0.5);
         if(close_lot > 0 && close_lot < volume)
           {
            if(Trade.PositionClosePartial(ticket, close_lot))
              {
               // Move stop to BE
               double new_stop = entry;
               Trade.PositionModify(ticket, new_stop, tp);
               GVWrite(ticket, "partials", 1);
               LogInfo(StringFormat("  Partial 1 fired (50%%) @ %.5f, stop -> BE on ticket %I64u",
                                    p1, ticket));
              }
           }
        }
      else if(partials_hit < 2 && p2_hit)
        {
         double close_lot = NormalizeLot(original_lot * 0.3);
         if(close_lot > 0 && close_lot < volume)
           {
            if(Trade.PositionClosePartial(ticket, close_lot))
              {
               // Move stop to 1R (locking +1R on runner)
               double new_stop = is_bear ? (entry - r_distance) : (entry + r_distance);
               Trade.PositionModify(ticket, new_stop, tp);
               GVWrite(ticket, "partials", 2);
               LogInfo(StringFormat("  Partial 2 fired (30%%) @ %.5f, stop -> 1R on ticket %I64u",
                                    p2, ticket));
              }
           }
        }
      else if(partials_hit < 3 && p3_hit)
        {
         // Close the remaining 20% at target (final)
         if(Trade.PositionClose(ticket))
           {
            GVDeleteForTicket(ticket);
            LogInfo(StringFormat("  Partial 3/final fired @ %.5f on ticket %I64u",
                                 p3, ticket));
           }
        }
     }
  }

//+------------------------------------------------------------------+
//| Lot sizing — risk % of equity per R-distance                     |
//+------------------------------------------------------------------+
double ComputeLotSize(double r_distance)
  {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_money = equity * InpRiskPercent / 100.0;

   // tick value for one minimum lot (point) on this symbol
   double tick_size  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   if(tick_size <= 0 || tick_value <= 0) return 0;

   double ticks = r_distance / tick_size;
   double money_per_lot = ticks * tick_value;
   if(money_per_lot <= 0) return 0;

   double lot = risk_money / money_per_lot;
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
//| Session classifier — "go" if in our analyzed go-sessions         |
//+------------------------------------------------------------------+
bool IsGoSession(datetime t)
  {
   int ny_hour = NYHour(t);
   // Go: 20-22, 22-2, 2-5, 5-7, 7-10 NY (asian_kz, asian, london_kz, london, ny_am_kz)
   if(ny_hour >= 20 && ny_hour < 22) return true;
   if(ny_hour >= 22 || ny_hour < 2)  return true;
   if(ny_hour >= 2  && ny_hour < 5)  return true;
   if(ny_hour >= 5  && ny_hour < 7)  return true;
   if(ny_hour >= 7  && ny_hour < 10) return true;
   return false;
  }

int NYHour(datetime t)
  {
   // Convert UTC -> NY local (DST-aware)
   // MT5 doesn't have built-in DST, so approximate:
   // Last Sunday of March to first Sunday of November = EDT (UTC-4)
   // else EST (UTC-5)
   MqlDateTime dt; TimeToStruct(t, dt);
   int year = dt.year;
   datetime dst_start = ComputeDSTStart(year); // 2nd Sun March 2am
   datetime dst_end   = ComputeDSTEnd(year);   // 1st Sun Nov 2am
   int offset_hours = (t >= dst_start && t < dst_end) ? -4 : -5;
   datetime ny = t + offset_hours * 3600;
   MqlDateTime ny_dt; TimeToStruct(ny, ny_dt);
   return ny_dt.hour;
  }

datetime ComputeDSTStart(int year)
  {
   // US DST: 2nd Sunday of March, 2am local
   for(int day = 8; day <= 14; day++)
     {
      MqlDateTime dt; dt.year=year; dt.mon=3; dt.day=day;
      dt.hour=7; dt.min=0; dt.sec=0; // 2am EST = 7am UTC
      datetime t = StructToTime(dt);
      MqlDateTime tt; TimeToStruct(t, tt);
      if(tt.day_of_week == 0) return t;
     }
   return 0;
  }

datetime ComputeDSTEnd(int year)
  {
   // 1st Sunday of November, 2am local
   for(int day = 1; day <= 7; day++)
     {
      MqlDateTime dt; dt.year=year; dt.mon=11; dt.day=day;
      dt.hour=6; dt.min=0; dt.sec=0; // 2am EDT = 6am UTC
      datetime t = StructToTime(dt);
      MqlDateTime tt; TimeToStruct(t, tt);
      if(tt.day_of_week == 0) return t;
     }
   return 0;
  }

//+------------------------------------------------------------------+
//| News filter via MT5 Economic Calendar                            |
//+------------------------------------------------------------------+
bool IsNewsBlackout()
  {
   // Throttle: refresh at most every 60 seconds
   if(TimeCurrent() - g_LastCalendarRefresh < 60 && g_LastCalendarRefresh > 0)
     {
      // re-read cached result via global var
      return (GlobalVariableGet("SMCCRT_News_" + IntegerToString(InpMagicNumber)) > 0);
     }
   g_LastCalendarRefresh = TimeCurrent();

   datetime from = TimeCurrent() - InpNewsBlackoutAfter * 60;
   datetime to   = TimeCurrent() + InpNewsBlackoutBefore * 60;

   // Get currencies relevant to our symbol
   string base = "", quote = "";
   ExtractCurrencies(_Symbol, base, quote);

   MqlCalendarValue values[];
   string country_codes[] = {"US", "EU", "GB", "JP", "DE", "CA", "AU", "NZ", "CH"};
   bool blackout = false;

   for(int c = 0; c < ArraySize(country_codes) && !blackout; c++)
     {
      string ccode = country_codes[c];
      if(base != ccode && quote != ccode && !IsGlobalEvent(ccode)) continue;

      int n = CalendarValueHistory(values, from, to, ccode);
      for(int i = 0; i < n; i++)
        {
         MqlCalendarEvent evt;
         if(!CalendarEventById(values[i].event_id, evt)) continue;
         bool blocks = false;
         if(InpNewsImpact == IMPACT_HIGH_ONLY)
            blocks = (evt.importance == CALENDAR_IMPORTANCE_HIGH);
         else
            blocks = (evt.importance >= CALENDAR_IMPORTANCE_MODERATE);
         if(blocks)
           {
            blackout = true;
            LogInfo(StringFormat("News blackout: %s [%s] at %s",
                                 evt.name, ccode,
                                 TimeToString(values[i].time, TIME_MINUTES)));
            break;
           }
        }
     }
   GlobalVariableSet("SMCCRT_News_" + IntegerToString(InpMagicNumber),
                     blackout ? 1.0 : 0.0);
   return blackout;
  }

void ExtractCurrencies(string sym, string &base, string &quote)
  {
   // FX symbols are 6 chars (EURUSD); metals/indices need mapping
   if(StringLen(sym) >= 6)
     {
      base  = StringSubstr(sym, 0, 3);
      quote = StringSubstr(sym, 3, 3);
     }
   if(StringFind(sym, "XAU") >= 0)        { base = "XAU"; quote = "USD"; }
   else if(StringFind(sym, "NAS") >= 0 ||
           StringFind(sym, "US100") >= 0) { base = "US";  quote = ""; }
   else if(StringFind(sym, "US30") >= 0 ||
           StringFind(sym, "DJ") >= 0)    { base = "US";  quote = ""; }
  }

bool IsGlobalEvent(string ccode) { return ccode == "US"; } // US events affect everything

//+------------------------------------------------------------------+
//| FTMO daily DD computation                                        |
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

//+------------------------------------------------------------------+
//| Friday close check                                               |
//+------------------------------------------------------------------+
bool IsFridayCloseTime()
  {
   datetime t = TimeCurrent();
   MqlDateTime dt; TimeToStruct(t, dt);
   if(dt.day_of_week != 5) return false; // not Friday
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
      if(Position.Symbol() == _Symbol && Position.Magic() == InpMagicNumber)
         return true;
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
      if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
      if(OrderGetInteger(ORDER_MAGIC) != InpMagicNumber) continue;
      Trade.OrderDelete(tk);
     }
  }

//+------------------------------------------------------------------+
//| ATR helper                                                       |
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
//| Global variable helpers — per-ticket state                       |
//+------------------------------------------------------------------+
string GVKey(ulong ticket, string field)
  {
   return StringFormat("SMCCRT_%I64u_%s", ticket, field);
  }

double GVRead(ulong ticket, string field, double dflt)
  {
   string k = GVKey(ticket, field);
   if(GlobalVariableCheck(k)) return GlobalVariableGet(k);
   return dflt;
  }

void GVWrite(ulong ticket, string field, double val)
  {
   GlobalVariableSet(GVKey(ticket, field), val);
  }

void GVDeleteForTicket(ulong ticket)
  {
   string fields[] = {"origLot","rDist","partials","mid","target",
                      "isBear","entryTime","initialStop"};
   for(int i=0; i<ArraySize(fields); i++)
      GlobalVariableDel(GVKey(ticket, fields[i]));
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
void LogInfo(string msg)
  {
   if(InpEnableLogging) Print("[SMC-CRT INFO] ", msg);
  }
void LogWarning(string msg) { Print("[SMC-CRT WARN] ", msg); }

//+------------------------------------------------------------------+
//| Chart drawing                                                    |
//+------------------------------------------------------------------+
void DrawSetupOnChart(double stop)
  {
   string prefix = "SMCCRT_";
   long chart_id = ChartID();
   ClearChartObjects();

   DrawHLine(prefix+"stop",  stop, clrRed);
   DrawHLine(prefix+"tgt",   g_Setup.target, clrLime);
   DrawHLine(prefix+"mid",   g_Setup.prev_mid, clrYellow);
   DrawHLine(prefix+"sweep", g_Setup.sweep_extreme, clrOrange);
  }

void DrawHLine(string name, double price, color c)
  {
   ObjectDelete(0, name);
   ObjectCreate(0, name, OBJ_HLINE, 0, 0, price);
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DASH);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetString (0, name, OBJPROP_TEXT, name);
  }

void ClearChartObjects()
  {
   ObjectsDeleteAll(0, "SMCCRT_");
  }

//+------------------------------------------------------------------+
//| OnTrade — capture position fills to save initial state           |
//+------------------------------------------------------------------+
void OnTrade()
  {
   // When a pending order fills and becomes a position, capture context
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!Position.SelectByIndex(i)) continue;
      if(Position.Symbol() != _Symbol) continue;
      if(Position.Magic()  != InpMagicNumber) continue;
      ulong tk = Position.Ticket();
      // If we haven't stored r_distance, derive from entry vs stop NOW
      if(!GlobalVariableCheck(GVKey(tk, "rDist")))
        {
         double r = MathAbs(Position.PriceOpen() - Position.StopLoss());
         GVWrite(tk, "initialStop", Position.StopLoss());
         GVWrite(tk, "rDist", r);
         GVWrite(tk, "origLot", Position.Volume());
         GVWrite(tk, "partials", 0);
         GVWrite(tk, "mid", ParseMidFromComment(Position.Comment()));
         GVWrite(tk, "target", Position.TakeProfit());
         GVWrite(tk, "isBear", Position.PositionType() == POSITION_TYPE_SELL ? 1 : 0);
         GVWrite(tk, "entryTime", (double)TimeCurrent());

         // Cancel any other pending order from the same setup (the other candidate)
         CancelAllOurPendingOrders();
        }
     }
  }
//+------------------------------------------------------------------+
