import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime
import requests
import time
from streamlit_gsheets import GSheetsConnection

# --- [0. 페이지 설정] ---
st.set_page_config(page_title="ISA QLD VR MANAGER", layout="wide")

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
            data["dd"] = round((n_hist['Close'].iloc[-1] / ndx_high - 1) * 100, 2)
        r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/static/history", headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        if r.status_code == 200: data["fng"] = float(r.json()['fear_and_greed']['score'])
        return data
    except: return data

m = get_market_intelligence()

# --- [2. 로직 함수: 멘트 강화] ---
def check_safety(dd, fng):
    if dd > -10: 
        return True, 1.0, f"✅ 정상장 (DD {dd}%): 안전장치 미작동. 가용 현금 100% 투입 가능.", "normal"
    elif -20 < dd <= -10:
        if fng <= 20:
            return True, 0.5, f"🟧 조정장 (DD {dd}%): 과매도 구간(FnG {fng}). 가용 현금의 50%만 매수 허용.", "warning"
        else:
            return False, 0.0, f"🚫 조정장 대기 (DD {dd}%): FnG({fng}) 수치 미달. 추가 하락 위험으로 매수 금지.", "error"
    else:
        if fng <= 15:
            return True, 0.3, f"🚨 폭락장 (DD {dd}%): 극심한 공포(FnG {fng}). 가용 현금의 30% 이내에서 보수적 매수.", "critical"
        else:
            return False, 0.0, f"⛔ 폭락장 방어 (DD {dd}%): 패닉 셀 구간 아님. 바닥 확인 전까지 매수 절대 금지.", "error"

# --- [3. UI 시작] ---
st.title("⚖️ ISA QLD VR STRATEGY MANAGER")

with st.sidebar:
    st.header("⚙️ 데이터 관리")
    conn = st.connection("gsheets", type=GSheetsConnection)
    try:
        df_history = conn.read(worksheet="ISA", ttl=0).dropna(how='all')
        if not df_history.empty:
            last_row = df_history.iloc[-1]
            default_qty, default_pool, default_v, default_principal = int(last_row.iloc[0]), int(last_row.iloc[1]), int(last_row.iloc[2]), int(last_row.iloc[3])
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
        new_row = pd.DataFrame([{"Qty": qty, "Pool": pool, "V_old": v1, "Principal": principal, "Date": datetime.now().strftime('%Y-%m-%d')}])
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
c2.metric("목표 V 대비 편차", f"{(curr_stock_val/v1-1)*100:.2f}%" if v1>0 else "0%")
c3.metric("누적 수익률", f"{(current_total/principal-1)*100:.2f}%" if principal>0 else "0%")

st.divider()

# --- [5. 탭 구성] ---
tab1, tab2, tab3 = st.tabs(["📊 매매 가이드 & 히스토리", "📋 상세 운영법", "🛡️ 안전장치 설명"])

