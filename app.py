import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime
import requests
import time
from streamlit_gsheets import GSheetsConnection

# --- [0. 페이지 설정] ---
st.set_page_config(page_title="ISA VR 5.0 가이드", layout="wide")

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

# --- [1. 시장 데이터 수집] ---
@st.cache_data(ttl=600)
def get_market_intelligence():
    data = {"price": 0, "dd": 0.0, "fng": 25.0, "bull": True}
    try:
        t_hist = yf.Ticker("409820.KS").history(period="5d")
        if not t_hist.empty: data["price"] = int(t_hist['Close'].iloc[-1])
        n_hist = yf.Ticker("^NDX").history(period="2y")
        if not n_hist.empty:
            ndx_high = n_hist['Close'].max()
            curr_ndx = n_hist['Close'].iloc[-1]
            data["dd"] = round((curr_ndx / ndx_high - 1) * 100, 2)
            data["bull"] = curr_ndx > n_hist['Close'].rolling(window=200).mean().iloc[-1]
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
            return False, 0.0, f"🚫 조정장 대기 (DD {dd}%): FnG({fng}) 수치 미달(20 필요). 추가 하락 위험으로 매수 금지.", "error"
    else:
        if fng <= 15:
            return True, 0.3, f"🚨 폭락장 (DD {dd}%): 극심한 공포(FnG {fng}). 가용 현금의 30% 이내에서 보수적 매수.", "critical"
        else:
            return False, 0.0, f"⛔ 폭락장 방어 (DD {dd}%): 패닉 셀 구간 아님(FnG 15 필요). 바닥 확인 전까지 매수 절대 금지.", "error"

# --- [3. UI 구성] ---
st.title("⚖️ ISA VR 5.0 가이드")

with st.sidebar:
    st.header("⚙️ 시장 지표")
    st.metric("나스닥 낙폭", f"{m['dd']}%")
    st.markdown("[👉 FnG 지수 (CNN)](https://edition.cnn.com/markets/fear-and-greed)")
    fng_input = st.number_input("FnG Index", value=float(m['fng']))
    st.divider()
    
    st.subheader("💾 자산 데이터 (ISA)")
    conn = st.connection("gsheets", type=GSheetsConnection)
    
    try:
        df_history = conn.read(worksheet="ISA", ttl=0).dropna(how='all')
        if not df_history.empty:
            last_row = df_history.iloc[-1]
            default_qty = int(last_row.get('Qty', 0))
            default_pool = int(last_row.get('Pool', 0))
            default_v = int(last_row.get('V_old', 0))
            default_principal = int(last_row.get('Principal', 20566879))
            st.success(f"📈 총 {len(df_history)}회차 기록 로드됨")
        else: raise Exception()
    except:
        default_qty, default_pool, default_v, default_principal = 0, 0, 0, 20566879
        df_history = pd.DataFrame(columns=["Qty", "Pool", "V_old", "Principal", "Date"])

    mode = st.radio("운용 모드", ["최초 시작", "사이클 업데이트"])
    principal = st.number_input("총 투입 원금 (원)", value=int(default_principal), step=10000)
    qty = st.number_input("보유 수량 (주)", value=int(default_qty), min_value=0)
    pool = st.number_input("Pool (파킹ETF 평가금)", value=int(default_pool), step=10000)
    
    if mode == "최초 시작":
        v1 = m['price'] * qty
        v_to_save = v1
    else:
        v_old = st.number_input("직전 V1 (원)", value=int(default_v), step=10000)
        target_roi = st.slider("이번 텀 목표 수익률 (%)", 0.0, 1.5, 0.6, step=0.1) / 100
        v_to_save = int(v_old * (1 + target_roi))
        v1 = v_to_save
        add_cash = st.number_input("추가 입금액 (원)", value=0, step=10000)
        if add_cash > 0:
            v1 += add_cash
            principal += add_cash

    band_pct = st.slider("밴드 설정 (%)", 5, 20, 10) / 100

    if st.button("💾 ISA 시트에 저장"):
        new_row = pd.DataFrame([{
            "Qty": qty, "Pool": pool, "V_old": v_to_save, 
            "Principal": principal, "Date": datetime.now().strftime('%Y-%m-%d')
        }])
        updated_df = pd.concat([df_history, new_row], ignore_index=True)
        conn.update(worksheet="ISA", data=updated_df)
        st.cache_data.clear() 
        st.success(f"✅ {datetime.now().strftime('%Y-%m-%d')} 저장 완료!")

