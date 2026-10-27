# -*- coding: utf-8 -*-
"""
策略名称: QA 日线趋势策略
版本: v2.0
更新日期: 2026-10-27
策略说明: 日线 MA5 上穿 MA10 金叉建仓, 死叉减半, 破位清仓
主要变更:
- 取消首日无条件建仓, 买卖只按已收盘日线信号
- 底仓不参与买卖, 每次买入固定股数
- 死叉卖出策略仓一半, 破位或最高价回撤 12% 清掉策略仓
- 收盘输出参数和当前状态
"""

import pandas as pd

# ============== 策略版本 ==============
STRATEGY_NAME = "QA"
STRATEGY_VERSION = "v2.0"
# ======================================

g = type('G', (), {})()

def initialize(context):
    log.info(f"=== {STRATEGY_NAME} {STRATEGY_VERSION}（日线趋势：金叉建仓，死叉减半，破位清仓） ===")

    # ==================== 参数定义 ====================
    g.security_list = ['603311.SS']
    g.timeframe = '1d'
    g.strategy_mode = 'right'

    g.ma_fast = 5
    g.ma_slow = 10
    # 买入 RSI 上限 70→80，避免强趋势金叉被滤掉
    g.rsi_max_for_buy = 80
    g.dmi_period = 14
    g.adx_min = 20
    g.macd_fast, g.macd_slow, g.macd_signal = 12, 26, 9
    # 策略仓市值上限。底仓不计入。每次金叉买入固定股数
    g.max_position_pct = 0.35
    g.add_once = 200
    g.lot_size = 100
    g.order_cash_buffer = 1.1

    # 只过滤买入。卖出不再要求放量，避免缩量阴跌卖不掉
    g.volume_confirm_mult_buy = 0.8

    g.sell_ratio = 0.5
    # 从策略仓最高价回撤该比例，卖掉策略仓。底仓不动。不用 ATR
    g.trail_pct = 0.12

    g.rsi_period = 14
    g.last_golden_cross_date = None
    g.last_death_cross_date = None
    g.entry_high = {}
    g.base_amount = {}

    set_universe(g.security_list)

    if not is_trade():
        context.portfolio.cash = 1000000

    log.info(f"买入量能倍数: {g.volume_confirm_mult_buy} | 每次买入: {g.add_once} 股 | "
             f"策略仓上限: {g.max_position_pct:.0%} | 死叉卖出比例: {g.sell_ratio} | 回撤止损: {g.trail_pct:.0%}")

# ==================== 数据 & 指标 ====================
def get_daily_data(stock, count=80):
    # include 默认 False：只要已收盘日线
    return get_history(count, g.timeframe, ['open', 'high', 'low', 'close', 'volume'], stock)

def _bar_date(value):
    if hasattr(value, 'date') and not isinstance(value, str):
        return value.date()
    return pd.Timestamp(value).date()

def _context_date(context):
    dt = getattr(context, 'current_dt', None)
    if dt is None:
        blotter = getattr(context, 'blotter', None)
        dt = getattr(blotter, 'current_dt', None) if blotter is not None else None
    if dt is None:
        return None
    return _bar_date(dt)

def drop_unclosed_daily(df, context):
    if df is None or len(df) == 0:
        return df
    today = _context_date(context)
    if today is None:
        return df
    try:
        last_date = _bar_date(df.index[-1])
    except Exception:
        return df
    if last_date >= today:
        return df.iloc[:-1]
    return df

def _bar_field(data, stock, name):
    try:
        bar = data[stock]
    except Exception:
        return None
    value = getattr(bar, name, None)
    if value is None:
        try:
            value = bar[name]
        except Exception:
            return None
    if value is None or pd.isna(value) or value <= 0:
        return None
    return float(value)

def latest_price(data, stock, df):
    for name in ('price', 'close'):
        value = _bar_field(data, stock, name)
        if value is not None:
            return value
    return float(df['close'].iloc[-1])

def latest_high(data, stock, df, price):
    value = _bar_field(data, stock, 'high')
    if value is not None:
        return max(value, price)
    return max(float(df['high'].iloc[-1]), price)