with tab1:
    if m_type == "normal": st.success(msg)
    elif m_type == "warning": st.warning(msg)
    else: st.error(msg)
    
    l, r = st.columns(2)
    with l:
        st.markdown("#### 📉 BUY (매수)")
        if curr_stock_val < v_l:
            if ok:
                st.info(f"매수 필요액: {v_l - curr_stock_val:,.0f}원")
                st.code(f"✅ LOC 매수 추천가: {int(v_l/(qty+1)):,}원 이하", language="txt")
            else:
                st.error("🚫 주가는 하단 아래이나 안전장치에 의해 매수 차단됨.")
        else:
            st.info("😴 현재 매수 구간이 아닙니다. (평가액 > 하단 밴드)")
    with r:
        st.markdown("#### 📈 SELL (매도)")
        if curr_stock_val > v_u:
            st.info(f"매도 필요액: {curr_stock_val - v_u:,.0f}원")
            st.code(f"🔥 LOC 매도 추천가: {int(v1/(qty-1)):,}원 이상", language="txt")
        else:
            st.info("😴 현재 매도 구간이 아닙니다. (평가액 < 상단 밴드)")

    st.divider()

    if v1 > 0:
        pos_fig = go.Figure()
        pos_fig.add_trace(go.Scatter(x=[0], y=[v_u], name="매도선", mode="markers+text", text=[f"매도선(110%): {v_u:,}"], textposition="top center", marker=dict(color="blue", size=12)))
        pos_fig.add_trace(go.Scatter(x=[0], y=[v_l], name="매수선", mode="markers+text", text=[f"매수선(90%): {v_l:,}"], textposition="bottom center", marker=dict(color="red", size=12)))
        pos_fig.add_trace(go.Scatter(x=[0], y=[curr_stock_val], name="현재가", mode="markers+text", text=[f"내 평가액: {curr_stock_val:,}"], textposition="middle right", marker=dict(color="green", size=18, symbol="diamond")))
        pos_fig.update_layout(title=f"현재 사이클 내 위치 (목표V: {v1:,})", yaxis_title="금액(원)", xaxis=dict(showticklabels=False, range=[-1, 1]), height=350, showlegend=False)
        st.plotly_chart(pos_fig, use_container_width=True)

    if not df_history.empty:
        st.subheader("📈 VR 누적 투자 성장 곡선")
        hist_fig = go.Figure()
        hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['V_old'], name="목표 가치(V)", line=dict(color='gray', dash='dash')))
        hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['Qty'] * m['price'], name="실제 주식 평가액", line=dict(color='#00FF00', width=3)))
        hist_fig.update_layout(title="목표 V vs 실제 자산 추이", xaxis_title="기록 날짜", yaxis_title="원(₩)", height=400)
        st.plotly_chart(hist_fig, use_container_width=True)

with tab2:
    st.markdown("### 📘 ISA-VR 실전 운영 매뉴얼")
    c1, c2 = st.columns(2)
    with c1:
        st.success("#### 🟢 상승 시 (매도)")
        st.write("""
        1. 주가 평가액이 **상단 밴드(V의 110%)**를 돌파하면 매도 준비.
        2. 목표 V값과 현재 평가액의 차액만큼 매도하여 수익 실현.
        3. 매도한 현금은 **가용 현금(Pool)**으로 옮겨 다음 하락을 대비.
        """)
    with c2:
        st.error("#### 🔴 하락 시 (매수)")
        st.write("""
        1. 주가 평가액이 **하단 밴드(V의 90%)** 아래로 내려가면 매수 검토.
        2. 반드시 **안전장치(탭3)**의 승인 여부를 확인.
        3. 가용 현금 범위 내에서 하단 밴드를 맞추기 위한 수량만큼 LOC 매수.
        """)
    st.markdown("""
    ---
    - **리밸런싱 주기:** 격주 월요일 오후 3시 (미국 금요일 종가 반영)
    - **목표 기울기:** 2주당 **0.6% 증액** (연 약 15% 성장 지향)
    - **원칙:** 감정을 배제하고 시스템이 제시하는 수치대로만 기계적 매매 실시.
    """)

with tab3:
    st.markdown("### 🛡️ ISA-VR 이중 안전장치 (Safety Brake)")
    st.info("""
    폭락장에서 현금이 조기에 고갈되는 것을 막기 위해 **나스닥 낙폭(DD)**과 **공포지수(FnG)**를 동시에 체크합니다.
    """)
    
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("1. 나스닥 낙폭 (DD)")
        st.write("- **정상장 (-10% 이내):** 매수 강도 100%")
        st.write("- **조정장 (-10% ~ -20%):** 매수 강도 50%")
        st.write("- **폭락장 (-20% 초과):** 매수 강도 30%")
    with col_b:
        st.subheader("2. 공포지수 (FnG)")
        st.write("- **조정장 진입 시:** FnG 20 이하일 때만 매수")
        st.write("- **폭락장 진입 시:** FnG 15 이하일 때만 매수")
    
    st.warning("⚠️ **주의:** 주가가 하단 밴드에 닿았더라도, 위 조건(FnG)이 충족되지 않으면 시스템은 매수 신호를 차단합니다.")
