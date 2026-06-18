"""
回测可视化窗口（Streamlit）。
选时间 + 输股票代码 → 总收益/年化/夏普/波动率/单位净值/回撤/胜率 + 净值曲线 + 个股买卖标识。

启动：
    streamlit run harness/dashboard.py
（依赖 streamlit、plotly，已随 TradingAgents-CN 安装）
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from harness.backtest import _load_df, run

st.set_page_config(page_title="AITrade 回测", layout="wide")
st.title("📊 AITrade 纪律策略回测")
st.caption("回测确定性纪律层（环境过滤+不追高/不破位+止损+止盈分档）；入场用 MACD 金叉代理。不构成投资建议。")

with st.sidebar:
    st.header("参数设置")
    codes = st.text_input("股票代码（逗号分隔）", "600519,002281,600584,603993,002709")
    start = st.date_input("开始日期", date(2024, 1, 1))
    end = st.date_input("结束日期", date(2026, 6, 16))
    cash = st.number_input("期初资金", value=1_000_000, step=100_000)
    st.markdown("**纪律参数**")
    sl = st.slider("止损 %", -15.0, -2.0, -5.0, 0.5) / 100
    tp = st.slider("第一止盈 %", 5.0, 40.0, 10.0, 1.0) / 100
    tr = st.slider("移动止盈回撤 %", 3.0, 20.0, 6.0, 1.0) / 100
    capm = st.slider("仓位系数", 0.5, 2.0, 1.0, 0.1)
    run_btn = st.button("▶ 运行回测", type="primary", use_container_width=True)

if run_btn:
    uni = [c.strip() for c in codes.split(",") if c.strip()]
    with st.spinner("回测中（首次需抓取行情）..."):
        st.session_state["r"] = run(universe=uni, start=start.isoformat(),
                                    end=end.isoformat(), cash=cash, stop_loss=sl,
                                    tp1=tp, trailing=tr, cap_mult=capm)
        st.session_state["uni"] = uni
        st.session_state["range"] = (start.isoformat(), end.isoformat())

r = st.session_state.get("r")
if not r:
    st.info("← 左侧设置参数后点击「运行回测」")
    st.stop()

# --- 常规量化指标 ---
c = st.columns(6)
c[0].metric("总收益", f"{r['ret']:+.1f}%", f"基准 {r['bench']:+.1f}%")
c[1].metric("年化收益", f"{r['ann']:+.1f}%")
c[2].metric("夏普比率", f"{r['sharpe']:.2f}")
c[3].metric("年化波动率", f"{r['vol']:.1f}%")
c[4].metric("最大回撤", f"{r['dd']:.1f}%")
c[5].metric("单位净值", f"{r['nav']:.3f}")
c2 = st.columns(6)
c2[0].metric("交易次数", r["trades"])
c2[1].metric("胜率", f"{r['win']:.1f}%")
c2[2].metric("盈亏比", f"{r['pf']:.2f}")
c2[3].metric("期末资产", f"{r['final']:,.0f}")
c2[4].metric("可用股数", r["loaded"])

# --- 净值曲线 vs 基准 ---
eq = pd.DataFrame(r["equity"])
fig = go.Figure()
fig.add_trace(go.Scatter(x=eq["date"], y=eq["nav"], name="策略净值",
                         line=dict(color="#d62728", width=2)))
bc = r["bench_curve"]
fig.add_trace(go.Scatter(x=bc["dates"], y=bc["norm"], name="上证基准",
                         line=dict(color="#888", dash="dot")))
fig.update_layout(title="单位净值曲线（策略 vs 上证）", height=420,
                  hovermode="x unified", legend=dict(orientation="h"))
st.plotly_chart(fig, use_container_width=True)

# --- 个股买卖标识 ---
st.subheader("个股买卖点")
uni = st.session_state["uni"]
s0, e0 = st.session_state["range"]
sel = st.selectbox("选择股票", uni)
try:
    px = _load_df(sel, s0, e0)
    f2 = go.Figure()
    f2.add_trace(go.Scatter(x=[d.date().isoformat() for d in px.index],
                            y=px["close"], name=sel, line=dict(color="#1f77b4")))
    td = pd.DataFrame(r["trades_log"])
    if len(td):
        ts = td[td["code"] == sel]
        b = ts[ts["side"] == "buy"]
        s = ts[ts["side"] == "sell"]
        f2.add_trace(go.Scatter(x=b["date"], y=b["price"], mode="markers", name="买入",
                                marker=dict(color="red", size=12, symbol="triangle-up")))
        f2.add_trace(go.Scatter(x=s["date"], y=s["price"], mode="markers", name="卖出",
                                marker=dict(color="green", size=12, symbol="triangle-down")))
    f2.update_layout(title=f"{sel} 收盘价与买卖点", height=420,
                     hovermode="x unified", legend=dict(orientation="h"))
    st.plotly_chart(f2, use_container_width=True)
except Exception as ex:
    st.warning(f"行情加载失败：{ex}")

# --- 交易明细 ---
st.subheader("交易明细")
st.dataframe(pd.DataFrame(r["trades_log"]), use_container_width=True)
