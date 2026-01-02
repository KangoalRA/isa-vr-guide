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
            # 전체 데이터를 읽어와서 마지막 줄 추출
            existing_data = conn.read(worksheet="ISA", usecols=[0, 1, 2, 3], ttl=0).dropna()
            if not existing_data.empty:
                last_row = existing_data.iloc[-1]
                default_qty, default_pool, default_v, default_principal = int(last_row.iloc[0]), int(last_row.iloc[1]), int(last_row.iloc[2]), int(last_row.iloc[3])
                st.success("☁️ 최신 기록 로드 완료")
            else: raise Exception()
        except:
            default_qty, default_pool, default_v, default_principal = 0, 0, 0, 20566879
            st.warning("⚠️ 신규 시작 모드")

        mode = st.radio("작업 선택", ["최초 시작", "사이클 업데이트"])
        principal = st.number_input("총 투입 원금", value=int(default_principal))
        qty = st.number_input("보유 수량", value=int(default_qty), min_value=0)
        pool = st.number_input("Pool (현금/파킹)", value=int(default_pool))
        
        if mode == "최초 시작":
            v1 = m['price'] * qty
        else:
            v_old = st.number_input("직전 목표V", value=int(default_v))
            v1 = int(v_old * 1.006) # 격주 0.6% 증액
            
        if st.button("💾 이 포지션 시트에 저장"):
            # 기존 데이터에 새로운 줄 추가 (Append)
            new_row = pd.DataFrame([{"Qty": qty, "Pool": pool, "V_old": v1, "Principal": principal}])
            updated_df = pd.concat([existing_data, new_row], ignore_index=True) if 'existing_data' in locals() else new_row
            conn.update(worksheet="ISA", data=updated_df)
            st.success("✅ 새로운 사이클 기록 완료!")

    # --- 계산 ---
    curr_v = m['price'] * qty
    v_l, v_u = int(v1 * (1 - band_pct)), int(v1 * (1 + band_pct))
    current_asset = curr_v + pool
    ok, qta, msg, m_type = check_safety(m['dd'], fng_input)

    # 상단 요약 지표
    col1, col2, col3 = st.columns(3)
    col1.metric("총 자산 (평가금+Pool)", f"{current_asset:,.0f}원")
    col2.metric("목표 V 대비 위치", f"{(curr_v/v1-1)*100:.2f}%" if v1>0 else "0%")
    col3.metric("누적 수익률", f"{(current_asset/principal-1)*100:.2f}%" if principal>0 else "0%")

    st.divider()
    
    # 탭 구성
    tab1, tab2, tab3 = st.tabs(["📊 매매 가이드 & 그래프", "📋 상세 운영법", "🛡️ 안전장치 설명"])
    
    with tab1:
        if m_type == "normal": st.success(msg)
        else: st.error(msg)

        # 매매 가이드 구역
        l, r = st.columns(2)
        with l:
            st.markdown("#### 📉 매수 가이드")
            if curr_v < v_l and ok: 
                target_p = int(v_l / (qty + 1))
                st.code(f"✅ LOC 매수 추천가: {target_p:,}원")
            else: st.info("매수 조건이 아닙니다.")
        with r:
            st.markdown("#### 📈 매도 가이드")
            if curr_v > v_u and qty > 0:
                target_p = int(v1 / (qty - 1))
                st.code(f"🔥 LOC 매도 추천가: {target_p:,}원")
            else: st.info("매도 조건이 아닙니다.")
        
        st.divider()
        
        # 📊 [그래프 위치 변경] 가이드 바로 아래에 배치
        if v1 > 0:
            fig = go.Figure()
            fig.add_shape(type="line", x0=-0.5, x1=0.5, y0=v_u, y1=v_u, line=dict(color="RoyalBlue", width=2, dash="dash"))
            fig.add_shape(type="line", x0=-0.5, x1=0.5, y0=v_l, y1=v_l, line=dict(color="Crimson", width=2, dash="dash"))
            fig.add_trace(go.Scatter(x=[0], y=[v_u], name="매도선", mode="markers+text", text=[f"상단(매도): {v_u:,}"], textposition="top center", marker=dict(color="blue", size=12)))
            fig.add_trace(go.Scatter(x=[0], y=[v_l], name="매수선", mode="markers+text", text=[f"하단(매수): {v_l:,}"], textposition="bottom center", marker=dict(color="red", size=12)))
            fig.add_trace(go.Scatter(x=[0], y=[curr_v], name="현재가", mode="markers+text", text=[f"내 위치: {curr_v:,}"], textposition="middle right", marker=dict(color="green", size=18, symbol="diamond")))
            
            fig.update_layout(title=f"현재 VR 포지션 (목표V: {v1:,}원)", yaxis_title="평가금액 (원)", xaxis=dict(showticklabels=False, range=[-1, 1]), height=400, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

        if st.button("✈️ 텔레그램으로 오늘 리포트 쏘기"):
            t_msg = f"[ISA QLD 리포트]\n📅 {datetime.now().strftime('%Y-%m-%d')}\n현재가: {m['price']:,}원\n수익률: {(current_asset/principal-1)*100:.2f}%"
            send_telegram_msg(t_msg)

    with tab2:
        st.write("격주 월요일 오후 3시 리밸런싱 지침 준수")
        # (기존 매뉴얼 내용 생략...)

    with tab3:
        st.write("DD 및 FnG 기반 안전장치 작동 중")
        # (기존 안전장치 내용 생략...)
