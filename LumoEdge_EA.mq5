//+------------------------------------------------------------------+
//|                                                LumoEdge_EA.mq5   |
//|                                  Powered by: Lumo Edge           |
//|                                  Owner: Gontse                   |
//|               Strategy: EMA 50 / EMA 200 Scanner & Auto-Close    |
//+------------------------------------------------------------------+
#property copyright "Powered by Lumo Edge | Owner: Gontse"
#property link      "https://lumoedge.trade"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
CTrade trade;

//--- Input Parameters
input group "=== LUMO EDGE BRANDING ==="
input string   InpOwner              = "Gontse";              // Bot Owner
input string   InpBrand              = "Lumo Edge";           // Powered By

input group "=== STRATEGY SETTINGS (EMA) ==="
input int      InpFastEMA            = 50;                    // Fast EMA Period
input int      InpSlowEMA            = 200;                   // Slow EMA Period
input ENUM_TIMEFRAMES InpTimeframe   = PERIOD_M5;             // Strategy Timeframe

input group "=== RISK & ORDER SETTINGS ==="
input double   InpLotSize            = 0.01;                  // Trade Lot Size
input double   InpStopLossPips       = 25.0;                  // Stop Loss in Pips
input ulong    InpMagicNumber        = 786999;                // Magic Number

input group "=== INSTANT PROFIT TAKER ==="
input double   InpMinProfitUSD       = 0.50;                  // Close immediately when Profit >= USD
input bool     InpAutoReopen         = true;                  // Open new trade after closing profit

//--- Indicator Handles
int handle_ema_fast;
int handle_ema_slow;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagicNumber);

   handle_ema_fast = iMA(_Symbol, InpTimeframe, InpFastEMA, 0, MODE_EMA, PRICE_CLOSE);
   handle_ema_slow = iMA(_Symbol, InpTimeframe, InpSlowEMA, 0, MODE_EMA, PRICE_CLOSE);

   if(handle_ema_fast == INVALID_HANDLE || handle_ema_slow == INVALID_HANDLE)
   {
      Print("[-] Lumo Edge: Error creating indicator handles");
      return INIT_FAILED;
   }

   Print("=================================================");
   Print("  LUMO EDGE FOREX BOT INITIALIZED                ");
   Print("  Powered by: ", InpBrand, " | Owner: ", InpOwner);
   Print("  Strategy  : EMA ", InpFastEMA, " / EMA ", InpSlowEMA);
   Print("=================================================");

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(handle_ema_fast);
   IndicatorRelease(handle_ema_slow);
   Print("[*] Lumo Edge Bot Deinitialized.");
}

//+------------------------------------------------------------------+
//| Check and Close in-profit positions                              |
//+------------------------------------------------------------------+
int ManageProfitTrades()
{
   int closed = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0)
      {
         if(PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
         {
            double profit = PositionGetDouble(POSITION_PROFIT);
            if(profit >= InpMinProfitUSD)
            {
               Print("[$$$] [LUMO EDGE PROFIT SECURED] Closing Ticket #", ticket, " with Profit: $", profit);
               if(trade.PositionClose(ticket))
               {
                  closed++;
               }
            }
         }
      }
   }
   return closed;
}

//+------------------------------------------------------------------+
//| Count active positions for this symbol & magic                   |
//+------------------------------------------------------------------+
int CountOpenPositions()
{
   int count = 0;
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0)
      {
         if(PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
         {
            count++;
         }
      }
   }
   return count;
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   // Step 1: Check if any trade is in profit and close it immediately
   int closed_trades = ManageProfitTrades();

   // Step 2: Check if we already have an active trade running on this symbol
   if(CountOpenPositions() > 0)
   {
      return; // Wait until current position closes
   }

   // Step 3: Fetch EMA Values
   double ema_fast[3];
   double ema_slow[3];

   if(CopyBuffer(handle_ema_fast, 0, 0, 3, ema_fast) < 3) return;
   if(CopyBuffer(handle_ema_slow, 0, 0, 3, ema_slow) < 3) return;

   // ema_fast[2] is candle index 0 (current), [1] is candle index 1 (closed), [0] is candle index 2
   double fast_curr = ema_fast[1];
   double fast_prev = ema_fast[0];
   double slow_curr = ema_slow[1];
   double slow_prev = ema_slow[0];

   MqlTick last_tick;
   if(!SymbolInfoTick(_Symbol, last_tick)) return;

   // Strategy Logic:
   // Bullish crossover / Uptrend: EMA 50 crossed above EMA 200 or Fast > Slow
   bool golden_cross = (fast_prev <= slow_prev && fast_curr > slow_curr);
   bool death_cross  = (fast_prev >= slow_prev && fast_curr < slow_curr);
   bool uptrend      = (fast_curr > slow_curr && last_tick.ask > fast_curr);
   bool downtrend    = (fast_curr < slow_curr && last_tick.bid < fast_curr);

   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   if(golden_cross || uptrend)
   {
      double sl = (InpStopLossPips > 0) ? NormalizeDouble(last_tick.ask - (InpStopLossPips * 10 * point), digits) : 0;
      trade.Buy(InpLotSize, _Symbol, last_tick.ask, sl, 0, "Lumo Edge Buy");
      Print("[+] [LUMO EDGE] Opened BUY on ", _Symbol, " at ", last_tick.ask);
   }
   else if(death_cross || downtrend)
   {
      double sl = (InpStopLossPips > 0) ? NormalizeDouble(last_tick.bid + (InpStopLossPips * 10 * point), digits) : 0;
      trade.Sell(InpLotSize, _Symbol, last_tick.bid, sl, 0, "Lumo Edge Sell");
      Print("[+] [LUMO EDGE] Opened SELL on ", _Symbol, " at ", last_tick.bid);
   }
}
//+------------------------------------------------------------------+
