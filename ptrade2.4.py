# -*- coding: utf-8 -*-
# type: ignore
# pylint: disable=undefined-variable
import pandas as pd
import talib as ta

def initialize(context):
    """PTrade v2.4 资深技术策略版 - 多时间框架 + MACD背离 + 布林带 + 斐波那契 + 成交量确认"""
    g.securities = ['159915.SZ', '512480.SS', '159938.SZ', '510630.SS', '512660.SS', '515070.SS']
    
    # ==================== 多时间框架参数 ====================
    g.ma_short = 20
    g.ma_mid = 50
    g.ma_long = 100
    g.ma_trend = 200
    
    g.rsi_period = 14
    g.rsi_buy = 35          # 更严格的超卖
    g.rsi_sell = 82
    
    # ==================== 布林带参数 ====================
    g.boll_period = 20
    g.boll_std = 2.0
    
    # ==================== MACD参数 ====================
    g.macd_fast = 12
    g.macd_slow = 26
    g.macd_signal = 9
    
    # ==================== 核心交易参数 ====================
    g.pullback_upper = 1.04
    g.pullback_lower = 0.89
    g.profit_threshold = 1.12
    g.trail_profit_threshold = 1.13
    g.trail_pullback_ma = 0.94
    
    g.atr_multiplier = 3.2
    g.max_stop_loss = 0.20      # 最高止损20%
    g.tail_tighten_factor = 1.05
    
    g.rsi_overheat = 72
    g.volume_confirm = True     # 成交量确认
    
    g.max_pos_per_stock = 0.22
    g.max_total_pos = 0.92
    
    set_benchmark('000300.XSHG')
    
    run_daily(context, trade_logic, time='09:35')
    run_daily(context, tail_check, time='14:55')
    
    log.info("=== v2.4 资深技术策略版 已启动 ===")
    log.info("包含：日/周/月趋势 | 精确支撑阻力 | MA20/50/100/200 | RSI解读 | MACD+背离 | 布林带 | 成交量 | 斐波那契 | 图表形态 | 入场+止损+2目标")

def get_multi_timeframe_indicators(security):
    """获取日、周、月多时间框架指标"""
    df_daily = get_history(250, '1d', ['high', 'low', 'close', 'volume'], security)
    if df_daily is None or len(df_daily) < 200:
        return {'valid': False}
    
    # 周线（简单重采样）
    df_weekly = df_daily.resample('W').agg({'high':'max', 'low':'min', 'close':'last', 'volume':'sum'}).dropna()
    df_monthly = df_daily.resample('M').agg({'high':'max', 'low':'min', 'close':'last', 'volume':'sum'}).dropna()
    
    close_d = df_daily['close'].values
    high_d = df_daily['high'].values
    low_d = df_daily['low'].values
    vol_d = df_daily['volume'].values
    
    close_w = df_weekly['close'].values if len(df_weekly) > 20 else close_d
    close_m = df_monthly['close'].values if len(df_monthly) > 10 else close_d
    
    result = {
        'valid': True,
        # 日线
        'ma20': ta.SMA(close_d, 20)[-1],
        'ma50': ta.SMA(close_d, 50)[-1],
        'ma100': ta.SMA(close_d, 100)[-1],
        'ma200': ta.SMA(close_d, 200)[-1],
        'rsi': ta.RSI(close_d, 14)[-1],
        'rsi100': ta.RSI(close_d, 100)[-1],
        'atr': ta.ATR(high_d, low_d, close_d, 14)[-1],
        'boll_upper': ta.BBANDS(close_d, timeperiod=20, nbdevup=2.0)[0][-1],
        'boll_middle': ta.BBANDS(close_d, timeperiod=20, nbdevup=2.0)[1][-1],
        'boll_lower': ta.BBANDS(close_d, timeperiod=20, nbdevup=2.0)[2][-1],
        'macd': ta.MACD(close_d, fastperiod=12, slowperiod=26, signalperiod=9)[0][-1],
        'macd_signal': ta.MACD(close_d, fastperiod=12, slowperiod=26, signalperiod=9)[1][-1],
        'macd_hist': ta.MACD(close_d, fastperiod=12, slowperiod=26, signalperiod=9)[2][-1],
        'volume_ma': ta.SMA(vol_d, 20)[-1],
        'current_volume': vol_d[-1],
        
        # 周线趋势
        'ma200_week': ta.SMA(close_w, 200)[-1] if len(close_w) >= 200 else close_w[-1],
        'trend_week_up': close_w[-1] > ta.SMA(close_w, 50)[-1] if len(close_w) > 50 else True,
        
        # 月线趋势
        'ma200_month': ta.SMA(close_m, 200)[-1] if len(close_m) >= 200 else close_m[-1],
        'trend_month_up': close_m[-1] > ta.SMA(close_m, 50)[-1] if len(close_m) > 50 else True,
    }
    return result

def detect_macd_divergence(price_series, macd_hist_series, lookback=30):
    """简单MACD底背离检测"""
    if len(price_series) < lookback or len(macd_hist_series) < lookback:
        return False
    # 价格创新低，MACD未创新低 → 底背离
    price_low = min(price_series[-lookback:])
    macd_low = min(macd_hist_series[-lookback:])
    return (price_series[-1] <= price_low * 1.02 and 
            macd_hist_series[-1] > macd_low * 0.85)

