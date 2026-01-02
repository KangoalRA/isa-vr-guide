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

# --- [2. 로직 함수: 안전장치 멘트 강화] ---
def check_safety(dd, fng):
    if dd > -10: 
        return True, 1.0, f"🟩 정상장 (DD {dd}%): 안전장치 미작동. 가용 현금 100% 매수 가능.", "normal"
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

# --- [3. UI & 데이터 관리] ---
st.title("⚖️ ISA QLD VR STRATEGY MANAGER")

with st.sidebar:
    st.header("⚙️ 실시간 지표 수정")
    # [복구] FnG 수동 입력 칸
    st.markdown(f"**현재 자동 수집 FnG: {m['fng']}**")
    fng_input = st.number_input("FnG 직접 입력 (수정 필요 시)", value=float(m['fng']), min_value=0.0, max_value=100.0)
    
    st.divider()
    st.header("📂 데이터 동기화")
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

    mode = st.radio("작업 선택", ["최초 설정", "사이클 업데이트"])
    principal = st.number_input("누적 투입 원금", value=int(default_principal))
    qty = st.number_input("현재 QLD 보유 수량", value=int(default_qty), min_value=0)
    pool = st.number_input("현재 가용 현금(Pool)", value=int(default_pool))
    
    if mode == "최초 설정":
        v1 = m['price'] * qty
    else:
        v_old = st.number_input("직전 회차 목표V", value=int(default_v))
        v1 = int(v_old * 1.006) 
        
    if st.button("📝 현재 회차 데이터 시트 저장"):
        new_row = pd.DataFrame([{"Qty": qty, "Pool": pool, "V_old": v1, "Principal": principal, "Date": datetime.now().strftime('%Y-%m-%d')}])
        updated_df = pd.concat([df_history, new_row], ignore_index=True)
        conn.update(worksheet="ISA", data=updated_df)
        st.cache_data.clear() 
        st.success(f"📊 {datetime.now().strftime('%Y-%m-%d')} 기록 완료")

# --- [4. 결과 계산] ---
curr_stock_val = m['price'] * qty
v_l, v_u = int(v1 * 0.9), int(v1 * 1.1)
current_total = curr_stock_val + pool
# 입력받은 fng_input을 사용하여 안전장치 체크
ok, qta, msg, m_type = check_safety(m['dd'], fng_input)

# 상단 대시보드
c1, c2, c3 = st.columns(3)
c1.metric("총 자산(평가액+현금)", f"{current_total:,.0f}원")
c2.metric("목표 V 대비 편차", f"{(curr_stock_val/v1-1)*100:.2f}%" if v1>0 else "0%")
c3.metric("누적 수익률", f"{(current_total/principal-1)*100:.2f}%" if principal>0 else "0%")

st.divider()

# --- [5. 탭 구성] ---
tab1, tab2, tab3 = st.tabs(["📊 매매 가이드", "📖 상세 운영법", "🛡️ 안전장치 로직"])

with tab1:
    st.subheader("🚩 현재 시장 상태 및 매수 승인")
    if m_type == "normal": st.success(msg)
    elif m_type == "warning": st.warning(msg)
    else: st.error(msg)
    
    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("### 📉 BUY (매수)")
        if curr_stock_val < v_l:
            if ok:
                st.info(f"매수 필요 금액: {v_l - curr_stock_val:,.0f}원")
                st.code(f"권장 매수단가: {int(v_l/(qty+1)):,}원 이하", language="txt")
            else:
                st.error("⚠️ 주가는 하단 아래이나, 안전장치 미충족으로 매수 제한.")
        else:
            st.write("현재 매수 구간이 아닙니다. (평가액 > 하단 밴드)")

    with col_r:
        st.markdown("### 📈 SELL (매도)")
        if curr_stock_val > v_u:
            st.info(f"매도 필요 금액: {curr_stock_val - v_u:,.0f}원")
            st.code(f"권장 매도단가: {int(v1/(qty-1)):,}원 이상", language="txt")
        else:
            st.write("현재 매도 구간이 아닙니다. (평가액 < 상단 밴드)")

    st.divider()
    if not df_history.empty:
        st.subheader("📈 자산 성장 및 V-Line 추이")
        hist_fig = go.Figure()
        hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['V_old'], name="목표(V)", line=dict(color='gray', dash='dash')))
        hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['Qty'] * m['price'], name="실제 평가액", line=dict(color='#00FF00', width=3)))
        hist_fig.update_layout(xaxis_title="날짜", yaxis_title="원", height=400)
        st.plotly_chart(hist_fig, use_container_width=True)

with tab2:
    st.markdown("### 📘 ISA QLD VR 상세 운영 매뉴얼")
    c1, c2 = st.columns(2)
    with c1:
        st.success("#### 🟢 상승 시 (수익 실현)")
        st.write("""
        1. 평가액이 **상단 밴드(V의 110%)** 돌파 시 매도 실행.
        2. 목표 V값과 현재 평가액의 차액만큼 매도.
        3. 수익금은 **가용 현금(Pool)**으로 보관.
        """)
    with c2:
        st.error("#### 🔴 하락 시 (저가 매수)")
        st.write("""
        1. 평가액이 **하단 밴드(V의 90%)** 이탈 시 매수 검토.
        2. **안전장치(탭3)**의 매수 승인 여부 확인 필수.
        3. 승인 시 하단 밴드를 맞추기 위한 수량만큼 분할 매수.
        """)
    st.info("💡 **리밸런싱 주기:** 격주 월요일 오후 3시 / **목표 기울기:** 2주당 0.6% 증액")

with tab3:
    st.markdown("### 🛡️ ISA-VR 이중 안전장치 작동 기준")
    st.info("폭락장에서 현금 고갈을 방지하기 위해 **낙폭(DD)**과 **공포지수(FnG)**를 동시 체크합니다.")
    
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("1. 나스닥 낙폭 (DD)")
        st.write("- **정상 (-10%):** 매수 강도 100%")
        st.write("- **조정 (-20%):** 매수 강도 50%")
        st.write("- **폭락 (-20%↓):** 매수 강도 30%")
    with col_b:
        st.subheader("2. 공포지수 (FnG)")
        st.write("- **조정장:** FnG 20 이하 시에만 승인")
        st.write("- **폭락장:** FnG 15 이하 시에만 승인")
    
    st.warning("⚠️ **주의:** 주가가 매수 밴드에 진입했어도 FnG 기준 미달 시 매수 신호는 출력되지 않습니다.")
