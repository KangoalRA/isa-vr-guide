import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime
import requests
from streamlit_gsheets import GSheetsConnection

# --- [0. 페이지 설정 및 제목] ---
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
            st.success(f"📈 {len(df_history)}회차 기록 로드됨")
        else: raise Exception()
    except:
        default_qty, default_pool, default_v, default_principal = 0, 0, 0, 20566879
        df_history = pd.DataFrame(columns=["Qty", "Pool", "V_old", "Principal", "Date", "FnG"])

    mode = st.radio("운용 모드", ["최초 시작", "사이클 업데이트"])
    principal = st.number_input("총 투입 원금 (원)", value=int(default_principal), step=10000)
    qty = st.number_input("보유 수량 (주)", value=int(default_qty), min_value=0)
    pool = st.number_input("Pool (현금/파킹)", value=int(default_pool), step=10000)
    
    if mode == "최초 시작":
        v1 = m['price'] * qty
        v_to_save = v1
    else:
        v_old = st.number_input("직전 V1 (원)", value=int(default_v), step=10000)
        target_roi = st.slider("목표 수익률 (%)", 0.0, 1.5, 0.6, step=0.1) / 100
        v_to_save = int(v_old * (1 + target_roi))
        v1 = v_to_save
        add_cash = st.number_input("추가 입금액 (원)", value=0, step=10000)
        if add_cash > 0: v1 += add_cash; principal += add_cash

    if st.button("💾 ISA 시트에 저장"):
        new_row = pd.DataFrame([{
            "Qty": qty, "Pool": pool, "V_old": v_to_save, 
            "Principal": principal, "Date": datetime.now().strftime('%Y-%m-%d'),
            "FnG": fng_input
        }])
        updated_df = pd.concat([df_history, new_row], ignore_index=True)
        conn.update(worksheet="ISA", data=updated_df)
        st.cache_data.clear() 
        st.success("✅ 저장 완료!")

# --- [4. 메인 화면] ---
tab1, tab2, tab3 = st.tabs(["📊 매매 가이드", "📋 사용방법", "🛡️ 안전장치 로직"])

with tab1:
    if v1 > 0 and m["price"] > 0:
        v_l, v_u = int(v1 * (1 - band_pct)), int(v1 * (1 + band_pct))
        curr_stock_val = m['price'] * qty
        current_asset = curr_stock_val + pool
        ok, qta, msg, m_type = check_safety(m['dd'], fng_input)
        roi_pct = (current_asset / principal - 1) * 100 if principal > 0 else 0

        c1, c2, c3 = st.columns(3)
        c1.metric("총 자산", f"{current_asset:,.0f}원")
        c2.metric("V 대비 편차", f"{(curr_stock_val/v1-1)*100:.2f}%")
        c3.metric("누적 수익률", f"{roi_pct:.2f}%")
        st.divider()

        if m_type == "normal": st.success(msg)
        elif m_type == "warning": st.warning(msg)
        else: st.error(msg)
        
        # 포지션 그래프
        pos_fig = go.Figure()
        pos_fig.add_trace(go.Scatter(x=[0], y=[v_u], name="매도", mode="markers+text", text=[f"매도: {v_u:,}"], textposition="top center", marker=dict(color="blue", size=12)))
        pos_fig.add_trace(go.Scatter(x=[0], y=[v_l], name="매수", mode="markers+text", text=[f"매수: {v_l:,}"], textposition="bottom center", marker=dict(color="red", size=12)))
        pos_fig.add_trace(go.Scatter(x=[0], y=[curr_stock_val], name="현재", mode="markers+text", text=[f"평가액: {curr_stock_val:,}"], textposition="middle right", marker=dict(color="green", size=18, symbol="diamond")))
        pos_fig.update_layout(title="현재 사이클 포지션", xaxis=dict(showticklabels=False, range=[-1, 1]), height=300, showlegend=False)
        st.plotly_chart(pos_fig, use_container_width=True)

        l, r = st.columns(2)
        with l:
            st.markdown("#### 📉 BUY (매수)")
            if curr_stock_val < v_l:
                if ok:
                    st.info(f"매수 승인: 강도 {qta*100:.0f}%")
                    st.code(f"✅ LOC 추천가: {int(v_l/(qty+1)):,}원")
                else: st.error("🚫 안전장치 차단: 매수 금지")
            else: st.info("😴 매수 관망")
        with r:
            st.markdown("#### 📈 SELL (매도)")
            if curr_stock_val > v_u:
                st.code(f"🔥 LOC 추천가: {int(v1/(qty-1)):,}원")
            else: st.info("😴 매도 관망")

        # [통합 그래프] 자산 히스토리 + FnG
        if not df_history.empty:
            st.divider()
            st.subheader("📈 통합 성장 히스토리 (자산 & 심리)")
            combined_fig = go.Figure()
            combined_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['V_old'], name="목표(V)", line=dict(color='gray', dash='dash')))
            combined_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['Qty'] * m['price'], name="실제 평가액", line=dict(color='#00FF00', width=3)))
            if 'FnG' in df_history.columns:
                combined_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['FnG'], name="당시 FnG", yaxis="y2", mode="markers+lines", marker=dict(color="orange", size=6), line=dict(width=1, dash='dot')))
            combined_fig.update_layout(
                yaxis=dict(title="자산 평가액 (원)"),
                yaxis2=dict(title="공포지수 (FnG)", overlaying="y", side="right", range=[0, 100]),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                height=450
            )
            st.plotly_chart(combined_fig, use_container_width=True)
    else:
        st.info("💡 사이드바에서 보유 수량을 입력하고 저장하면 매매 가이드가 표시됩니다.")

