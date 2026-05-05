# -*- coding: utf-8 -*-
# type: ignore
# pylint: disable=undefined-variable
import pandas as pd
import talib as ta

def initialize(context):
    """PTrade v2.32 平衡版 - 取消趋势破位卖出 | ATR止损优化 + 防反复买卖"""
    g.securities = ['159915.SZ', '512480.SS', '159938.SZ', '510630.SS','512660.SS','515070.SS']  
    
    g.ma_short = 20
    g.ma_trend = 200
    g.rsi_period = 14
    
    # ==================== 核心参数 ====================
    g.rsi_buy = 38              
    g.pullback_upper = 1.04      
    g.pullback_lower = 0.89
    g.rsi_sell = 85
    g.profit_threshold = 1.12
    
    # ==================== 追踪止盈参数 ====================
    g.trail_profit_threshold = 1.12
    g.trail_pullback_ma = 0.95
    
    # ==================== 市场过热控制 ====================
    g.rsi_overheat = 70
    
    # ==================== ATR止损（核心保护）================
    g.atr_multiplier = 3.0      
    g.max_stop_loss = 0.22      
    g.tail_tighten_factor = 1.0 
    
    g.max_pos_per_stock = 0.20
    g.max_total_pos = 0.95
    g.stop_loss_ma = False      # ← 已关闭趋势破位卖出
    
    set_benchmark('000300.XSHG')
    
    run_daily(context, trade_logic, time='09:35')
    run_daily(context, tail_check, time='14:55')
    
    log.info("=== v2.32 平衡版 已启动（取消趋势破位卖出 + ATR 3.0倍 + 22%封顶）===")
    log.info("已解决买入规则1与卖出规则1矛盾 | 依赖ATR+追踪止盈防下行")

def trade_logic(context):
    portfolio = context.portfolio
    cash = portfolio.cash
    total_value = portfolio.total_value
    if total_value < 10000:
        return
    
    indicators = {sec: get_indicators(sec) for sec in g.securities}   # ← 这行现在安全了
    
    # 动态总仓位
    market_rsis = [ind.get('rsi_100', 50) for ind in indicators.values() if ind.get('valid')]
    market_overheat = max(market_rsis) > g.rsi_overheat if market_rsis else False
    current_max_total = 0.70 if market_overheat else g.max_total_pos
    
    current_pos_ratio = (total_value - cash) / total_value if total_value > 0 else 0.0
    
    # === 卖出优先（已移除趋势破位） ===
    for sec in g.securities:
        pos = portfolio.positions.get(sec)
        if not pos or pos.amount <= 0: 
            continue
            
        ind = indicators.get(sec)
        if not ind.get('valid', False): 
            continue
            
        df_today = get_history(2, '1d', ['close'], sec)
        if df_today is None or len(df_today) < 1: 
            continue
        
        current_price = df_today['close'].iloc[-1]
        avg_price = pos.avg_price
        profit_ratio = current_price / avg_price
        
        reason = None
        
        # 卖出1：ATR动态止损（主力保护）
        if ind['atr'] > 0:
            atr_ratio = ind['atr'] / current_price * g.atr_multiplier
            dynamic_stop = min(g.max_stop_loss, atr_ratio)
            if current_price < avg_price * (1 - dynamic_stop):
                reason = "ATR动态止损"
                log.info(f"【卖出触发 - ATR动态止损】{sec} | 价格 {current_price:.3f} | "
                         f"ATR%={ind['atr']/current_price*100:.2f}% | 动态止损={dynamic_stop:.4f} | "
                         f"持仓盈亏={profit_ratio:.4f} | RSI={ind['rsi']:.2f}")
        
        # 卖出2：超买止盈
        elif ind['rsi'] >= g.rsi_sell and current_price > avg_price * g.profit_threshold:
            reason = "超买止盈"
            log.info(f"【卖出触发 - 超买止盈】{sec} | 价格 {current_price:.3f} | "
                     f"RSI={ind['rsi']:.2f} | 持仓盈亏={profit_ratio:.4f}")
        
        # 卖出3：追踪止盈
        elif current_price > avg_price * g.trail_profit_threshold and \
             current_price < ind['ma_short'] * g.trail_pullback_ma:
            reason = "追踪止盈"
            log.info(f"【卖出触发 - 追踪止盈】{sec} | 价格 {current_price:.3f} | "
                     f"MA20={ind['ma_short']:.3f} | Pullback阈值={g.trail_pullback_ma} | "
                     f"持仓盈亏={profit_ratio:.4f} | RSI={ind['rsi']:.2f}")
        
        if reason:
            order_target(sec, 0)
            log.info(f"【卖出执行】{sec} | 原因：{reason} | 价格 {current_price:.3f} | "
                     f"持仓盈亏率={profit_ratio-1:.2%} | 当前总仓位={current_pos_ratio:.1%}")
            continue
    
    # === 买入（保持不变） ===
    for sec in g.securities:
        if (total_value - cash) / total_value >= current_max_total: 
            break
        ind = indicators.get(sec)
        if not ind.get('valid', False): 
            continue
        if portfolio.positions.get(sec) and portfolio.positions[sec].amount > 0: 
            continue
            
        df_today = get_history(2, '1d', ['close'], sec)
        if df_today is None or len(df_today) < 1: 
            continue
        
        current_price = df_today['close'].iloc[-1]
        
        if is_buy_signal(current_price, ind):
            ma_trend = ind['ma_trend']
            ma_short = ind['ma_short']
            rsi = ind['rsi']
            atr = ind['atr']
            
            price_vs_ma200 = current_price / ma_trend
            ma20_vs_ma200 = ma_short / ma_trend
            pullback_ratio = current_price / ma_short
            available_pos = current_max_total - current_pos_ratio
            
            log.info(f"【买入触发 - 详细条件】{sec} | "
                     f"价格 {current_price:.3f} | "
                     f"RSI(14)={rsi:6.2f} | "
                     f"ATR%={atr/current_price*100:5.2f}% | "
                     f"Price/MA200={price_vs_ma200:.4f} | "
                     f"MA20/MA200={ma20_vs_ma200:.4f} | "
                     f"Pullback={pullback_ratio:.4f} | "
                     f"当前总仓位={current_pos_ratio:6.1%} | "
                     f"可买入仓位={available_pos:6.1%} | "
                     f"市场过热={market_overheat}")
            
            buy_value = min(cash * 0.48, total_value * g.max_pos_per_stock)
            if buy_value > 8000:
                order_value(sec, buy_value)
                log.info(f"【买入执行】{sec} | 价格 {current_price:.3f} | "
                         f"金额 {buy_value:,.0f} | RSI={rsi:.1f} | 当前总仓位={current_pos_ratio:.1%}")

