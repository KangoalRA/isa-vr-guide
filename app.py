import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime
import requests
from streamlit_gsheets import GSheetsConnection

# --- [0. 페이지 설정] ---
st.set_page_config(page_title="ISA QLD VR MANAGER", layout="wide")

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

# --- [2. 강화된 안전장치 로직] ---
def check_safety(dd, fng):
    # 1단계: 정상장 (DD -10% 이내)
    if dd > -10: 
        return True, 1.0, f"✅ 정상장 (DD {dd}%): 안전장치 미작동. 가용 현금 100% 투입 가능.", "normal"
    
    # 2단계: 조정장 (DD -10% ~ -20%)
    elif -20 < dd <= -10:
        if fng <= 20:
            return True, 0.5, f"⚠️ 조정장 진입 (DD {dd}%): 과매도 구간(FnG {fng}). 가용 현금의 50%만 매수 허용.", "warning"
        else:
            return False, 0.0, f"🚫 조정장 대기 (DD {dd}%): FnG({fng}) 수치 미달. 추가 하락 위험으로 매수 금지.", "error"
    
    # 3단계: 폭락장 (DD -20% 이하)
    else:
        if fng <= 15:
            return True, 0.3, f"🚨 폭락장 진입 (DD {dd}%): 극심한 공포(FnG {fng}). 가용 현금의 30% 이내에서 분할 매수.", "critical"
        else:
            return False, 0.0, f"⛔ 폭락장 방어 (DD {dd}%): 패닉 셀 구간 아님. 바닥 확인 전까지 매수 절대 금지.", "error"

# --- [3. UI & 데이터 관리] ---
st.title("⚖️ ISA QLD VR STRATEGY MANAGER")

with st.sidebar:
    st.header("📂 데이터 동기화")
    conn = st.connection("gsheets", type=GSheetsConnection)
    try:
        df_history = conn.read(worksheet="ISA", ttl=0).dropna(how='all')
        if not df_history.empty:
            last_row = df_history.iloc[-1]
            default_qty, default_pool, default_v, default_principal = int(last_row.iloc[0]), int(last_row.iloc[1]), int(last_row.iloc[2]), int(last_row.iloc[3])
        else: raise Exception()
    except:
        default_qty, default_pool, default_v, default_principal = 0, 0, 0, 20566879
        df_history = pd.DataFrame(columns=["Qty", "Pool", "V_old", "Principal", "Date"])

    mode = st.radio("작업 선택", ["최초 설정", "정기 업데이트 (2주)"])
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
ok, qta, msg, m_type = check_safety(m['dd'], m['fng'])

# 지표 요약
c1, c2, c3 = st.columns(3)
c1.metric("총 자산(평가액+현금)", f"{current_total:,.0f}원")
c2.metric("목표 V 대비 편차", f"{(curr_stock_val/v1-1)*100:.2f}%" if v1>0 else "0%")
c3.metric("누적 수익률", f"{(current_total/principal-1)*100:.2f}%" if principal>0 else "0%")

st.divider()

# --- [5. 메인 탭 구성] ---
tab1, tab2, tab3 = st.tabs(["🚀 매매 가이드", "📖 상세 운영법", "🛡️ 안전장치 로직"])

with tab1:
    # 안전장치 출력
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
                st.error("⚠️ 주가는 하단 밴드 아래이나, 안전장치에 의해 매수가 제한됨.")
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
    # 누적 히스토리 그래프
    if not df_history.empty:
        st.subheader("📈 자산 성장 추이")
        hist_fig = go.Figure()
        hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['V_old'], name="목표(V)", line=dict(color='gray', dash='dash')))
        hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['Qty'] * m['price'], name="실제 평가액", line=dict(color='#00FF00', width=3)))
        hist_fig.update_layout(xaxis_title="날짜", yaxis_title="원", height=400, margin=dict(l=20, r=20, t=30, b=20))
        st.plotly_chart(hist_fig, use_container_width=True)

with tab2:
    st.markdown("""
    ### 📋 ISA QLD VR 상세 운영 매뉴얼
    
    **1. 사이클 관리 (2주 주기)**
    - 매 2주마다 '정기 업데이트' 모드를 선택합니다.
    - 직전 목표 V값에 **0.6%를 곱하여(V * 1.006)** 새로운 목표 V를 설정합니다. 이는 나스닥의 장기 우상향을 반영한 기대 수익입니다.
    
    **2. 매매 밴드 설정 (±10%)**
    - **하단 밴드 (V_low):** 목표 V의 90% 지점. 평가액이 이보다 낮으면 **매수**를 검토합니다.
    - **상단 밴드 (V_up):** 목표 V의 110% 지점. 평가액이 이보다 높으면 **매도**하여 수익을 실현합니다.
    
    **3. 매매 실행 전략**
    - **매수:** (V_low - 현재 평가액)만큼의 금액을 추가 매수합니다. 단, [탭3]의 안전장치가 승인할 때만 실행합니다.
    - **매도:** (현재 평가액 - V_up)만큼의 수량을 매도하여 현금(Pool)을 확보합니다. 매도는 안전장치와 상관없이 즉시 실행합니다.
    
    **4. 현금(Pool) 관리**
    - 매도 시 확보된 현금은 파킹통장이나 발행어음 등에 보관하여 리스크에 대비합니다.
    - 추가 원금 투입 시 '누적 투입 원금' 항목을 업데이트하여 정확한 수익률을 계산합니다.
    """)

with tab3:
    st.markdown("""
    ### 🛡️ 안전장치(Safety Brake) 작동 기준
    
    본 시스템은 시장의 폭락장에서 무분별한 매수로 인해 현금이 고갈되는 것을 방지합니다.
    
    | 시장 상태 | 판단 기준 (나스닥 DD) | 매수 승인 조건 (FnG) | 매수 강도 |
    | :--- | :--- | :--- | :--- |
    | **정상장** | **-10% 이내** | 제한 없음 | **100% (Full)** |
    | **조정장** | **-10% ~ -20%** | **20 이하**일 때만 승인 | **50% 제한** |
    | **폭락장** | **-20% 이하** | **15 이하**일 때만 승인 | **30% 제한** |
    
    - **낙폭(DD):** 전고점 대비 하락률을 의미하며, 하락의 깊이를 측정합니다.
    - **공포지수(FnG):** 시장의 심리적 과매도 상태를 측정합니다. 
    - **핵심:** 하락장에서는 단순히 주가가 싸졌다고 사는 것이 아니라, **시장에 극심한 공포가 만연할 때만** 보수적으로 현금을 투입합니다.
    """)
