import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime
import requests
import time
from streamlit_gsheets import GSheetsConnection

# --- [0. 페이지 설정] ---
st.set_page_config(page_title="ISA VR 매매 사용 가이드", layout="wide")

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

# --- [2. 로직 함수: 시장 상태별 카드 색상 및 안전장치] ---
def get_recommended_band_ui(dd, is_bull):
    if not is_bull or dd <= -20:
        return 5, "🟥 폭락장/역배열: 자산 방어를 위해 5% 추천", "error"
    elif -20 < dd <= -10:
        return 7, "🟧 조정장: 변동성 대비 7% ~ 10% 추천", "warning"
    else:
        return 10, "🟩 상승/정배열: 수익 극대화 10% ~ 15% 추천", "success"

def check_safety(dd, fng):
    if dd > -10: return True, 1.0, f"🟩 정상장 (DD {dd}%): 100% 가동 가능", "normal"
    elif -20 < dd <= -10:
        return (True, 0.5, f"🟧 조정장: 50% 제한 (FnG {fng})", "warning") if fng <= 20 else (False, 0.0, f"🚫 조정장 대기 (FnG {fng})", "error")
    else:
        return (True, 0.3, f"🚨 폭락장: 30% 제한 (FnG {fng})", "critical") if fng <= 15 else (False, 0.0, f"🚫 하락장 방어 (FnG {fng})", "error")

# --- [3. UI 시작] ---
st.title("⚖️ ISA VR 매매 사용 가이드")

