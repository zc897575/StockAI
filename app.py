import streamlit as st
import akshare as ak
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import sqlite3
import hashlib

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
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, password TEXT, balance REAL DEFAULT 100000)''')
    c.execute('''CREATE TABLE IF NOT EXISTS positions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, stock_code TEXT, stock_name TEXT, 
                  quantity INTEGER, price REAL, buy_date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS trades
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, stock_code TEXT, stock_name TEXT,
                  type TEXT, quantity INTEGER, price REAL, date TEXT, profit REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_recommendations
                 (date TEXT PRIMARY KEY, stocks TEXT)''')
    conn.commit()
    conn.close()

init_db()

# 辅助函数
@st.cache_data(ttl=60)
def get_stock_list():
    """获取A股实时行情，只返回前200只热门股票，提升加载速度"""
    try:
        df = ak.stock_zh_a_spot_em()
        df = df[["代码", "名称", "最新价", "涨跌幅", "涨跌额", "成交量", "成交额", "最高", "最低", "今开", "昨收"]]
        # 只返回涨幅前200只，提升加载速度
        df = df.sort_values(by="涨跌幅", ascending=False).head(200)
        return df
    except Exception as e:
        st.error(f"获取行情失败: {e}")
        return pd.DataFrame()

def get_stock_name(stock_code):
    """获取股票名称"""
    df = get_stock_list()
    if not df.empty and stock_code in df['代码'].values:
        return df[df['代码'] == stock_code]['名称'].values[0]
    return None

def get_current_price(stock_code):
    """获取当前价格"""
    df = get_stock_list()
    if not df.empty and stock_code in df['代码'].values:
        return float(df[df['代码'] == stock_code]['最新价'].values[0])
    return None

@st.cache_data(ttl=300)
def get_kline_data(stock_code, days=180):
    """获取K线数据"""
    try:
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        df = ak.stock_zh_a_hist(symbol=stock_code, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
        df.columns = ["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"]
        return df
    except Exception as e:
        st.error(f"获取K线失败: {e}")
        return None

# 侧边栏导航
st.sidebar.title("📈 AI股票分析系统")
menu = st.sidebar.radio(
    "功能导航",
    ["实时行情", "股票分析", "每日推荐", "模拟炒股", "量化分析"]
)

# 用户登录
if 'user' not in st.session_state:
    st.session_state.user = None

if menu == "实时行情":
    st.title("📊 A股实时行情")
    
    df = get_stock_list()
    if df.empty:
        st.stop()
    
    # 搜索
    search = st.text_input("搜索股票代码/名称", "")
    if search:
        df = df[df['代码'].str.contains(search) | df['名称'].str.contains(search)]
    
    # 排序
    sort_by = st.selectbox("排序方式", ["涨跌幅", "成交量", "最新价", "成交额"], index=0)
    df = df.sort_values(by=sort_by, ascending=False)
    
    # 展示
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
        }),
        use_container_width=True,
        height=600
    )
    
    # 市场概览
    col1, col2, col3, col4 = st.columns(4)
    up_count = len(df[df['涨跌幅'] > 0])
    down_count = len(df[df['涨跌幅'] < 0])
    flat_count = len(df[df['涨跌幅'] == 0])
    total_turnover = df['成交额'].sum() / 100000000
    
    with col1:
        st.metric("上涨家数", up_count)
    with col2:
        st.metric("下跌家数", down_count)
    with col3:
        st.metric("平盘家数", flat_count)
    with col4:
        st.metric("总成交额(亿元)", round(total_turnover, 2))

elif menu == "股票分析":
    st.title("🔍 股票分析")
    
    stock_code = st.text_input("输入股票代码（如：601985）", "601985")
    days = st.slider("查看天数", 30, 365, 180)
    
    if st.button("开始分析"):
        stock_name = get_stock_name(stock_code)
        if not stock_name:
            st.error("股票代码错误")
            st.stop()
        
        st.subheader(f"{stock_name} ({stock_code})")
        
        df = get_kline_data(stock_code, days)
        if df is None or len(df) == 0:
            st.error("获取数据失败")
            st.stop()
        
        # K线图
        fig = go.Figure(data=[go.Candlestick(
            x=df['日期'],
            open=df['开盘'],
            high=df['最高'],
            low=df['最低'],
            close=df['收盘'],
            name='K线'
        )])
        
        # 均线
        df['MA5'] = df['收盘'].rolling(5).mean()
        df['MA10'] = df['收盘'].rolling(10).mean()
        df['MA20'] = df['收盘'].rolling(20).mean()
        
        fig.add_trace(go.Scatter(x=df['日期'], y=df['MA5'], name='MA5', line=dict(color='blue', width=1)))
        fig.add_trace(go.Scatter(x=df['日期'], y=df['MA10'], name='MA10', line=dict(color='yellow', width=1)))
        fig.add_trace(go.Scatter(x=df['日期'], y=df['MA20'], name='MA20', line=dict(color='purple', width=1)))
        
        fig.update_layout(title="K线图", xaxis_title="日期", yaxis_title="价格", height=600)
        st.plotly_chart(fig, use_container_width=True)
        
        # 基本指标
        col1, col2, col3, col4 = st.columns(4)
        current_price = df['收盘'].iloc[-1]
        change = df['涨跌幅'].iloc[-1]
        volume = df['成交量'].iloc[-1]
        high = df['最高'].iloc[-1]
        
        with col1:
            st.metric("当前价格", f"{current_price:.2f}", f"{change:.2f}%")
        with col2:
            st.metric("今日最高", f"{high:.2f}")
        with col3:
            st.metric("今日成交量", f"{volume:.0f}")
        with col4:
            st.metric("30日涨幅", f"{((current_price / df['收盘'].iloc[-30]) - 1) * 100:.2f}%")

elif menu == "每日推荐":
    st.title("🎯 每日推荐")
    
    df = get_stock_list()
    if df.empty:
        st.stop()
    
    # 筛选涨幅前5，排除ST
    df = df[~df['名称'].str.contains('ST') & ~df['名称'].str.contains('*ST')]
    recommended = df.sort_values(by="涨跌幅", ascending=False).head(5)
    
    st.subheader(f"📅 {datetime.now().strftime('%Y-%m-%d')} 精选股票")
    st.dataframe(
        recommended[["代码", "名称", "最新价", "涨跌幅", "成交量"]].style.format({
            "最新价": "{:.2f}",
            "涨跌幅": "{:.2f}%",
            "成交量": "{:.0f}"
        }),
        use_container_width=True
    )
    
    st.info("推荐策略：选取当日涨幅居前的非ST优质股票，仅供参考，不构成投资建议")

elif menu == "模拟炒股":
    st.title("💰 模拟炒股")
    
    if st.session_state.user is None:
        tab1, tab2 = st.tabs(["登录", "注册"])
        with tab1:
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
                    st.success("登录成功")
                    st.rerun()
                else:
                    st.error("用户名或密码错误")
        with tab2:
            new_username = st.text_input("新用户名")
            new_password = st.text_input("新密码", type="password")
            confirm_pw = st.text_input("确认密码", type="password")
            if st.button("注册"):
                if new_password != confirm_pw:
                    st.error("密码不一致")
                elif len(new_username) < 3:
                    st.error("用户名至少3位")
                else:
                    conn = sqlite3.connect('stock_system.db')
                    c = conn.cursor()
                    hashed_pw = hashlib.md5(new_password.encode()).hexdigest()
                    try:
                        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (new_username, hashed_pw))
                        conn.commit()
                        st.success("注册成功，请登录")
                    except:
                        st.error("用户名已存在")
                    conn.close()
    else:
        st.subheader(f"欢迎，{st.session_state.user}")
        conn = sqlite3.connect('stock_system.db')
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE username=?", (st.session_state.user,))
        balance = c.fetchone()[0]
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("可用资金", f"{balance:.2f}元")
        with col2:
            if st.button("退出登录"):
                st.session_state.user = None
                st.rerun()
        
        # 交易
        st.subheader("股票交易")
        stock_code = st.text_input("股票代码")
        quantity = st.number_input("买入数量（100的整数倍）", min_value=100, step=100)
        
        if st.button("买入"):
            if not stock_code:
                st.error("请输入股票代码")
            else:
                stock_name = get_stock_name(stock_code)
                price = get_current_price(stock_code)
                if not stock_name or not price:
                    st.error("股票代码错误")
                else:
                    total = price * quantity
                    if total > balance:
                        st.error("资金不足")
                    else:
                        # 扣除资金
                        new_balance = balance - total
                        c.execute("UPDATE users SET balance=? WHERE username=?", (new_balance, st.session_state.user))
                        # 添加持仓
                        c.execute("INSERT INTO positions (username, stock_code, stock_name, quantity, price, buy_date) VALUES (?, ?, ?, ?, ?, ?)",
                                (st.session_state.user, stock_code, stock_name, quantity, price, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                        # 添加交易记录
                        c.execute("INSERT INTO trades (username, stock_code, stock_name, type, quantity, price, date, profit) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (st.session_state.user, stock_code, stock_name, "买入", quantity, price, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0))
                        conn.commit()
                        st.success(f"买入成功：{stock_name} {quantity}股，成交金额：{total:.2f}元")
        
        # 持仓
        st.subheader("我的持仓")
        c.execute("SELECT * FROM positions WHERE username=?", (st.session_state.user,))
        positions = c.fetchall()
        if positions:
            pos_data = []
            for pos in positions:
                current_price = get_current_price(pos[2]) or pos[5]
                profit = (current_price - pos[5]) * pos[4]
                pos_data.append({
                    "股票代码": pos[2],
                    "股票名称": pos[3],
                    "持仓数量": pos[4],
                    "成本价": pos[5],
                    "当前价": current_price,
                    "持仓收益": profit
                })
            st.dataframe(pd.DataFrame(pos_data), use_container_width=True)
        else:
            st.info("暂无持仓")
        conn.close()

elif menu == "量化分析":
    st.title("🧮 量化回测")
    
    stock_code = st.text_input("股票代码", "000001")
    short_ma = st.slider("短期均线", 3, 30, 5)
    long_ma = st.slider("长期均线", 20, 120, 20)
    days = st.slider("回测天数", 180, 720, 365)
    
    if st.button("开始回测"):
        df = get_kline_data(stock_code, days)
        if df is None or len(df) == 0:
            st.error("获取数据失败")
            st.stop()
        
        # 计算均线
        df[f'MA{short_ma}'] = df['收盘'].rolling(short_ma).mean()
        df[f'MA{long_ma}'] = df['收盘'].rolling(long_ma).mean()
        
        # 生成信号
        df['signal'] = 0
        df.loc[df[f'MA{short_ma}'] > df[f'MA{long_ma}'], 'signal'] = 1
        df.loc[df[f'MA{short_ma}'] < df[f'MA{long_ma}'], 'signal'] = -1
        
        # 计算收益
        df['return'] = df['收盘'].pct_change()
        df['strategy_return'] = df['return'] * df['signal'].shift(1)
        
        df['cum_market'] = (1 + df['return']).cumprod()
        df['cum_strategy'] = (1 + df['strategy_return']).cumprod()
        
        # 指标
        total_strategy = (df['cum_strategy'].iloc[-1] - 1) * 100
        total_market = (df['cum_market'].iloc[-1] - 1) * 100
        max_drawdown = (df['cum_strategy'] / df['cum_strategy'].cummax() - 1).min() * 100
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("策略收益率", f"{total_strategy:.2f}%", f"{total_strategy - total_market:.2f}% vs 大盘")
        with col2:
            st.metric("大盘收益率", f"{total_market:.2f}%")
        with col3:
            st.metric("最大回撤", f"{max_drawdown:.2f}%")
        
        # 绘图
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df['日期'], y=df['cum_market'], name='大盘收益', line=dict(color='blue')))
        fig.add_trace(go.Scatter(x=df['日期'], y=df['cum_strategy'], name='策略收益', line=dict(color='red')))
        fig.update_layout(title="收益对比", height=600)
        st.plotly_chart(fig, use_container_width=True)

st.sidebar.markdown("---")
st.sidebar.info("📊 数据来源：AkShare | 仅供学习，不构成投资建议")
