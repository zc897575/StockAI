import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from ta import add_all_ta_features
from datetime import datetime, timedelta
import sqlite3
import hashlib
import requests
import json
import time

# 全局缓存：行情数据缓存1分钟
CACHE_DURATION = 60
cache = {
    "stock_list": None,
    "stock_list_time": 0
}

# 页面配置
st.set_page_config(
    page_title="AI股票分析系统",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 初始化数据库
def init_db():
    conn = sqlite3.connect('stock_system.db')
    c = conn.cursor()
    
    # 模拟炒股账户表
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, password TEXT, balance REAL DEFAULT 100000)''')
    
    # 持仓表
    c.execute('''CREATE TABLE IF NOT EXISTS positions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, stock_code TEXT, stock_name TEXT, 
                  quantity INTEGER, price REAL, buy_date TEXT)''')
    
    # 交易记录表
    c.execute('''CREATE TABLE IF NOT EXISTS trades
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, stock_code TEXT, stock_name TEXT,
                  type TEXT, quantity INTEGER, price REAL, date TEXT, profit REAL)''')
    
    # 每日推荐表
    c.execute('''CREATE TABLE IF NOT EXISTS daily_recommendations
                 (date TEXT PRIMARY KEY, stocks TEXT)''')
    
    conn.commit()
    conn.close()

init_db()

# 辅助函数
def get_stock_list():
    """获取全部股票列表，直接调用新浪原生API，不依赖AkShare，速度更快更稳定"""
    global cache
    now = time.time()
    
    # 如果缓存有效直接返回
    if cache["stock_list"] is not None and now - cache["stock_list_time"] < CACHE_DURATION:
        return cache["stock_list"].copy()
    
    try:
        # 新浪财经全市场股票接口
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
        params = {
            "page": 1,
            "num": 5000,
            "sort": "changepercent",
            "asc": 0,
            "node": "hs_a",
            "symbol": "",
            "_s_r_a": "init"
        }
        
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            raise Exception(f"接口请求失败，状态码：{response.status_code}")
        
        data = response.json()
        if not data:
            raise Exception("接口返回空数据")
        
        # 转换为DataFrame
        df = pd.DataFrame(data)
        df = df.rename(columns={
            "code": "代码",
            "name": "名称",
            "trade": "最新价",
            "changepercent": "涨跌幅",
            "pricechange": "涨跌额",
            "volume": "成交量",
            "amount": "成交额",
            "high": "最高",
            "low": "最低",
            "open": "今开",
            "settlement": "昨收"
        })
        
        # 保留需要的列
        df = df[["代码", "名称", "最新价", "涨跌幅", "涨跌额", "成交量", "成交额", "最高", "最低", "今开", "昨收"]]
        
        # 数据类型转换
        numeric_cols = ["最新价", "涨跌幅", "涨跌额", "成交量", "成交额", "最高", "最低", "今开", "昨收"]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        
        # 更新缓存
        cache["stock_list"] = df
        cache["stock_list_time"] = now
        
        return df.copy()
    except Exception as e:
        st.error(f"获取行情数据失败: {str(e)}，请稍后刷新重试")
        return None

def get_current_price(stock_code):
    """获取股票当前价格"""
    try:
        df = get_stock_list()
        if df is not None and stock_code in df['代码'].values:
            return float(df[df['代码'] == stock_code]['最新价'].values[0])
        return None
    except:
        return None

def get_stock_name(stock_code):
    """获取股票名称"""
    try:
        df = get_stock_list()
        if df is not None and stock_code in df['代码'].values:
            return df[df['代码'] == stock_code]['名称'].values[0]
        return None
    except:
        return None

def get_kline_data(stock_code, period="daily", days=180):
    """获取K线数据，增加重试和备用数据源"""
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    
    # 尝试3次
    for retry in range(3):
        try:
            if period == "daily":
                df = ak.stock_zh_a_hist(symbol=stock_code, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
            elif period == "weekly":
                df = ak.stock_zh_a_hist(symbol=stock_code, period="weekly", start_date=start_date, end_date=end_date, adjust="qfq")
            else:
                df = ak.stock_zh_a_hist(symbol=stock_code, period="monthly", start_date=start_date, end_date=end_date, adjust="qfq")
            
            if len(df) > 0:
                df.columns = ["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"]
                return df
        except Exception as e:
            if retry == 2: # 最后一次尝试失败，用备用接口
                try:
                    # 备用接口：新浪财经K线
                    df = ak.stock_zh_a_daily(symbol=stock_code, start_date=start_date, end_date=end_date, adjust="qfq")
                    if len(df) > 0:
                        df = df.reset_index()
                        df.columns = ["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额"]
                        # 计算其他指标
                        df["涨跌幅"] = (df["收盘"] - df["收盘"].shift(1)) / df["收盘"].shift(1) * 100
                        df["涨跌额"] = df["收盘"] - df["收盘"].shift(1)
                        df["振幅"] = (df["最高"] - df["最低"]) / df["收盘"].shift(1) * 100
                        df["换手率"] = 0 # 新浪接口没有换手率，暂时填空
                        return df
                except Exception as e2:
                    if retry == 2:
                        st.error(f"获取K线数据失败: {e2}，请稍后重试或换其他股票")
                        return None
            time.sleep(1) # 重试间隔1秒
    return None

def calculate_technical_indicators(df):
    """计算技术指标"""
    try:
        df = add_all_ta_features(
            df, open="开盘", high="最高", low="最低", close="收盘", volume="成交量", fillna=True
        )
        return df
    except:
        return df

def generate_daily_recommendations():
    """生成每日推荐股票，暂时用涨幅榜前5名替代"""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        
        # 先查数据库是否有今日推荐
        conn = sqlite3.connect('stock_system.db')
        c = conn.cursor()
        c.execute("SELECT stocks FROM daily_recommendations WHERE date=?", (today,))
        result = c.fetchone()
        
        if result:
            return eval(result[0])
        
        # 从实时行情里取涨幅前5名
        df = get_stock_list()
        if df is None:
            return []
        
        # 取涨幅前5，排除ST和新股
        recommended = []
        for _, row in df.sort_values(by="涨跌幅", ascending=False).head(10).iterrows():
            if "ST" in row["名称"] or "*ST" in row["名称"] or float(row["最新价"]) > 100:
                continue
            recommended.append({
                "code": row["代码"],
                "name": row["名称"],
                "change": round(row["涨跌幅"], 2),
                "current_price": round(row["最新价"], 2)
            })
            if len(recommended) >=5:
                break
        
        # 存入数据库
        c.execute("INSERT OR REPLACE INTO daily_recommendations VALUES (?, ?)", (today, str(recommended)))
        conn.commit()
        conn.close()
        
        return recommended
    except Exception as e:
        st.error(f"生成推荐失败: {e}")
        return []

# 侧边栏导航
st.sidebar.title("📈 AI股票分析系统")
menu = st.sidebar.radio(
    "功能导航",
    ["实时行情", "股票分析", "每日推荐", "模拟炒股", "量化分析", "系统设置"]
)

# 用户登录/注册
if 'user' not in st.session_state:
    st.session_state.user = None

if st.session_state.user is None and menu == "模拟炒股":
    st.sidebar.subheader("账户登录")
    login_tab, register_tab = st.sidebar.tabs(["登录", "注册"])
    
    with login_tab:
        username = st.text_input("用户名")
        password = st.text_input("密码", type="password")
        if st.button("登录"):
            conn = sqlite3.connect('stock_system.db')
            c = conn.cursor()
            hashed_pw = hashlib.md5(password.encode()).hexdigest()
            c.execute("SELECT * FROM users WHERE username=? AND password=?", (username, hashed_pw))
            user = c.fetchone()
            conn.close()
            
            if user:
                st.session_state.user = username
                st.success("登录成功！")
                st.rerun()
            else:
                st.error("用户名或密码错误")
    
    with register_tab:
        new_username = st.text_input("新用户名")
        new_password = st.text_input("新密码", type="password")
        confirm_password = st.text_input("确认密码", type="password")
        if st.button("注册"):
            if new_password != confirm_password:
                st.error("两次密码不一致")
            elif len(new_username) < 3:
                st.error("用户名至少3位")
            else:
                conn = sqlite3.connect('stock_system.db')
                c = conn.cursor()
                hashed_pw = hashlib.md5(new_password.encode()).hexdigest()
                try:
                    c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (new_username, hashed_pw))
                    conn.commit()
                    st.success("注册成功！请登录")
                except:
                    st.error("用户名已存在")
                conn.close()

# 页面内容
if menu == "实时行情":
    st.title("📊 A股实时行情")
    
    # 获取全部A股实时行情
    with st.spinner("正在加载实时行情数据，首次加载可能需要5-10秒..."):
        df = get_stock_list()
    
    if df is None:
        st.error("行情数据获取失败，请刷新页面重试，或稍后再试")
        st.stop()
    
    # 搜索功能
    search = st.text_input("搜索股票代码/名称", "")
    if search:
        df = df[df['代码'].str.contains(search) | df['名称'].str.contains(search)]
    
    # 排序选项
    sort_by = st.selectbox("排序方式", ["涨跌幅", "成交量", "最新价", "成交额"], index=0)
    df = df.sort_values(by=sort_by, ascending=False)
    
    # 显示数据
    st.dataframe(
        df.style.format({
            "最新价": "{:.2f}",
            "涨跌幅": "{:.2f}%",
            "涨跌额": "{:.2f}",
            "成交量": "{:.0f}",
            "成交额": "{:.0f}",
            "最高": "{:.2f}",
            "最低": "{:.2f}",
            "今开": "{:.2f}",
            "昨收": "{:.2f}"
        }).applymap(lambda x: 'color: red' if isinstance(x, (int, float)) and x > 0 else 'color: green' if isinstance(x, (int, float)) and x < 0 else '', subset=['涨跌幅', '涨跌额']),
        use_container_width=True,
        height=600
    )
    
    # 市场概览
    st.subheader("市场概览")
    col1, col2, col3, col4 = st.columns(4)
    
    # 上涨家数
    up_count = len(df[df['涨跌幅'] > 0])
    down_count = len(df[df['涨跌幅'] < 0])
    flat_count = len(df[df['涨跌幅'] == 0])
    
    with col1:
        st.metric("上涨家数", up_count, delta_color="normal")
    with col2:
        st.metric("下跌家数", down_count, delta_color="inverse")
    with col3:
        st.metric("平盘家数", flat_count)
    with col4:
        total_turnover = df['成交额'].sum() / 100000000
        st.metric("总成交额(亿元)", round(total_turnover, 2))

elif menu == "股票分析":
    st.title("🔍 股票深度分析")
    
    stock_code = st.text_input("输入股票代码（如：000001）", "000001")
    period = st.selectbox("K线周期", ["daily", "weekly", "monthly"], index=0)
    days = st.slider("查看天数", 30, 365, 180)
    
    if st.button("开始分析"):
        with st.spinner("正在加载股票数据..."):
            stock_name = get_stock_name(stock_code)
            if not stock_name:
                st.error("股票代码错误，请重新输入")
            else:
                st.subheader(f"{stock_name} ({stock_code}) 分析报告")
                
                # 获取K线数据
                df = get_kline_data(stock_code, period, days)
                if df is None:
                    st.error("获取数据失败")
                else:
                    # 计算技术指标
                    df = calculate_technical_indicators(df)
                    
                    # 绘制K线图
                    fig = go.Figure(data=[go.Candlestick(
                        x=df['日期'],
                        open=df['开盘'],
                        high=df['最高'],
                        low=df['最低'],
                        close=df['收盘'],
                        name='K线'
                    )])
                    
                    # 添加均线
                    df['MA5'] = df['收盘'].rolling(5).mean()
                    df['MA10'] = df['收盘'].rolling(10).mean()
                    df['MA20'] = df['收盘'].rolling(20).mean()
                    
                    fig.add_trace(go.Scatter(x=df['日期'], y=df['MA5'], name='MA5', line=dict(color='blue', width=1)))
                    fig.add_trace(go.Scatter(x=df['日期'], y=df['MA10'], name='MA10', line=dict(color='yellow', width=1)))
                    fig.add_trace(go.Scatter(x=df['日期'], y=df['MA20'], name='MA20', line=dict(color='purple', width=1)))
                    
                    fig.update_layout(title="K线图", xaxis_title="日期", yaxis_title="价格", height=600)
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # 绘制成交量
                    fig_volume = px.bar(df, x='日期', y='成交量', title='成交量')
                    st.plotly_chart(fig_volume, use_container_width=True)
                    
                    # 技术指标展示
                    st.subheader("技术指标")
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        rsi = df['momentum_rsi'].iloc[-1]
                        st.metric("RSI(14)", round(rsi, 2), 
                                  delta="超买" if rsi > 70 else "超卖" if rsi < 30 else "正常",
                                  delta_color="inverse" if rsi > 70 else "normal" if rsi <30 else "off")
                    
                    with col2:
                        macd = df['trend_macd'].iloc[-1]
                        st.metric("MACD", round(macd, 2),
                                  delta="多头" if macd > 0 else "空头",
                                  delta_color="normal" if macd >0 else "inverse")
                    
                    with col3:
                        boll_high = df['volatility_bbh'].iloc[-1]
                        boll_low = df['volatility_bbl'].iloc[-1]
                        current_price = df['收盘'].iloc[-1]
                        boll_pos = (current_price - boll_low) / (boll_high - boll_low) * 100
                        st.metric("布林带位置", f"{round(boll_pos, 0)}%",
                                  delta="上轨" if boll_pos > 80 else "下轨" if boll_pos <20 else "中轨")
                    
                    with col4:
                        atr = df['volatility_atr'].iloc[-1]
                        st.metric("ATR(14)", round(atr, 2))
                    
                    # 基本面信息
                    st.subheader("基本面信息")
                    try:
                        finance_df = ak.stock_financial_report_sina(symbol=stock_code, report_type="年报")
                        st.dataframe(finance_df.head(5), use_container_width=True)
                    except:
                        st.info("暂无基本面数据")

elif menu == "每日推荐":
    st.title("🎯 每日精选股票推荐")
    
    with st.spinner("正在生成今日推荐..."):
        recommendations = generate_daily_recommendations()
    
    if not recommendations:
        st.info("今日暂无推荐，请稍后再试")
    else:
        st.subheader(f"📅 {datetime.now().strftime('%Y-%m-%d')} 精选股票")
        
        # 转换为DataFrame展示
        rec_df = pd.DataFrame(recommendations)
        rec_df.columns = ["股票代码", "股票名称", "5日涨幅(%)", "当前价格(元)"]
        
        st.dataframe(
            rec_df.style.format({
                "5日涨幅(%)": "{:.2f}%",
                "当前价格(元)": "{:.2f}"
            }).applymap(lambda x: 'color: red' if x > 0 else 'color: green', subset=['5日涨幅(%)']),
            use_container_width=True,
            height=300
        )
        
        # 推荐逻辑说明
        st.info("""
        推荐策略说明：
        1. 从沪深300成分股中筛选
        2. 最近5个交易日涨幅大于3%
        3. 最近3个交易日成交量较10日均量放大20%以上
        4. 技术形态处于上升通道
        """)

elif menu == "模拟炒股":
    if st.session_state.user is None:
        st.warning("请先登录账户使用模拟炒股功能")
    else:
        st.title("💰 模拟炒股系统")
        
        # 获取用户信息
        conn = sqlite3.connect('stock_system.db')
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE username=?", (st.session_state.user,))
        balance = c.fetchone()[0]
        
        # 账户概览
        st.subheader(f"欢迎回来，{st.session_state.user}")
        col1, col2, col3 = st.columns(3)
        
        # 计算持仓市值
        c.execute("SELECT * FROM positions WHERE username=?", (st.session_state.user,))
        positions = c.fetchall()
        market_value = 0
        
        for pos in positions:
            current_price = get_current_price(pos[2]) or pos[5]
            market_value += pos[4] * current_price
        
        total_asset = balance + market_value
        
        with col1:
            st.metric("总资产(元)", round(total_asset, 2))
        with col2:
            st.metric("可用资金(元)", round(balance, 2))
        with col3:
            st.metric("持仓市值(元)", round(market_value, 2))
        
        # 交易区
        st.subheader("股票交易")
        trade_tab, position_tab, history_tab = st.tabs(["买入/卖出", "我的持仓", "交易历史"])
        
        with trade_tab:
            trade_type = st.radio("交易类型", ["买入", "卖出"])
            stock_code = st.text_input("股票代码")
            quantity = st.number_input("交易数量", min_value=100, step=100)
            
            if stock_code:
                current_price = get_current_price(stock_code)
                stock_name = get_stock_name(stock_code)
                
                if current_price and stock_name:
                    st.info(f"当前价格：{stock_name} ({stock_code}) ￥{current_price:.2f}")
                    total_amount = current_price * quantity
                    st.info(f"交易总金额：￥{total_amount:.2f}")
                    
                    if st.button("确认交易"):
                        if trade_type == "买入":
                            if total_amount > balance:
                                st.error("资金不足")
                            else:
                                # 扣除资金
                                new_balance = balance - total_amount
                                c.execute("UPDATE users SET balance=? WHERE username=?", (new_balance, st.session_state.user))
                                
                                # 添加持仓
                                c.execute("INSERT INTO positions (username, stock_code, stock_name, quantity, price, buy_date) VALUES (?, ?, ?, ?, ?, ?)",
                                        (st.session_state.user, stock_code, stock_name, quantity, current_price, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                                
                                # 添加交易记录
                                c.execute("INSERT INTO trades (username, stock_code, stock_name, type, quantity, price, date, profit) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                        (st.session_state.user, stock_code, stock_name, "买入", quantity, current_price, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0))
                                
                                conn.commit()
                                st.success("买入成功！")
                                st.rerun()
                        
                        else: # 卖出
                            # 检查持仓
                            c.execute("SELECT SUM(quantity) FROM positions WHERE username=? AND stock_code=?", (st.session_state.user, stock_code))
                            hold_quantity = c.fetchone()[0] or 0
                            
                            if hold_quantity < quantity:
                                st.error(f"持仓不足，当前持有{hold_quantity}股")
                            else:
                                # 计算利润
                                c.execute("SELECT price FROM positions WHERE username=? AND stock_code=? ORDER BY buy_date LIMIT 1", (st.session_state.user, stock_code))
                                buy_price = c.fetchone()[0]
                                profit = (current_price - buy_price) * quantity
                                
                                # 增加资金
                                new_balance = balance + total_amount
                                c.execute("UPDATE users SET balance=? WHERE username=?", (new_balance, st.session_state.user))
                                
                                # 减少持仓
                                c.execute("DELETE FROM positions WHERE username=? AND stock_code=? ORDER BY buy_date LIMIT 1", (st.session_state.user, stock_code))
                                if hold_quantity > quantity:
                                    c.execute("INSERT INTO positions (username, stock_code, stock_name, quantity, price, buy_date) VALUES (?, ?, ?, ?, ?, ?)",
                                            (st.session_state.user, stock_code, stock_name, hold_quantity - quantity, buy_price, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                                
                                # 添加交易记录
                                c.execute("INSERT INTO trades (username, stock_code, stock_name, type, quantity, price, date, profit) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                        (st.session_state.user, stock_code, stock_name, "卖出", quantity, current_price, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), profit))
                                
                                conn.commit()
                                st.success(f"卖出成功！盈利：￥{profit:.2f}")
                                st.rerun()
                else:
                    st.error("股票代码错误")
        
        with position_tab:
            if not positions:
                st.info("暂无持仓")
            else:
                pos_data = []
                for pos in positions:
                    current_price = get_current_price(pos[2]) or pos[5]
                    profit = (current_price - pos[5]) * pos[4]
                    profit_rate = profit / (pos[5] * pos[4]) * 100
                    
                    pos_data.append({
                        "股票代码": pos[2],
                        "股票名称": pos[3],
                        "持仓数量": pos[4],
                        "成本价": round(pos[5], 2),
                        "当前价": round(current_price, 2),
                        "持仓收益": round(profit, 2),
                        "收益率(%)": round(profit_rate, 2),
                        "买入时间": pos[6]
                    })
                
                pos_df = pd.DataFrame(pos_data)
                st.dataframe(
                    pos_df.style.format({
                        "成本价": "{:.2f}",
                        "当前价": "{:.2f}",
                        "持仓收益": "{:.2f}",
                        "收益率(%)": "{:.2f}%"
                    }).applymap(lambda x: 'color: red' if x > 0 else 'color: green', subset=['持仓收益', '收益率(%)']),
                    use_container_width=True
                )
        
        with history_tab:
            c.execute("SELECT * FROM trades WHERE username=? ORDER BY date DESC LIMIT 50", (st.session_state.user,))
            trades = c.fetchall()
            
            if not trades:
                st.info("暂无交易记录")
            else:
                trade_data = []
                for trade in trades:
                    trade_data.append({
                        "时间": trade[6],
                        "类型": trade[4],
                        "股票代码": trade[2],
                        "股票名称": trade[3],
                        "数量": trade[5],
                        "价格": round(trade[6], 2),
                        "收益": round(trade[7], 2)
                    })
                
                trade_df = pd.DataFrame(trade_data)
                st.dataframe(trade_df, use_container_width=True)
        
        conn.close()
        
        if st.sidebar.button("退出登录"):
            st.session_state.user = None
            st.rerun()

elif menu == "量化分析":
    st.title("🧮 量化分析工具")
    
    st.subheader("双均线策略回测")
    stock_code = st.text_input("股票代码", "000001")
    short_period = st.slider("短期均线周期", 3, 30, 5)
    long_period = st.slider("长期均线周期", 20, 120, 20)
    backtest_days = st.slider("回测天数", 180, 720, 365)
    
    if st.button("开始回测"):
        with st.spinner("正在回测..."):
            df = get_kline_data(stock_code, days=backtest_days)
            if df is None:
                st.error("获取数据失败")
            else:
                # 计算均线
                df['MA_SHORT'] = df['收盘'].rolling(short_period).mean()
                df['MA_LONG'] = df['收盘'].rolling(long_period).mean()
                
                # 生成信号
                df['signal'] = 0
                df.loc[df['MA_SHORT'] > df['MA_LONG'], 'signal'] = 1  # 金叉，买入
                df.loc[df['MA_SHORT'] < df['MA_LONG'], 'signal'] = -1  # 死叉，卖出
                
                # 计算收益率
                df['return'] = df['收盘'].pct_change()
                df['strategy_return'] = df['return'] * df['signal'].shift(1)
                
                # 计算累计收益
                df['cumulative_market'] = (1 + df['return']).cumprod()
                df['cumulative_strategy'] = (1 + df['strategy_return']).cumprod()
                
                # 计算指标
                total_return = (df['cumulative_strategy'].iloc[-1] - 1) * 100
                market_return = (df['cumulative_market'].iloc[-1] - 1) * 100
                max_drawdown = (df['cumulative_strategy'] / df['cumulative_strategy'].cummax() - 1).min() * 100
                win_rate = len(df[df['strategy_return'] > 0]) / len(df[df['strategy_return'] != 0]) * 100 if len(df[df['strategy_return'] != 0]) > 0 else 0
                
                # 展示结果
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("策略收益率", f"{round(total_return, 2)}%", delta=f"{round(total_return - market_return, 2)}% vs 大盘")
                with col2:
                    st.metric("大盘收益率", f"{round(market_return, 2)}%")
                with col3:
                    st.metric("最大回撤", f"{round(max_drawdown, 2)}%", delta_color="inverse")
                with col4:
                    st.metric("胜率", f"{round(win_rate, 2)}%")
                
                # 绘制收益曲线
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df['日期'], y=df['cumulative_market'], name='大盘收益', line=dict(color='blue')))
                fig.add_trace(go.Scatter(x=df['日期'], y=df['cumulative_strategy'], name='策略收益', line=dict(color='red')))
                fig.update_layout(title="收益曲线对比", xaxis_title="日期", yaxis_title="累计收益倍数", height=600)
                st.plotly_chart(fig, use_container_width=True)
                
                st.info("策略逻辑：短期均线上穿长期均线买入，短期均线下穿长期均线卖出")

elif menu == "系统设置":
    st.title("⚙️ 系统设置")
    
    st.subheader("关于系统")
    st.info("""
    📈 AI股票分析系统 v1.0
    
    功能特点：
    ✅ A股实时行情查询
    ✅ 股票技术面/基本面分析
    ✅ 每日AI选股推荐
    ✅ 模拟炒股交易系统
    ✅ 量化策略回测工具
    
    数据源：
    - AkShare 开源金融数据接口
    - Tushare 金融大数据平台
    
    免责声明：本系统仅供学习参考，不构成任何投资建议，股市有风险，入市需谨慎。
    """)
    
    st.subheader("数据更新")
    if st.button("刷新全部缓存数据"):
        with st.spinner("正在刷新数据..."):
            # 清除今日推荐缓存
            conn = sqlite3.connect('stock_system.db')
            c = conn.cursor()
            c.execute("DELETE FROM daily_recommendations WHERE date=?", (datetime.now().strftime("%Y-%m-%d"),))
            conn.commit()
            conn.close()
            st.success("缓存刷新成功！")

# 页脚
st.sidebar.markdown("---")
st.sidebar.info("📊 数据来源：AkShare | 更新频率：实时 | 免责声明：仅供学习，不构成投资建议")