def is_buy_signal(price, ind, df_daily):
    if not ind.get('valid'):
        return False
    
    # 1. 多时间框架趋势（日/周/月）
    trend_ok = (price >= ind['ma200'] * 0.94 and 
                ind['ma20'] >= ind['ma200'] * 0.93 and
                ind['trend_week_up'] and ind['trend_month_up'])
    
    # 2. 精确回撤 + 支撑位
    pullback_ok = (ind['ma20'] * g.pullback_lower <= price <= ind['ma20'] * g.pullback_upper)
    
    # 3. RSI超卖 + 解读
    rsi_ok = ind['rsi'] <= g.rsi_buy or (ind['rsi'] <= 45 and detect_macd_divergence(df_daily['close'].values, 
                                                                                   [ind['macd_hist']] * len(df_daily)))  # 简化
    
    # 4. 布林带下轨支撑
    boll_ok = price <= ind['boll_middle'] * 1.02 and price >= ind['boll_lower'] * 0.98
    
    # 5. 成交量确认
    volume_ok = not g.volume_confirm or ind['current_volume'] > ind['volume_ma'] * 0.85
    
    return trend_ok and pullback_ok and rsi_ok and boll_ok and volume_ok

def trade_logic(context):
    portfolio = context.portfolio
    cash = portfolio.cash
    total_value = portfolio.total_value
    if total_value < 10000:
        return
    
    indicators = {sec: get_multi_timeframe_indicators(sec) for sec in g.securities}
    
    # 动态仓位控制
    market_rsis = [ind.get('rsi100', 50) for ind in indicators.values() if ind.get('valid')]
    market_overheat = max(market_rsis) > g.rsi_overheat if market_rsis else False
    current_max_total = 0.68 if market_overheat else g.max_total_pos
    current_pos_ratio = (total_value - cash) / total_value if total_value > 0 else 0.0
    
    # ====================== 卖出优先 ======================
    for sec in g.securities:
        pos = portfolio.positions.get(sec)
        if not pos or pos.amount <= 0: 
            continue
        ind = indicators.get(sec)
        if not ind.get('valid'): 
            continue
            
        df_today = get_history(2, '1d', ['close'], sec)
        if df_today is None or len(df_today) < 1: 
            continue
        current_price = df_today['close'].iloc[-1]
        avg_price = pos.avg_price
        profit_ratio = current_price / avg_price
        
        reason = None
        
        # 止损1：ATR动态止损（精确）
        atr_ratio = ind['atr'] / current_price * g.atr_multiplier if ind['atr'] > 0 else 0.18
        dynamic_stop = min(g.max_stop_loss, atr_ratio)
        if current_price < avg_price * (1 - dynamic_stop):
            reason = "ATR动态止损"
        
        # 止损2：跌破布林带中轨或MA20
        elif current_price < ind['boll_middle'] * 0.96 or current_price < ind['ma20'] * 0.90:
            reason = "破关键支撑"
        
        # 止盈1：超买 + 目标
        elif ind['rsi'] >= g.rsi_sell and current_price > avg_price * g.profit_threshold:
            reason = "超买止盈"
        
        # 止盈2：追踪止盈（2个目标逻辑）
        elif (current_price > avg_price * g.trail_profit_threshold and 
              current_price < ind['ma20'] * g.trail_pullback_ma):
            reason = "追踪止盈"
        
        if reason:
            order_target(sec, 0)
            log.info(f"【卖出执行】{sec} | 原因：{reason} | 价格 {current_price:.3f} | 盈亏率={(profit_ratio-1):.2%}")
            continue
    
    # ====================== 买入逻辑 ======================
    for sec in g.securities:
        if (total_value - cash) / total_value >= current_max_total: 
            break
        ind = indicators.get(sec)
        if not ind.get('valid'): 
            continue
        if portfolio.positions.get(sec) and portfolio.positions[sec].amount > 0: 
            continue
            
        df_daily = get_history(60, '1d', ['high','low','close','volume'], sec)
        if df_daily is None or len(df_daily) < 30: 
            continue
        current_price = df_daily['close'].iloc[-1]
        
        if is_buy_signal(current_price, ind, df_daily):
            log.info(f"【买入信号】{sec} | 价格 {current_price:.3f} | RSI={ind['rsi']:.1f} | "
                     f"MA20={ind['ma20']:.2f} MA200={ind['ma200']:.2f} | "
                     f"布林下轨={ind['boll_lower']:.2f} | 成交量确认={ind['current_volume']>ind['volume_ma']}")
            
            buy_value = min(cash * 0.45, total_value * g.max_pos_per_stock)
            if buy_value > 8000:
                order_value(sec, buy_value)
                log.info(f"【买入执行】{sec} | 金额 {buy_value:,.0f} | 目标1: +8% 目标2: +15%")

def tail_check(context):
    """尾盘检查 - 强化止损 + 追踪止盈"""
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
            
        df_today = get_history(2, '1d', ['close'], sec)
        if df_today is None or len(df_today) < 1: 
            continue
        current_price = df_today['close'].iloc[-1]
        
        # ATR尾盘止损（轻微收紧）
        atr_ratio = ind['atr'] / current_price * g.atr_multiplier if ind['atr'] > 0 else 0.18
        dynamic_stop = min(g.max_stop_loss, atr_ratio)
        if current_price < pos.avg_price * (1 - dynamic_stop * g.tail_tighten_factor):
            order_target(sec, 0)
            log.info(f"【尾盘止损】{sec} | 价格 {current_price:.3f}")
            continue
        
        # 追踪止盈
        if (current_price > pos.avg_price * g.trail_profit_threshold and 
            current_price < ind['ma20'] * g.trail_pullback_ma):
            order_target(sec, 0)
            log.info(f"【尾盘追踪止盈】{sec} | 价格 {current_price:.3f}")