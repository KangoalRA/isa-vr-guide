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
    except:
        st.error("텔레그램 전송 실패")

# --- [1. 데이터 수집] ---
@st.cache_data(ttl=600)
def get_market_intelligence():
    data = {"price": 0, "dd": 0.0, "fng": 25.0}
    try:
        t_hist = yf.Ticker("409820.KS").history(period="5d")
        if not t_hist.empty: data["price"] = int(t_hist['Close'].iloc[-1])
        n_hist = yf.Ticker("^NDX").history(period="2y")
        if not n_hist.empty:
            ndx_high = n_hist['Close'].max()
            data["dd"] = round((yf.Ticker("^NDX").history(period="1d")['Close'].iloc[-1] / ndx_high - 1) * 100, 2)
        r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/static/history", headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        if r.status_code == 200: data["fng"] = float(r.json()['fear_and_greed']['score'])
        return data
    except: return data

m = get_market_intelligence()

# --- [2. 로직 함수] ---
def check_safety(dd, fng):
    if dd > -10: return True, 1.0, "🟩 정상장: 가용 현금 100% 매수 가능", "normal"
    elif -20 < dd <= -10:
        return (True, 0.5, "🟧 조정장: 50% 제한 매수", "warning") if fng <= 20 else (False, 0.0, "🚫 조정장 대기", "error")
    else:
        return (True, 0.3, "🟥 하락장: 30% 제한 매수", "critical") if fng <= 15 else (False, 0.0, "🚫 하락장 방어", "error")

# --- [3. UI 시작] ---
st.title("🇰🇷 ISA 매매 가이드 (KODEX QLD)")

with st.sidebar:
    st.header("⚙️ 데이터 관리")
    conn = st.connection("gsheets", type=GSheetsConnection)
    try:
        # 시트 데이터 전체 읽기
        df_history = conn.read(worksheet="ISA", ttl=0).dropna(how='all')
        if not df_history.empty:
            last_row = df_history.iloc[-1]
            # 열 순서: Qty(0), Pool(1), V_old(2), Principal(3), Date(4)
            default_qty = int(last_row.iloc[0])
            default_pool = int(last_row.iloc[1])
            default_v = int(last_row.iloc[2])
            default_principal = int(last_row.iloc[3])
            st.success(f"📈 총 {len(df_history)}회차 기록 로드됨")
        else: raise Exception()
    except:
        default_qty, default_pool, default_v, default_principal = 0, 0, 0, 20566879
        df_history = pd.DataFrame(columns=["Qty", "Pool", "V_old", "Principal", "Date"])

    mode = st.radio("모드 선택", ["최초 시작", "사이클 업데이트"])
    principal = st.number_input("총 투입 원금", value=int(default_principal))
    qty = st.number_input("보유 수량", value=int(default_qty), min_value=0)
    pool = st.number_input("Pool (현금/파킹)", value=int(default_pool))
    
    if mode == "최초 시작":
        v1 = m['price'] * qty
    else:
        v_old = st.number_input("직전 목표V", value=int(default_v))
        v1 = int(v_old * 1.006) 
        
    if st.button("💾 이번 회차 기록 저장"):
        # E열에 들어갈 날짜 추가
        new_row = pd.DataFrame([{
            "Qty": qty, 
            "Pool": pool, 
            "V_old": v1, 
            "Principal": principal, 
            "Date": datetime.now().strftime('%Y-%m-%d') # E열에 현재 날짜 기록
        }])
        updated_df = pd.concat([df_history, new_row], ignore_index=True)
        conn.update(worksheet="ISA", data=updated_df)
        st.cache_data.clear() 
        st.success(f"✅ {datetime.now().strftime('%Y-%m-%d')} 기록 완료!")

# --- [4. 메인 화면 계산] ---
curr_stock_val = m['price'] * qty
v_l, v_u = int(v1 * 0.9), int(v1 * 1.1)
current_total = curr_stock_val + pool
ok, qta, msg, m_type = check_safety(m['dd'], m['fng'])

# 지표 대시보드
c1, c2, c3 = st.columns(3)
c1.metric("현재 총 자산", f"{current_total:,.0f}원")
c2.metric("목표 V 대비", f"{(curr_stock_val/v1-1)*100:.2f}%" if v1>0 else "0%")
c3.metric("누적 수익률", f"{(current_total/principal-1)*100:.2f}%" if principal>0 else "0%")

st.divider()

# --- [5. 탭 구성] ---
tab1, tab2, tab3 = st.tabs(["📊 매매 가이드 & 히스토리", "📋 상세 운영법", "🛡️ 안전장치 설명"])

with tab1:
    # 1단계: 안전장치 및 가이드
    if m_type == "normal": st.success(msg)
    else: st.error(msg)
    
    l, r = st.columns(2)
    with l:
        st.markdown("#### 📉 매수")
        if curr_stock_val < v_l and ok: st.code(f"✅ 매수 추천가: {int(v_l/(qty+1)):,}원")
        else: st.info("매수 조건 미달")
    with r:
        st.markdown("#### 📈 매도")
        if curr_stock_val > v_u: st.code(f"🔥 매도 추천가: {int(v1/(qty-1)):,}원")
        else: st.info("매도 조건 미달")

    st.divider()

    # 2단계: 현재 포지션 비주얼 (현재 사이클)
    if v1 > 0:
        pos_fig = go.Figure()
        pos_fig.add_trace(go.Scatter(x=[0], y=[v_u], name="매도선", mode="markers+text", text=[f"매도선: {v_u:,}"], textposition="top center", marker=dict(color="blue", size=12)))
        pos_fig.add_trace(go.Scatter(x=[0], y=[v_l], name="매수선", mode="markers+text", text=[f"매수선: {v_l:,}"], textposition="bottom center", marker=dict(color="red", size=12)))
        pos_fig.add_trace(go.Scatter(x=[0], y=[curr_stock_val], name="현재가", mode="markers+text", text=[f"현재: {curr_stock_val:,}"], textposition="middle right", marker=dict(color="green", size=18, symbol="diamond")))
        pos_fig.update_layout(title="현재 사이클 내 위치", yaxis_title="금액(원)", xaxis=dict(showticklabels=False, range=[-1, 1]), height=350, showlegend=False)
        st.plotly_chart(pos_fig, use_container_width=True)

    st.divider()

    # 3단계: 누적 히스토리 그래프 (E열 날짜 기준)
    if not df_history.empty:
        st.subheader("📈 VR 누적 투자 성적표")
        # X축을 E열(Date)로 사용하여 시계열 그래프 생성
        hist_fig = go.Figure()
        hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['V_old'], name="목표 V(예상)", line=dict(color='gray', dash='dash')))
        # 실제 평가액 추적 (보유수량 * 현재가로 추정치 표시)
        hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['Qty'] * m['price'], name="실제 평가액", line=dict(color='green', width=3)))
        
        hist_fig.update_layout(title="과거 대비 현재 자산 추이", xaxis_title="기록 날짜", yaxis_title="금액(원)", height=400)
        st.plotly_chart(hist_fig, use_container_width=True)

with tab2:
    st.markdown("### 📘 ISA-VR 운영 원칙")
    st.write("2주마다 V값을 0.6%씩 상향시키며 밴드를 관리합니다.")

with tab3:
    st.markdown("### 🛡️ 리스크 관리 시스템")
    st.write("나스닥 낙폭(DD)과 공포지수(FnG)가 매수 강도를 자동 조절합니다.")
