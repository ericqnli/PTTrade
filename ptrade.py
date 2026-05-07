# -*- coding: utf-8 -*-
# type: ignore
# pylint: disable=undefined-variable

import pandas as pd
import talib as ta

def initialize(context):
    """PTrade v2.7 优化版 - Fib + RSI + MACD背离 + 详细信号日志"""
    g.securities = ['159915.SZ', '512480.SS', '159938.SZ', '510630.SS', '512660.SS', '515070.SS']
    
    # ==================== 参数配置 ====================
    g.ma_short = 20
    g.ma_mid = 50
    g.ma_long = 100
    g.ma_trend = 200
    g.rsi_period = 14
    g.rsi_buy = 38
    g.rsi_sell = 82
    g.rsi_overheat = 72
    
    g.boll_period = 20
    g.boll_std = 2.0
    
    g.macd_fast = 12
    g.macd_slow = 26
    g.macd_signal = 9
    
    g.pullback_upper = 1.04
    g.pullback_lower = 0.89
    g.profit_threshold = 1.12
    g.trail_profit_threshold = 1.14
    g.trail_pullback_ma = 0.945
    g.atr_multiplier = 3.0
    g.max_stop_loss = 0.20
    g.tail_tighten_factor = 1.06
    g.volume_confirm = True
    g.max_pos_per_stock = 0.23
    g.max_total_pos = 0.92
    
    set_benchmark('000300.XSHG')
    run_daily(context, trade_logic, time='09:35')
    run_daily(context, tail_check, time='14:55')
    
    log.info("=== PTrade v2.7 优化版 已启动 ===")
    log.info("新增功能：Fib + RSI + 趋势 + 背离 详细信号日志")


# ====================== 核心指标函数 ======================
def get_multi_timeframe_indicators(security):
    """增强版多时间框架指标"""
    df_daily = get_history(260, '1d', ['high', 'low', 'close', 'volume'], security)
    if df_daily is None or len(df_daily) < 200:
        return {'valid': False, 'reason': '数据不足'}
    
    if not isinstance(df_daily.index, pd.DatetimeIndex):
        df_daily.index = pd.to_datetime(df_daily.index)
    
    df_weekly = (df_daily.resample('W-FRI').agg({'high':'max','low':'min','close':'last','volume':'sum'}).dropna())
    df_monthly = (df_daily.resample('ME').agg({'high':'max','low':'min','close':'last','volume':'sum'}).dropna())
    
    close_d = df_daily['close'].values
    high_d = df_daily['high'].values
    low_d = df_daily['low'].values
    vol_d = df_daily['volume'].values
    close_w = df_weekly['close'].values
    close_m = df_monthly['close'].values
    
    if len(close_w) < 30: close_w = close_d
    if len(close_m) < 12: close_m = close_d
    
    result = {
        'valid': True,
        'security': security,
        'last_date': df_daily.index[-1].strftime('%Y-%m-%d'),
        'price': close_d[-1],
        'ma20': ta.SMA(close_d, 20)[-1],
        'ma50': ta.SMA(close_d, 50)[-1],
        'ma100': ta.SMA(close_d, 100)[-1],
        'ma200': ta.SMA(close_d, 200)[-1],
        'rsi': ta.RSI(close_d, g.rsi_period)[-1],
        'rsi100': ta.RSI(close_d, 100)[-1],
        'atr': ta.ATR(high_d, low_d, close_d, 14)[-1],
        'bb_upper': ta.BBANDS(close_d, g.boll_period, nbdevup=g.boll_std)[0][-1],
        'bb_middle': ta.BBANDS(close_d, g.boll_period, nbdevup=g.boll_std)[1][-1],
        'bb_lower': ta.BBANDS(close_d, g.boll_period, nbdevup=g.boll_std)[2][-1],
        'macd': ta.MACD(close_d, g.macd_fast, g.macd_slow, g.macd_signal)[0][-1],
        'macd_signal': ta.MACD(close_d, g.macd_fast, g.macd_slow, g.macd_signal)[1][-1],
        'macd_hist': ta.MACD(close_d, g.macd_fast, g.macd_slow, g.macd_signal)[2][-1],
        'volume_ma': ta.SMA(vol_d, 20)[-1],
        'current_volume': vol_d[-1],
        'volume_ratio': vol_d[-1] / ta.SMA(vol_d, 20)[-1] if ta.SMA(vol_d, 20)[-1] > 0 else 1.0,
        'ma200_week': ta.SMA(close_w, 200)[-1] if len(close_w) >= 200 else close_w[-1],
        'trend_week_up': close_w[-1] > ta.SMA(close_w, 50)[-1] if len(close_w) >= 50 else True,
        'ma200_month': ta.SMA(close_m, 200)[-1] if len(close_m) >= 200 else close_m[-1],
        'trend_month_up': close_m[-1] > ta.SMA(close_m, 50)[-1] if len(close_m) >= 50 else True,
    }
    return result


