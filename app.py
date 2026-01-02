import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime
import requests
import time
from streamlit_gsheets import GSheetsConnection

# --- [0. 페이지 설정] ---
st.set_page_config(page_title="ISA QLD 매매 가이드", layout="wide")

# 텔레그램 전송 함수
def send_telegram_msg(msg):
    try:
        token = st.secrets["telegram"]["bot_token"]
        chat_id = st.secrets["telegram"]["chat_id"]
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {"chat_id": chat_id, "text": msg}
        requests.post(url, data=data)
        st.toast("✅ 텔레그램 전송 완료!", icon="✈️")
    except Exception as e:
        st.error(f"텔레그램 전송 실패: {e}")

# --- [🛡️ 데이터 수집] ---
def get_data_safe(ticker, period="5d"):
    for i in range(3):
        try:
            df = yf.Ticker(ticker).history(period=period)
            if not df.empty: return df
            time.sleep(1) 
        except: time.sleep(1)
    return pd.DataFrame() 

@st.cache_data(ttl=600)
def get_market_intelligence():
    data = {"price": 0, "dd": 0.0, "fng": 25.0, "bull": True}
    try:
        t_hist = get_data_safe("409820.KS", period="5d")
        if not t_hist.empty: data["price"] = int(t_hist['Close'].iloc[-1])
        n_hist = get_data_safe("^NDX", period="2y")
        if not n_hist.empty:
            ndx_high = n_hist['Close'].max()
            curr_ndx = n_hist['Close'].iloc[-1]
            data["dd"] = round((curr_ndx / ndx_high - 1) * 100, 2)
            data["bull"] = curr_ndx > n_hist['Close'].rolling(window=200).mean().iloc[-1]
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/static/history", headers=headers, timeout=3)
            if r.status_code == 200: data["fng"] = float(r.json()['fear_and_greed']['score'])
        except: pass
        return data
    except: return data

m = get_market_intelligence()

# --- [2. 로직 함수] ---
def check_safety(dd, fng):
    if dd > -10: return True, 1.0, "🟩 정상장: 가용 현금 100% 매수 가능", "normal"
    elif -20 < dd <= -10:
        if fng <= 20: return True, 0.5, "🟧 조정장: 가용 현금 50% 제한 매수", "warning"
        else: return False, 0.0, f"🚫 조정장 매수 금지: FnG {fng}", "error"
    else:
        if fng <= 15: return True, 0.3, "🟥 하락장: 가용 현금 30% 제한 매수", "critical"
        else: return False, 0.0, f"🚫 하락장 매수 금지: FnG {fng}", "error"

# --- [UI 시작] ---
st.title("🇰🇷 ISA 매매 가이드 (KODEX QLD)")

if m["price"] > 0:
    with st.sidebar:
        st.header("⚙️ 설정 및 데이터")
        fng_input = st.number_input("FnG Index", value=float(m['fng']))
        band_pct = st.slider("밴드 설정 (%)", 5, 20, 10) / 100
        st.divider()
        conn = st.connection("gsheets", type=GSheetsConnection)
        try:
            existing_data = conn.read(worksheet="ISA", usecols=[0, 1, 2, 3], ttl=0).dropna()
            if not existing_data.empty:
                last_row = existing_data.iloc[-1]
                default_qty, default_pool, default_v, default_principal = int(last_row.iloc[0]), int(last_row.iloc[1]), int(last_row.iloc[2]), int(last_row.iloc[3])
                st.success("☁️ 데이터 로드 완료")
            else: raise Exception()
        except:
            default_qty, default_pool, default_v, default_principal = 0, 0, 0, 20566879
            st.warning("⚠️ 신규 시작")

        mode = st.radio("모드", ["최초 시작", "사이클 업데이트"])
        principal = st.number_input("원금", value=int(default_principal))
        qty = st.number_input("보유수량", value=int(default_qty), min_value=0)
        pool = st.number_input("Pool", value=int(default_pool))
        
        if mode == "최초 시작":
            v1 = m['price'] * qty
        else:
            v_old = st.number_input("직전 V1", value=int(default_v))
            v1 = int(v_old * 1.006) # 기본 0.6% 증액 가입
            
        if st.button("💾 시트 저장"):
            new_data = pd.DataFrame([{"Qty": qty, "Pool": pool, "V_old": v1, "Principal": principal}])
            conn.update(worksheet="ISA", data=new_data)
            st.success("저장 완료")

    # --- 계산 ---
    v_l, v_u = int(v1 * (1 - band_pct)), int(v1 * (1 + band_pct))
    curr_v = m['price'] * qty
    ok, qta, msg, m_type = check_safety(m['dd'], fng_input)

    # --- 📊 [핵심] VR 시각화 그래프 ---
    fig = go.Figure()
    # 밴드 영역 표시
    fig.add_trace(go.Scatter(x=["현재 상태"], y=[v_u], name="매도선(Upper)", mode="markers+text", text=[f"매도: {v_u:,}"], textposition="top center", marker=dict(color="blue", size=15)))
    fig.add_trace(go.Scatter(x=["현재 상태"], y=[v1], name="목표V", mode="markers+text", text=[f"목표: {v1:,}"], textposition="middle right", marker=dict(color="gray", size=10, symbol="x")))
    fig.add_trace(go.Scatter(x=["현재 상태"], y=[v_l], name="매수선(Lower)", mode="markers+text", text=[f"매수: {v_l:,}"], textposition="bottom center", marker=dict(color="red", size=15)))
    # 현재가 표시
    fig.add_trace(go.Scatter(x=["현재 상태"], y=[curr_v], name="현재 평가금", mode="markers+text", text=[f"현재: {curr_v:,}"], textposition="middle left", marker=dict(color="green", size=20, symbol="diamond")))
    
    fig.update_layout(title="VR 포지션 현황", ylabel="원화(₩)", height=500, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    # --- 하단 대시보드 ---
    col1, col2, col3 = st.columns(3)
    current_asset = curr_v + pool
    col1.metric("총 자산", f"{current_asset:,.0f}원")
    col2.metric("목표 V 대비", f"{(curr_v/v1-1)*100:.2f}%" if v1>0 else "0%")
    col3.metric("수익률", f"{(current_asset/principal-1)*100:.2f}%" if principal>0 else "0%")

    tab1, tab2, tab3 = st.tabs(["📊 매매 가이드", "📋 상세 정보", "🛡️ 리스크 관리"])
    # (이하 탭 내용은 이전과 동일...)
    with tab1:
        if m_type == "normal": st.success(msg)
        else: st.error(msg)
        l, r = st.columns(2)
        with l:
            if curr_v < v_l and ok: st.code(f"✅ 매수추천: {int(v_l/ (qty+1)):,}원")
            else: st.info("매수 관망")
        with r:
            if curr_v > v_u: st.code(f"🔥 매도추천: {int(v1/ (qty-1)):,}원")
            else: st.info("매도 관망")