# --- [4. 메인 화면 출력] ---
if v1 > 0:
    v_l, v_u = int(v1 * (1 - band_pct)), int(v1 * (1 + band_pct))
    curr_stock_val = m['price'] * qty
    current_asset = curr_stock_val + pool
    ok, qta, msg, m_type = check_safety(m['dd'], fng_input)
    roi_pct = (current_asset / principal - 1) * 100 if principal > 0 else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("총 자산", f"{current_asset:,.0f}원")
    c2.metric("목표 V 대비 편차", f"{(curr_stock_val/v1-1)*100:.2f}%")
    c3.metric("누적 수익률", f"{roi_pct:.2f}%")
    st.divider()

    tab1, tab2, tab3 = st.tabs(["📊 매매 가이드", "📋 사용방법(상세)", "🛡️ 안전장치 로직(상세)"])
    
    with tab1:
        if m_type == "normal": st.success(msg)
        elif m_type == "warning": st.warning(msg)
        else: st.error(msg)
        
        l, r = st.columns(2)
        with l:
            st.markdown("#### 📉 BUY (매수)")
            if curr_stock_val < v_l:
                if ok:
                    st.info(f"매수 강도: {qta*100:.0f}% 적용")
                    for i in range(1, 10): 
                        t_q = qty + i
                        p = int(v_l / t_q)
                        if p < m['price'] * 1.05: st.code(f"✅ LOC 매수: {p:,}원 ({t_q}주)")
                else: st.error("🚫 안전장치 미충족: 매수 금지")
            else: st.info("😴 관망 (평가액 > 하단 밴드)")
        with r:
            st.markdown("#### 📈 SELL (매도)")
            if curr_stock_val > v_u:
                for i in range(1, 5):
                    t_q = qty - i
                    if t_q > 0:
                        p = int(v1 / t_q)
                        if p > m['price']: st.code(f"🔥 LOC 매도: {p:,}원 ({qty-t_q}주 판매)")
            else: st.info("😴 관망 (평가액 < 상단 밴드)")

        st.divider()
        if not df_history.empty:
            st.subheader("📈 자산 성장 곡선 (History)")
            hist_fig = go.Figure()
            hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['V_old'], name="목표(V)", line=dict(color='gray', dash='dash')))
            hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['Qty'] * m['price'], name="실제 평가액", line=dict(color='#00FF00', width=3)))
            st.plotly_chart(hist_fig, use_container_width=True)

    with tab2:
        st.markdown("### 📘 ISA VR 5.0 상세 운영 매뉴얼")
        c_left, c_right = st.columns(2)
        with c_left:
            st.success("#### 🟢 상승 시 (수익 실현)")
            st.write("""
            1. 평가액이 **상단 밴드(V의 110%)** 돌파 시 매도 실행.
            2. 목표 V값과 현재 평가액의 차액만큼 매도하여 수익 확정.
            3. 매도한 현금은 **Pool(파킹ETF)**로 옮겨 다음 하락을 대비.
            4. 매도는 안전장치와 상관없이 기계적으로 즉시 실행.
            """)
        with c_right:
            st.error("#### 🔴 하락 시 (저가 매수)")
            st.write("""
            1. 평가액이 **하단 밴드(V의 90%)** 아래로 추락 시 매수 검토.
            2. 반드시 **안전장치(탭3)**의 매수 승인 여부와 강도 확인.
            3. 승인 시 하단 밴드를 맞추기 위한 금액만큼만 **분할 매수**.
            4. 현금(Pool) 한도 내에서만 집행하여 생존 자금 확보.
            """)
        st.info("💡 **리밸런싱 주기:** 격주 월요일 오후 3시 / **목표 기울기:** 2주당 0.6% 증액 권장")

    with tab3:
        st.markdown("### 🛡️ ISA-VR 이중 안전장치 (Safety Brake)")
        st.info("폭락장에서 현금 고갈을 방지하기 위해 **나스닥 낙폭(DD)**과 **공포지수(FnG)**를 동시 체크합니다.")
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("1. 나스닥 낙폭 (DD) 기준")
            st.write("- **정상장 (-10% 이내):** 매수 신호 시 가용 현금의 **100% 가동** 가능.")
            st.write("- **조정장 (-10% ~ -20%):** 하락 압력 대비 매수 강도를 **50%로 제한**.")
            st.write("- **폭락장 (-20% 초과):** 패닉 구간 대비 매수 강도를 **30%로 극도 제한**.")
        with col_b:
            st.subheader("2. 공포지수 (FnG) 승인 조건")
            st.write("- **조정장:** FnG 수치가 **20 이하**일 때만 매수 신호를 최종 승인.")
            st.write("- **폭락장:** FnG 수치가 **15 이하**로 떨어졌을 때만 보수적 매수 승인.")
        st.warning("⚠️ **핵심 원칙:** 주가가 하단 밴드에 닿았더라도, 위 조건(DD+FnG)이 충족되지 않으면 매수를 금지하여 현금을 방어합니다.")
else:
    st.info("💡 사이드바에서 보유 수량을 입력하고 '최초 시작' 후 저장 버튼을 누르면 활성화됩니다.")