def detect_macd_divergence(close_prices, macd_hist, lookback=35):
    """改进版MACD底背离检测"""
    if len(close_prices) < lookback or len(macd_hist) < lookback:
        return False
    price_low_idx = close_prices[-lookback:].argmin()
    macd_low_idx = macd_hist[-lookback:].argmin()
    if price_low_idx > 5 and macd_low_idx > 5:
        price_bottom1 = min(close_prices[-lookback:-5])
        macd_bottom1 = min(macd_hist[-lookback:-5])
        return (close_prices[-1] < price_bottom1 * 1.015 and
                macd_hist[-1] > macd_bottom1 * 0.80)
    return False


def calculate_fib_levels(df_daily):
    """斐波那契支撑位计算"""
    if len(df_daily) < 60:
        return None, None, None
    recent_high = df_daily['high'][-60:].max()
    recent_low = df_daily['low'][-60:].min()
    diff = recent_high - recent_low
    fib_382 = recent_high - diff * 0.382
    fib_500 = recent_high - diff * 0.500
    fib_618 = recent_high - diff * 0.618
    return fib_382, fib_618, fib_500


def is_buy_signal(price, ind, df_daily):
    """优化后买入信号判断 - Fib + RSI + 趋势 + 背离"""
    if not ind.get('valid'):
        return False, 0, []
    
    fib_382, fib_618, fib_500 = calculate_fib_levels(df_daily)
    score = 0
    reasons = []
    
    # 1. 多时间框架趋势
    trend_ok = (price >= ind['ma200'] * 0.935 and
                ind['ma20'] > ind['ma50'] and
                ind['trend_week_up'] and ind['trend_month_up'])
    if trend_ok:
        score += 25
        reasons.append(f"趋势向上 (周:{ind['trend_week_up']} 月:{ind['trend_month_up']})")
    
    # 2. 斐波那契支撑位
    near_fib = False
    if fib_618 and fib_618 * 0.985 <= price <= fib_618 * 1.025:
        score += 30
        reasons.append(f"61.8%黄金支撑 (当前价 {price:.2f} / Fib {fib_618:.2f})")
        near_fib = True
    elif fib_382 and fib_382 * 0.98 <= price <= fib_382 * 1.03:
        score += 20
        reasons.append(f"38.2%支撑 (当前价 {price:.2f} / Fib {fib_382:.2f})")
        near_fib = True
    elif fib_500 and fib_500 * 0.98 <= price <= fib_500 * 1.03:
        score += 15
        reasons.append(f"50%中位支撑 (当前价 {price:.2f} / Fib {fib_500:.2f})")
        near_fib = True
    
    # 3. RSI + MACD背离
    macd_div = detect_macd_divergence(df_daily['close'].values, [ind['macd_hist']] * len(df_daily))
    if ind['rsi'] <= 32:
        score += 20
        reasons.append(f"RSI极度超卖 ({ind['rsi']:.1f})")
    elif ind['rsi'] <= 40 and near_fib:
        score += 18
        reasons.append(f"RSI超卖 + Fib支撑 ({ind['rsi']:.1f})")
    elif ind['rsi'] <= 48 and macd_div:
        score += 22
        reasons.append(f"MACD底背离 (RSI {ind['rsi']:.1f})")
    
    # 4. 辅助确认
    if price >= ind['boll_lower'] * 0.97 and ind['volume_ratio'] >= 0.9:
        score += 10
        reasons.append("布林带下轨 + 放量")
    if ind['ma20'] * g.pullback_lower <= price <= ind['ma20'] * g.pullback_upper:
        score += 8
        reasons.append("MA20回撤到位")
    
    signal_ok = score >= 65 and trend_ok and near_fib
    return signal_ok, score, reasons