def calc_rsi(df, period=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calc_dmi(df, period=14):
    """Wilder DMI。平滑真实波幅只作 +DI/-DI 的分母，不参与止损。"""
    high = df['high']
    low = df['low']
    close = df['close']
    up_move = high.diff()
    down_move = low.shift() - low
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    alpha = 1.0 / period
    smooth_tr = tr.ewm(alpha=alpha, adjust=False).mean().replace(0, float('nan'))
    plus_di = 100 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / smooth_tr
    minus_di = 100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / smooth_tr
    di_sum = (plus_di + minus_di).replace(0, float('nan'))
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    adx = dx.ewm(alpha=alpha, adjust=False).mean()
    return plus_di, minus_di, adx

def _dmi_now(df):
    plus_di, minus_di, adx = calc_dmi(df, g.dmi_period)
    values = (plus_di.iloc[-1], minus_di.iloc[-1], adx.iloc[-2], adx.iloc[-1])
    if any(pd.isna(v) for v in values):
        return None
    return values

def calc_macd(df):
    ema_fast = df['close'].ewm(span=g.macd_fast, adjust=False).mean()
    ema_slow = df['close'].ewm(span=g.macd_slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=g.macd_signal, adjust=False).mean()
    return dif, dea

def calc_ma(df, period=200):
    return df['close'].rolling(window=period).mean()

def _cross_date(df):
    try:
        return _bar_date(df.index[-1])
    except Exception:
        return df.index[-1]

def _ma_pair(df):
    ma_fast = calc_ma(df, g.ma_fast)
    ma_slow = calc_ma(df, g.ma_slow)
    values = (ma_fast.iloc[-2], ma_fast.iloc[-1], ma_slow.iloc[-2], ma_slow.iloc[-1])
    if any(pd.isna(v) for v in values):
        return None
    return values

def _volume_ok(df, mult):
    vol_avg = df['volume'].rolling(5).mean().shift(1).iloc[-1]
    vol_now = df['volume'].iloc[-1]
    if pd.isna(vol_avg) or vol_avg <= 0 or pd.isna(vol_now):
        return False
    return vol_now > vol_avg * mult

def account_value(context, position_value):
    total = getattr(context.portfolio, 'portfolio_value', None)
    if total is None or pd.isna(total) or total <= 0:
        total = context.portfolio.cash + position_value
    return float(total)

def round_lot(shares):
    lot = int(g.lot_size)
    if shares <= 0 or lot <= 0:
        return 0
    return int(shares / lot) * lot

def remember_base(stock, current_pos):
    """本次运行第一次见到的持仓记为底仓，之后的买卖都不包含它。"""
    if stock not in g.base_amount:
        g.base_amount[stock] = current_pos
        log.info(f"[{stock}] 记录底仓 {current_pos} 股")
    return g.base_amount[stock]

def strategy_amount(stock, current_pos):
    base = remember_base(stock, current_pos)
    return max(0, current_pos - base)

def fixed_buy_amount(tradable, price, cash, total_value):
    """买入固定股数。只按策略仓检查市值上限，底仓不计入。"""
    buy_amount = g.add_once
    if buy_amount <= 0 or price <= 0 or cash < price * buy_amount * g.order_cash_buffer:
        return 0
    if total_value > 0 and (tradable + buy_amount) * price / total_value > g.max_position_pct:
        return 0
    return buy_amount

def calc_half_sell(tradable):
    """只对策略仓卖出一半；不足 1 手的策略仓一次卖清。底仓不在内。"""
    if tradable <= 0:
        return 0
    amount = round_lot(tradable * g.sell_ratio)
    leftover = tradable - amount
    if amount <= 0 or leftover < g.lot_size:
        return int(tradable)
    return amount

def update_entry_high(stock, current_pos, high_price):
    if current_pos <= 0:
        g.entry_high.pop(stock, None)
        return None
    held = g.entry_high.get(stock)
    if held is None:
        g.entry_high[stock] = high_price
    else:
        g.entry_high[stock] = max(held, high_price)
    return g.entry_high[stock]

def _ready_daily(df):
    need = max(g.ma_slow + 2, g.rsi_period + 2, g.dmi_period * 2 + 2, g.macd_slow + g.macd_signal + 2, 8)
    return df is not None and len(df) >= need

def daily_buy_signal(df):
    """已完成日线：MA5 上穿 MA10，且 DMI 为上升趋势。"""
    if not _ready_daily(df):
        return False, None
    pair = _ma_pair(df)
    if pair is None:
        return False, None
    fast_prev, fast_now, slow_prev, slow_now = pair
    if not (fast_prev <= slow_prev and fast_now > slow_now):
        return False, None
    if not (slow_now > slow_prev):
        return False, None
    if not (df['close'].iloc[-1] > slow_now):
        return False, None
    rsi = calc_rsi(df, g.rsi_period).iloc[-1]
    if pd.isna(rsi) or rsi >= g.rsi_max_for_buy:
        return False, None
    if not _volume_ok(df, g.volume_confirm_mult_buy):
        return False, None
    dmi = _dmi_now(df)
    if dmi is None:
        return False, None
    plus_di, minus_di, _, adx = dmi
    if not (plus_di > minus_di and adx >= g.adx_min):
        return False, None
    return True, _cross_date(df)

def daily_sell_signal(df):
    """已完成日线：MACD 的 DIF 下穿 DEA，且 DIF 在零轴下。不要求放量。"""
    if not _ready_daily(df):
        return False, None
    dif, dea = calc_macd(df)
    dif_prev, dif_now = dif.iloc[-2], dif.iloc[-1]
    dea_prev, dea_now = dea.iloc[-2], dea.iloc[-1]
    if any(pd.isna(v) for v in (dif_prev, dif_now, dea_prev, dea_now)):
        return False, None
    if not (dif_prev >= dea_prev and dif_now < dea_now):
        return False, None
    if not (dif_now < 0):
        return False, None
    return True, _cross_date(df)

def trend_broken(df, dmi):
    """收盘跌破 MA10，且 DMI 已转为空头并有趋势。用于无量阴跌时清仓。"""
    if dmi is None or not _ready_daily(df):
        return False
    plus_di, minus_di, _, adx = dmi
    ma_slow = calc_ma(df, g.ma_slow).iloc[-1]
    close_now = df['close'].iloc[-1]
    if pd.isna(ma_slow) or pd.isna(close_now):
        return False
    return close_now < ma_slow and minus_di > plus_di and adx >= g.adx_min

# ==================== handle_data ====================
def handle_data(context, data):
    for stock in g.security_list:
        try:
            count = max(80, g.dmi_period * 3)
            df = drop_unclosed_daily(get_daily_data(stock, count), context)
            if not _ready_daily(df):
                continue

            current_price = latest_price(data, stock, df)
            high_price = latest_high(data, stock, df, current_price)
            available_cash = context.portfolio.cash
            dmi = _dmi_now(df)

            position = get_position(stock)
            current_pos = getattr(position, 'amount', 0) or 0
            base_pos = remember_base(stock, current_pos)
            tradable = strategy_amount(stock, current_pos)
            peak = update_entry_high(stock, tradable, high_price)

            fast_now = calc_ma(df, g.ma_fast).iloc[-1]
            slow_now = calc_ma(df, g.ma_slow).iloc[-1]
            rsi = calc_rsi(df, g.rsi_period).iloc[-1]
            dif_line, dea_line = calc_macd(df)
            dif_now, dea_now = dif_line.iloc[-1], dea_line.iloc[-1]
            plus_di = minus_di = adx = float('nan')
            if dmi is not None:
                plus_di, minus_di, _, adx = dmi

            buy_ok, buy_date = daily_buy_signal(df)
            sell_ok, sell_date = daily_sell_signal(df)
            broken = trend_broken(df, dmi)
            trail_hit = peak is not None and current_price < peak * (1 - g.trail_pct)

            log.info(f"[{stock}] 价:{current_price:.2f} | MA{g.ma_fast}:{fast_now:.2f} | MA{g.ma_slow}:{slow_now:.2f} | "
                     f"RSI:{rsi:.1f} | DIF:{dif_now:.4f} | DEA:{dea_now:.4f} | "
                     f"+DI:{plus_di:.1f} | -DI:{minus_di:.1f} | ADX:{adx:.1f} | "
                     f"金叉:{buy_ok} | 死叉:{sell_ok} | 破位:{broken} | 回撤止损:{trail_hit} | "
                     f"底仓:{base_pos} | 策略仓:{tradable} | 总持仓:{current_pos}")

            exited = False
            if tradable > 0 and trail_hit:
                log.info(f"[{stock}] 回撤止损，卖出策略仓 {int(tradable)} 股，底仓保留")
                order(stock, -int(tradable))
                g.entry_high.pop(stock, None)
                exited = True
            elif tradable > 0 and broken:
                log.info(f"[{stock}] 趋势破位，卖出策略仓 {int(tradable)} 股，底仓保留")
                order(stock, -int(tradable))
                g.entry_high.pop(stock, None)
                exited = True
            elif sell_ok and sell_date != g.last_death_cross_date and tradable > 0:
                sell_amount = calc_half_sell(tradable)
                if sell_amount > 0:
                    log.info(f"[{stock}] 【日线MACD死叉】卖出策略仓 {sell_amount} 股，底仓保留")
                    order(stock, -sell_amount)
                    g.last_death_cross_date = sell_date
                    exited = True

            if exited or not buy_ok or buy_date == g.last_golden_cross_date:
                continue

            total_value = account_value(context, current_pos * current_price)
            buy_amount = fixed_buy_amount(tradable, current_price, available_cash, total_value)
            if buy_amount <= 0:
                continue
            log.info(f"[{stock}] 【日线MA{g.ma_fast}/{g.ma_slow}金叉】买入 {buy_amount} 股")
            order(stock, buy_amount)
            g.last_golden_cross_date = buy_date
            held_high = g.entry_high.get(stock, high_price)
            g.entry_high[stock] = max(held_high, high_price)

        except Exception as e:
            log.error(f"[{stock}] 异常: {str(e)}")

def _pct_text(value, total):
    if total <= 0:
        return "账户市值无效"
    return f"{value / total:.1%}"

def log_close_status(context, data, stock):
    count = max(80, g.dmi_period * 3)
    df = drop_unclosed_daily(get_daily_data(stock, count), context)
    if not _ready_daily(df):
        log.info(f"[{stock}] 日线数据不足，无法判断当前状态")
        return

    price = latest_price(data, stock, df)
    position = get_position(stock)
    current_pos = getattr(position, 'amount', 0) or 0
    base_pos = g.base_amount.get(stock)
    if base_pos is None:
        log.info(f"[{stock}] 底仓尚未记录。当前总持仓 {current_pos} 股")
        base_pos = 0
        tradable = 0
    else:
        tradable = max(0, current_pos - base_pos)

    total_value = account_value(context, current_pos * price)
    strategy_value = tradable * price
    fast_now = calc_ma(df, g.ma_fast).iloc[-1]
    slow_prev = calc_ma(df, g.ma_slow).iloc[-2]
    slow_now = calc_ma(df, g.ma_slow).iloc[-1]
    rsi = calc_rsi(df, g.rsi_period).iloc[-1]
    dif_line, dea_line = calc_macd(df)
    dif_now, dea_now = dif_line.iloc[-1], dea_line.iloc[-1]
    dmi = _dmi_now(df)
    volume_ok = _volume_ok(df, g.volume_confirm_mult_buy)
    buy_ok, _ = daily_buy_signal(df)
    sell_ok, _ = daily_sell_signal(df)
    broken = trend_broken(df, dmi)

    log.info(f"[{stock}] 底仓 {base_pos} 股不参与买卖。策略仓 {tradable} 股，总持仓 {current_pos} 股。"
             f"策略仓市值 {strategy_value:.0f}，占账户 {_pct_text(strategy_value, total_value)}，上限 {g.max_position_pct:.0%}。")

    peak = g.entry_high.get(stock)
    if tradable > 0 and peak:
        stop_price = peak * (1 - g.trail_pct)
        log.info(f"[{stock}] 策略仓最高价 {peak:.2f}，{g.trail_pct:.0%} 回撤止损价 {stop_price:.2f}，"
                 f"现价 {price:.2f}。{'已跌破止损价' if price < stop_price else '尚未触及回撤止损'}。")
    elif tradable > 0:
        log.info(f"[{stock}] 策略仓 {tradable} 股，最高价尚未记下，现价 {price:.2f}。")
    else:
        log.info(f"[{stock}] 目前没有策略仓，回撤止损不生效。现价 {price:.2f}。")

    ma_up = slow_now > slow_prev
    above_slow = price > slow_now
    log.info(f"[{stock}] MA{g.ma_fast} {fast_now:.2f}，MA{g.ma_slow} {slow_now:.2f}。"
             f"{'快线在慢线之上' if fast_now > slow_now else '快线在慢线之下'}，"
             f"{'慢线向上' if ma_up else '慢线不向上'}，"
             f"{'收盘在慢线之上' if above_slow else '收盘在慢线之下'}。")

    if dmi is None:
        dmi_text = "DMI 数据不足"
    else:
        plus_di, minus_di, _, adx = dmi
        dmi_text = (f"+DI {plus_di:.1f} {'大于' if plus_di > minus_di else '不大于'} -DI {minus_di:.1f}，"
                    f"ADX {adx:.1f} {'达到' if adx >= g.adx_min else '低于'} {g.adx_min}")
    rsi_text = "RSI 数据不足" if pd.isna(rsi) else f"RSI {rsi:.1f} {'低于' if rsi < g.rsi_max_for_buy else '不低于'} 买入上限 {g.rsi_max_for_buy}"
    log.info(f"[{stock}] {rsi_text}。{dmi_text}。买入量能{'达标' if volume_ok else '未达标'}（阈值 {g.volume_confirm_mult_buy}×前5日）。"
             f"今日{'是' if buy_ok else '不是'}金叉买入日。")

    if pd.isna(dif_now) or pd.isna(dea_now):
        macd_text = "MACD 数据不足"
    else:
        macd_text = (f"DIF {dif_now:.4f} {'低于' if dif_now < dea_now else '不低于'} DEA {dea_now:.4f}，"
                     f"DIF {'在零轴下' if dif_now < 0 else '在零轴上'}")
    half_amount = calc_half_sell(tradable)
    log.info(f"[{stock}] {macd_text}。今日{'是' if sell_ok else '不是'}死叉卖出日，"
             f"若卖出则为策略仓 {half_amount} 股。"
             f"趋势{'已破位，会卖出全部策略仓' if broken else '未破位'}。")
    log.info(f"[{stock}] 最近一次金叉 {g.last_golden_cross_date or '无'}，最近一次死叉 {g.last_death_cross_date or '无'}。")

def after_trading_end(context, data):
    log.info("=== 收盘总结 ===")
    log.info(f"参数 | 每次买入 {g.add_once} 股 | 策略仓上限 {g.max_position_pct:.0%}（不含底仓） | "
             f"死叉卖出策略仓的 {g.sell_ratio:.0%} | 回撤止损 {g.trail_pct:.0%} | "
             f"MA{g.ma_fast}/{g.ma_slow} | MACD {g.macd_fast}/{g.macd_slow}/{g.macd_signal} | "
             f"RSI 上限 {g.rsi_max_for_buy} | ADX 下限 {g.adx_min} | 买入量能 {g.volume_confirm_mult_buy}×前5日")
    log.info(f"账户现金 {context.portfolio.cash:.0f}")
    for stock in g.security_list:
        try:
            log_close_status(context, data, stock)
        except Exception as e:
            log.error(f"[{stock}] 收盘总结异常: {str(e)}")
