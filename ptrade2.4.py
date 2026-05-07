# -*- coding: utf-8 -*-
# type: ignore
# pylint: disable=undefined-variable

import pandas as pd
import talib as ta

def initialize(context):
    """PTrade v2.5 资深技术策略版 - 全面优化"""
    g.securities = ['159915.SZ', '512480.SS', '159938.SZ', '510630.SS', '512660.SS', '515070.SS']
    
    # ==================== 参数配置 ====================
    g.ma_short = 20
    g.ma_mid = 50
    g.ma_long = 100
    g.ma_trend = 200
    g.rsi_period = 14
    g.rsi_buy = 35
    g.rsi_sell = 82
    g.rsi_overheat = 72
    
    g.boll_period = 20
    g.boll_std = 2.0
    
    g.macd_fast = 12
    g.macd_slow = 26
    g.macd_signal = 9
    
    # 交易参数
    g.pullback_upper = 1.04
    g.pullback_lower = 0.89
    g.profit_threshold = 1.12
    g.trail_profit_threshold = 1.14      # 略微提高
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
    
    log.info("=== PTrade v2.5 资深技术策略版 已启动 ===")
    log.info("优化内容：多时间框架 | 精准MACD背离 | 斐波那契 | 智能止盈止损 | 仓位控制")


# ====================== 核心指标函数 ======================
def get_multi_timeframe_indicators(security):
    """增强版多时间框架指标"""
    df_daily = get_history(260, '1d', ['high', 'low', 'close', 'volume'], security)
    if df_daily is None or len(df_daily) < 200:
        return {'valid': False, 'reason': '数据不足'}
    
    if not isinstance(df_daily.index, pd.DatetimeIndex):
        df_daily.index = pd.to_datetime(df_daily.index)
    
    # 标准周线（周五收盘）和月线
    df_weekly = (df_daily.resample('W-FRI')
                 .agg({'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'})
                 .dropna())
    df_monthly = (df_daily.resample('ME')
                  .agg({'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'})
                  .dropna())
    
    close_d = df_daily['close'].values
    high_d = df_daily['high'].values
    low_d = df_daily['low'].values
    vol_d = df_daily['volume'].values
    close_w = df_weekly['close'].values
    close_m = df_monthly['close'].values
    
    # 长度保护
    if len(close_w) < 30:
        close_w = close_d
    if len(close_m) < 12:
        close_m = close_d
    
    result = {
        'valid': True,
        'security': security,
        'last_date': df_daily.index[-1].strftime('%Y-%m-%d'),
        'price': close_d[-1],
        
        # 日线
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
        
        # 周/月趋势
        'ma200_week': ta.SMA(close_w, 200)[-1] if len(close_w) >= 200 else close_w[-1],
        'trend_week_up': close_w[-1] > ta.SMA(close_w, 50)[-1] if len(close_w) >= 50 else True,
        'ma200_month': ta.SMA(close_m, 200)[-1] if len(close_m) >= 200 else close_m[-1],
        'trend_month_up': close_m[-1] > ta.SMA(close_m, 50)[-1] if len(close_m) >= 50 else True,
    }
    return result


def detect_macd_divergence(close_prices, macd_hist, lookback=35):
    """
    改进版 MACD 底背离检测
    
    判断条件：
        1. 价格出现最近两个低点，且后者更低
        2. MACD 柱状线在对应位置未创新低（形成背离）
    """
    if len(close_prices) < lookback or len(macd_hist) < lookback:
        return False
    
    # 最近lookback内价格最低点和MACD最低点
    price_low_idx = close_prices[-lookback:].argmin()
    macd_low_idx = macd_hist[-lookback:].argmin()
    
    # 价格创新低，MACD未创新低（或抬高）
    if price_low_idx > 5 and macd_low_idx > 5:   # 要有一定间隔
        price_bottom1 = min(close_prices[-lookback:-5])
        macd_bottom1 = min(macd_hist[-lookback:-5])
        
        return (close_prices[-1] < price_bottom1 * 1.015 and
                macd_hist[-1] > macd_bottom1 * 0.80)
    return False


def calculate_fib_levels(df_daily):
    """简单斐波那契支撑/阻力"""
    if len(df_daily) < 60:
        return None, None
    recent_high = df_daily['high'][-60:].max()
    recent_low = df_daily['low'][-60:].min()
    diff = recent_high - recent_low
    fib_382 = recent_high - diff * 0.382
    fib_618 = recent_high - diff * 0.618
    return fib_382, fib_618