# ====================== 交易主逻辑 ======================
def trade_logic(context):
    portfolio = context.portfolio
    if portfolio.total_value < 10000:
        return
    
    indicators = {}
    daily_data = {}
    for sec in g.securities:
        indicators[sec] = get_multi_timeframe_indicators(sec)
        if indicators[sec].get('valid'):
            daily_data[sec] = get_history(60, '1d', ['high','low','close','volume'], sec)
    
    market_rsis = [ind.get('rsi100', 50) for ind in indicators.values() if ind.get('valid')]
    market_overheat = max(market_rsis) > g.rsi_overheat if market_rsis else False
    current_max_total = 0.65 if market_overheat else g.max_total_pos
    
    total_value = portfolio.total_value
    cash = portfolio.cash
    
    # ====================== 卖出优先 ======================
    for sec in g.securities:
        pos = portfolio.positions.get(sec)
        if not pos or pos.amount <= 0:
            continue
        ind = indicators.get(sec)
        if not ind.get('valid'):
            continue
        
        current_price = ind['price']
        avg_price = pos.avg_price
        profit_ratio = current_price / avg_price
        
        reason = None
        atr_ratio = ind['atr'] / current_price * g.atr_multiplier if ind['atr'] > 0 else 0.18
        dynamic_stop = min(g.max_stop_loss, atr_ratio)
        
        if current_price < avg_price * (1 - dynamic_stop):
            reason = f"ATR动态止损 (止损位 {avg_price*(1-dynamic_stop):.2f})"
        elif current_price < ind['boll_middle'] * 0.955 or current_price < ind['ma20'] * 0.905:
            reason = "破关键支撑"
        elif ind['rsi'] >= g.rsi_sell and profit_ratio > g.profit_threshold:
            reason = f"超买止盈 (RSI {ind['rsi']:.1f})"
        elif (profit_ratio > g.trail_profit_threshold and 
              current_price < ind['ma20'] * g.trail_pullback_ma):
            reason = "追踪止盈"
        
        if reason:
            order_target(sec, 0)
            log.info(f"【卖出执行】{sec} | 原因：{reason} | 价格 {current_price:.3f} | 盈亏 {(profit_ratio-1):.2%}")
    
    # ====================== 买入逻辑 ======================
    if (total_value - cash) / total_value >= current_max_total:
        return
        
    for sec in g.securities:
        if (total_value - cash) / total_value >= current_max_total:
            break
        if portfolio.positions.get(sec) and portfolio.positions[sec].amount > 0:
            continue
            
        ind = indicators.get(sec)
        if not ind.get('valid'):
            continue
        df_daily = daily_data.get(sec)
        if df_daily is None or len(df_daily) < 40:
            continue
            
        current_price = ind['price']
        buy_signal, signal_score, reasons = is_buy_signal(current_price, ind, df_daily)
        
        if buy_signal:
            log.info(f"【强买入信号】{sec} | 总分 {signal_score}/100 | 价格 {current_price:.3f}")
            for r in reasons:
                log.info(f"   └─ {r}")
            log.info("─" * 60)
            
            buy_value = min(cash * 0.48, total_value * g.max_pos_per_stock)
            if buy_value > 8000:
                order_value(sec, buy_value)
                log.info(f"【买入执行】{sec} | 金额 {buy_value:,.0f}")


def tail_check(context):
    """尾盘检查"""
    portfolio = context.portfolio
    if portfolio.total_value < 10000:
        return
    
    indicators = {sec: get_multi_timeframe_indicators(sec) for sec in g.securities}
    
    for sec in g.securities:
        pos = portfolio.positions.get(sec)
        if not pos or pos.amount <= 0:
            continue
        ind = indicators.get(sec)
        if not ind.get('valid'):
            continue
            
        current_price = ind['price']
        avg_price = pos.avg_price
        atr_ratio = ind['atr'] / current_price * g.atr_multiplier if ind['atr'] > 0 else 0.18
        dynamic_stop = min(g.max_stop_loss, atr_ratio)
        
        if current_price < avg_price * (1 - dynamic_stop * g.tail_tighten_factor):
            order_target(sec, 0)
            log.info(f"【尾盘止损】{sec} | 价格 {current_price:.3f}")
            continue
        
        if (current_price > avg_price * g.trail_profit_threshold and
            current_price < ind['ma20'] * g.trail_pullback_ma):
            order_target(sec, 0)
            log.info(f"【尾盘追踪止盈】{sec} | 价格 {current_price:.3f}")