with tab2:
    st.markdown("### 📘 ISA VR 실전 사용 매뉴얼")
    st.success("#### 🟢 상승장 (매도 타임)\n- 평가액이 파란색 **매도선**을 넘으면 수익 실현 타이밍입니다.\n- 가이드 가격으로 매도 주문을 넣고, 판 돈은 **Pool(현금)**에 보관하세요. 💰")
    st.warning("#### 🟡 횡보장 (관망 타임)\n- 주가가 밴드 안에서 움직이면 아무것도 하지 않는 것이 핵심입니다.\n- 매회차 V값을 조금씩 늘려가며 자산의 기초 체력을 키웁니다. ☕")
    st.error("#### 🔴 하락장 (매수 타임)\n- 평가액이 빨간색 **매수선** 아래로 떨어지면 줍줍 타이밍입니다.\n- 단, **안전장치(탭3)**가 허락할 때만 현금을 투입하여 생존을 우선합니다. 📉")
    st.divider()
    st.write("**📝 매매 운영 루틴**\n1. 격주 월요일 오후 3시: 수량과 현금을 정확히 입력\n2. 저장: '사이클 업데이트' 모드로 기록 저장\n3. 주문: LOC 예약 주문 실행")

with tab3:
    st.markdown("### 🛡️ ISA-VR 이중 안전장치 설정 원리")
    st.info("시장의 폭락장에서 현금이 고갈되는 것을 방지하기 위해 **나스닥 낙폭(DD)**과 **공포지수(FnG)**를 동시 체크합니다. ⚙️")
    c_a, c_b = st.columns(2)
    with c_a:
        st.subheader("1️⃣ 나스닥 낙폭 (DD) 기준")
        st.write("- **정상장 (-10% 이내):** 가용 현금의 **100% 가동** 가능. 👍\n- **조정장 (-10% ~ -20%):** 매수 강도를 **50%로 제한**. ✋\n- **폭락장 (-20% 초과):** 매수 강도를 **30%로 극도 제한**. 🚨")
    with c_b:
        st.subheader("2️⃣ 공포지수 (FnG) 승인 조건")
        st.write("- **조정장 진입 시:** FnG가 **20 이하**일 때만 매수 승인.\n- **폭락장 진입 시:** FnG가 **15 이하**일 때만 매수 승인.")