def get_indicators(security):
    """从 2.31 版本完整复制，确保返回 dict"""
    df = get_history(220, '1d', ['high', 'low', 'close'], security)
    if df is None or len(df) < 200:
        return {'valid': False}
    
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    
    result = {
        'ma_short': ta.SMA(close, g.ma_short)[-1],
        'ma_trend': ta.SMA(close, g.ma_trend)[-1],
        'rsi':      ta.RSI(close, g.rsi_period)[-1],
        'rsi_100':  ta.RSI(close, 100)[-1],
        'atr':      ta.ATR(high, low, close, 14)[-1] if len(close) > 14 else 0,
        'valid':    True
    }
    return result

def is_buy_signal(price, ind):
    if not ind.get('valid'): 
        return False
    trend_ok = (price >= ind['ma_trend'] * 0.95 and ind['ma_short'] >= ind['ma_trend'] * 0.93)
    pullback_ok = ind['ma_short'] * g.pullback_lower <= price <= ind['ma_short'] * g.pullback_upper
    oversold_ok = ind['rsi'] <= g.rsi_buy
    return trend_ok and pullback_ok and oversold_ok

def tail_check(context):
    portfolio = context.portfolio
    if portfolio.total_value < 10000: 
        return
    
    indicators = {sec: get_indicators(sec) for sec in g.securities}
    
    for sec in g.securities:
        pos = portfolio.positions.get(sec)
        if not pos or pos.amount <= 0: 
            continue
        ind = indicators.get(sec)
        if not ind.get('valid', False): 
            continue
            
        df_today = get_history(2, '1d', ['close'], sec)
        if df_today is None or len(df_today) < 1: 
            continue
        current_price = df_today['close'].iloc[-1]
        
        # ATR动态止损（尾盘不收紧）
        atr_ratio = ind['atr'] / current_price * g.atr_multiplier if ind['atr'] > 0 else 0.16
        dynamic_stop = min(g.max_stop_loss, atr_ratio)
        
        if current_price < pos.avg_price * (1 - dynamic_stop * g.tail_tighten_factor):
            order_target(sec, 0)
            log.info(f"【尾盘-强化止损】{sec} | 价格 {current_price:.3f} | ATR止损 {dynamic_stop*100:.1f}%")
            continue
        
        # 尾盘追踪止盈
        if current_price > pos.avg_price * g.trail_profit_threshold and current_price < ind['ma_short'] * g.trail_pullback_ma:
            order_target(sec, 0)
            log.info(f"【尾盘-追踪止盈】{sec} | 价格 {current_price:.3f}")