if m["price"] > 0:
    with st.sidebar:
        st.header("⚙️ 시장 지표")
        st.metric("나스닥 낙폭", f"{m['dd']}%")
        st.markdown("[👉 FnG 지수 (CNN)](https://edition.cnn.com/markets/fear-and-greed)")
        fng_input = st.number_input("FnG Index", value=float(m['fng']))
        st.divider()

        st.subheader("🛠️ 밴드폭 추천")
        rec_val, rec_msg, style = get_recommended_band_ui(m['dd'], m['bull'])
        if style == "error": st.error(rec_msg)
        elif style == "warning": st.warning(rec_msg)
        else: st.success(rec_msg)
        
        band_pct = st.slider("밴드 설정 (%)", 5, 20, rec_val) / 100
        st.divider()

        st.subheader("💾 자산 데이터 (ISA)")
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

        mode = st.radio("운용 모드", ["최초 시작", "사이클 업데이트"])
        principal = st.number_input("총 투입 원금 (원)", value=int(default_principal), step=10000)
        qty = st.number_input("보유 수량 (주)", value=int(default_qty), min_value=0)
        pool = st.number_input("Pool (현금/파킹)", value=int(default_pool), step=10000)
        
        if mode == "최초 시작":
            v1, v_to_save = m['price'] * qty, m['price'] * qty
        else:
            v_old = st.number_input("직전 V1 (원)", value=int(default_v), step=10000)
            target_roi = st.slider("이번 텀 목표 수익률 (%)", 0.0, 1.5, 0.6, step=0.1) / 100
            v_to_save = int(v_old * (1 + target_roi))
            v1 = v_to_save
            add_cash = st.number_input("추가 입금액 (원)", value=0, step=10000)
            if add_cash > 0: v1 += add_cash; principal += add_cash

        # [수정된 저장 로직] E열 날짜와 F열 FnG 지수 함께 저장
        if st.button("💾 ISA 시트에 저장"):
            new_row = pd.DataFrame([{
                "Qty": qty, 
                "Pool": pool, 
                "V_old": v_to_save, 
                "Principal": principal, 
                "Date": datetime.now().strftime('%Y-%m-%d'),
                "FnG": fng_input  # F열에 저장될 데이터
            }])
            updated_df = pd.concat([df_history, new_row], ignore_index=True) if not df_history.empty else new_row
            conn.update(worksheet="ISA", data=updated_df)
            st.cache_data.clear() 
            st.success(f"✅ 날짜(E열)와 FnG({fng_input})(F열) 기록 완료!")

    # --- 메인 화면 (나머지 동일) ---
    v_l, v_u = int(v1 * (1 - band_pct)), int(v1 * (1 + band_pct))
    curr_stock_val = m['price'] * qty
    current_asset = curr_stock_val + pool
    ok, qta, msg, m_type = check_safety(m['dd'], fng_input)
    roi_pct = (current_asset / principal - 1) * 100 if principal > 0 else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("총 자산", f"{current_asset:,.0f}원")
    c2.metric("V 대비 편차", f"{(curr_stock_val/v1-1)*100:.2f}%" if v1>0 else "0%")
    c3.metric("누적 수익률", f"{roi_pct:.2f}%")
    st.divider()

    tab1, tab2, tab3 = st.tabs(["📊 매매 가이드", "📋 사용방법(상세)", "🛡️ 안전장치 로직(상세)"])
    
    with tab1:
        if m_type == "normal": st.success(msg)
        elif m_type == "warning": st.warning(msg)
        else: st.error(msg)
        
        # 포지션 그래프
        if v1 > 0:
            pos_fig = go.Figure()
            pos_fig.add_trace(go.Scatter(x=[0], y=[v_u], name="매도", mode="markers+text", text=[f"매도: {v_u:,}"], textposition="top center", marker=dict(color="blue", size=12)))
            pos_fig.add_trace(go.Scatter(x=[0], y=[v_l], name="매수", mode="markers+text", text=[f"매수: {v_l:,}"], textposition="bottom center", marker=dict(color="red", size=12)))
            pos_fig.add_trace(go.Scatter(x=[0], y=[curr_stock_val], name="현재", mode="markers+text", text=[f"평가액: {curr_stock_val:,}"], textposition="middle right", marker=dict(color="green", size=18, symbol="diamond")))
            pos_fig.update_layout(title="현재 사이클 포지션 비주얼", xaxis=dict(showticklabels=False, range=[-1, 1]), height=350, showlegend=False)
            st.plotly_chart(pos_fig, use_container_width=True)

        l, r = st.columns(2)
        with l:
            st.markdown("#### 📉 BUY (매수 가이드)")
            if curr_stock_val < v_l:
                if ok:
                    st.info(f"매수 승인: 강도 {qta*100:.0f}%")
                    st.code(f"✅ LOC 추천가: {int(v_l/(qty+1)):,}원")
                else: st.error("🚫 안전장치 미충족: 매수 절대 금지")
            else: st.info("😴 관망 (평가액 > 하단 밴드)")
        with r:
            st.markdown("#### 📈 SELL (매도 가이드)")
            if curr_stock_val > v_u:
                st.code(f"🔥 LOC 추천가: {int(v1/(qty-1)):,}원")
            else: st.info("😴 관망 (평가액 < 상단 밴드)")

        st.divider()
        if not df_history.empty:
            st.subheader("📈 자산 성장 히스토리")
            hist_fig = go.Figure()
            hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['V_old'], name="목표(V)", line=dict(color='gray', dash='dash')))
            hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['Qty'] * m['price'], name="실제 평가액", line=dict(color='#00FF00', width=3)))
            # [추가] 과거 FnG 지수도 그래프에 점으로 표시 (선택사항)
            if 'FnG' in df_history.columns:
                hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['FnG'], name="과거 심리지수(FnG)", yaxis="y2", mode="markers", marker=dict(color="orange", size=8)))
            
            hist_fig.update_layout(
                xaxis_title="날짜", 
                yaxis_title="금액(원)", 
                yaxis2=dict(title="FnG", overlaying="y", side="right", range=[0, 100]),
                height=400
            )
            st.plotly_chart(hist_fig, use_container_width=True)

    with tab2:
        st.write("...중략 (기존 사용방법 멘트 유지)...")

    with tab3:
        st.write("...중략 (기존 안전장치 로직 멘트 유지)...")