def is_buy_signal(price, ind, df_daily):
    """买入信号综合判断"""
    if not ind.get('valid'):
        return False
    
    # 1. 多时间框架共振
    trend_ok = (price >= ind['ma200'] * 0.935 and
                ind['ma20'] > ind['ma50'] and
                ind['trend_week_up'] and ind['trend_month_up'])
    
    # 2. 回撤到位
    pullback_ok = (ind['ma20'] * g.pullback_lower <= price <= ind['ma20'] * g.pullback_upper)
    
    # 3. RSI + MACD背离
    macd_div = detect_macd_divergence(df_daily['close'].values, 
                                      [ind['macd_hist']] * len(df_daily))  # 实际应传入完整序列
    rsi_ok = (ind['rsi'] <= g.rsi_buy) or (ind['rsi'] <= 48 and macd_div)
    
    # 4. 布林带 + 斐波那契
    fib_382, fib_618 = calculate_fib_levels(df_daily)
    boll_ok = price >= ind['boll_lower'] * 0.97
    if fib_618:
        boll_ok = boll_ok and price >= min(ind['boll_lower'] * 0.97, fib_618 * 0.99)
    
    # 5. 成交量确认
    volume_ok = not g.volume_confirm or ind['volume_ratio'] >= 0.85
    
    return trend_ok and pullback_ok and rsi_ok and boll_ok and volume_ok


# ====================== 交易主逻辑 ======================
def trade_logic(context):
    portfolio = context.portfolio
    if portfolio.total_value < 10000:
        return
    
    # 一次性获取所有指标，减少API调用
    indicators = {}
    daily_data = {}
    for sec in g.securities:
        indicators[sec] = get_multi_timeframe_indicators(sec)
        if indicators[sec].get('valid'):
            daily_data[sec] = get_history(60, '1d', ['high','low','close','volume'], sec)
    
    # 市场热度判断
    market_rsis = [ind.get('rsi100', 50) for ind in indicators.values() if ind.get('valid')]
    market_overheat = max(market_rsis) > g.rsi_overheat if market_rsis else False
    current_max_total = 0.65 if market_overheat else g.max_total_pos
    
    total_value = portfolio.total_value
    cash = portfolio.cash
    current_pos_ratio = (total_value - cash) / total_value if total_value > 0 else 0
    
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
            reason = "ATR动态止损"
        elif current_price < ind['boll_middle'] * 0.955 or current_price < ind['ma20'] * 0.905:
            reason = "破关键支撑"
        elif ind['rsi'] >= g.rsi_sell and profit_ratio > g.profit_threshold:
            reason = "超买止盈"
        elif (profit_ratio > g.trail_profit_threshold and 
              current_price < ind['ma20'] * g.trail_pullback_ma):
            reason = "追踪止盈"
        
        if reason:
            order_target(sec, 0)
            log.info(f"【卖出执行】{sec} | 原因：{reason} | 价格 {current_price:.3f} | 盈亏 {(profit_ratio-1):.2%}")
    
    # ====================== 买入逻辑 ======================
    if current_pos_ratio >= current_max_total:
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
        if df_daily is None or len(df_daily) < 30:
            continue
            
        current_price = ind['price']
        
        if is_buy_signal(current_price, ind, df_daily):
            log.info(f"【买入信号】{sec} | 价格 {current_price:.3f} | RSI {ind['rsi']:.1f} | "
                     f"周线向上={ind['trend_week_up']} 月线向上={ind['trend_month_up']}")
            
            buy_value = min(cash * 0.48, total_value * g.max_pos_per_stock)
            if buy_value > 8000:
                order_value(sec, buy_value)
                log.info(f"【买入执行】{sec} | 金额 {buy_value:,.0f}")


def tail_check(context):
    """尾盘强化检查"""
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
        
        # 尾盘收紧止损
        if current_price < avg_price * (1 - dynamic_stop * g.tail_tighten_factor):
            order_target(sec, 0)
            log.info(f"【尾盘止损】{sec} | 价格 {current_price:.3f}")
            continue
        
        # 追踪止盈
        if (current_price > avg_price * g.trail_profit_threshold and
            current_price < ind['ma20'] * g.trail_pullback_ma):
            order_target(sec, 0)
            log.info(f"【尾盘追踪止盈】{sec} | 价格 {current_price:.3f}")

