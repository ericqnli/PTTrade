# PTrade v2.32

**A股量化交易策略框架（平衡版）**

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

### 项目介绍
取消趋势破位卖出 + ATR止损优化 + 防反转买入，适合当前震荡行情的稳健量化策略。

### 核心特性
- 支持 6 只股票同时交易
- RSI + 均线回踩买入机制
- ATR 3.0倍动态止损
- 追踪止盈 + 仓位管理
- 市场过热控制

### 策略核心逻辑
- **买入条件**：RSI < 38 + 价格回踩下轨
- **卖出条件**：RSI > 85 或 达到利润阈值
- **止损**：ATR 动态止损 + 最大回撤保护
- **仓位**：单股最高 20%，总仓位最高 95%

### 快速开始

```bash
# 克隆项目
git clone https://github.com/ericqnli/PTTrade.git
cd PTTrade

# 安装依赖
pip install -r requirements.txt

# 运行策略
python ptrade2.32.py
参数,默认值,说明
g.rsi_buy,38,RSI买入阈值
g.rsi_sell,85,RSI卖出阈值
g.atr_multiplier,3.0,ATR止损倍数
g.profit_threshold,1.12,止盈比例
g.max_pos_per_stock,0.20,单股最大仓位