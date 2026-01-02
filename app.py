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
            st.warning("⚠️ 데이터 없음: 최초 시작 필요")

        mode = st.radio("모드", ["최초 시작", "사이클 업데이트"])
        principal = st.number_input("총 투입 원금", value=int(default_principal))
        qty = st.number_input("보유 수량", value=int(default_qty), min_value=0)
        pool = st.number_input("Pool (현금/파킹)", value=int(default_pool))
        
        if mode == "최초 시작":
            v1 = m['price'] * qty
        else:
            v_old = st.number_input("직전 V1", value=int(default_v))
            # ISA는 2주 주기이므로 약 0.6% 증액 (기울기)
            v1 = int(v_old * 1.006) 
            
        if st.button("💾 시트 저장"):
            new_data = pd.DataFrame([{"Qty": qty, "Pool": pool, "V_old": v1, "Principal": principal}])
            conn.update(worksheet="ISA", data=new_data)
            st.success("저장 완료")

    # --- 계산 ---
    v_l, v_u = int(v1 * (1 - band_pct)), int(v1 * (1 + band_pct))
    curr_v = m['price'] * qty
    ok, qta, msg, m_type = check_safety(m['dd'], fng_input)

    # --- 📊 VR 시각화 그래프 ---
    if v1 > 0:
        fig = go.Figure()
        # 밴드 라인 (수평선)
        fig.add_shape(type="line", x0=-0.5, x1=0.5, y0=v_u, y1=v_u, line=dict(color="RoyalBlue", width=2, dash="dash"))
        fig.add_shape(type="line", x0=-0.5, x1=0.5, y0=v_l, y1=v_l, line=dict(color="Crimson", width=2, dash="dash"))
        
        # 포인트 표시
        fig.add_trace(go.Scatter(x=[0], y=[v_u], name="매도선", mode="markers+text", text=[f"매도선: {v_u:,}"], textposition="top center", marker=dict(color="blue", size=12)))
        fig.add_trace(go.Scatter(x=[0], y=[v_l], name="매수선", mode="markers+text", text=[f"매수선: {v_l:,}"], textposition="bottom center", marker=dict(color="red", size=12)))
        fig.add_trace(go.Scatter(x=[0], y=[curr_v], name="현재 평가금", mode="markers+text", text=[f"현재: {curr_v:,}"], textposition="middle right", marker=dict(color="green", size=18, symbol="diamond")))
        
        # 레이아웃 수정 (ValueError 해결 포인트)
        fig.update_layout(
            title=f"VR 포지션 현황 (목표V: {v1:,}원)",
            yaxis_title="평가금 (원)",
            xaxis=dict(showticklabels=False, range=[-1, 1]),
            height=450,
            showlegend=False
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("💡 최초 시작 버튼을 눌러 데이터를 저장하면 그래프가 표시됩니다.")

    # --- 하단 대시보드 및 탭 ---
    current_asset = curr_v + pool
    col1, col2, col3 = st.columns(3)
    col1.metric("총 자산", f"{current_asset:,.0f}원")
    col2.metric("목표 V 대비", f"{(curr_v/v1-1)*100:.2f}%" if v1>0 else "0%")
    col3.metric("수익률", f"{(current_asset/principal-1)*100:.2f}%" if principal>0 else "0%")

    st.divider()
    tab1, tab2, tab3 = st.tabs(["📊 매매 가이드", "📋 상세 정보", "🛡️ 리스크 관리"])
    
    with tab1:
        if m_type == "normal": st.success(msg)
        else: st.error(msg)
        l, r = st.columns(2)
        with l:
            st.markdown("#### 📉 매수")
            if curr_v < v_l and ok: 
                # 다음 매수 가격 계산 (1주 추가 시 v_l에 도달하는 가격)
                target_p = int(v_l / (qty + 1))
                st.code(f"✅ LOC 매수 추천: {target_p:,}원")
            else: st.info("매수 조건 미달")
        with r:
            st.markdown("#### 📈 매도")
            if curr_v > v_u and qty > 0:
                # 다음 매도 가격 계산 (1주 감소 시 v1에 도달하는 가격)
                target_p = int(v1 / (qty - 1))
                st.code(f"🔥 LOC 매도 추천: {target_p:,}원")
            else: st.info("매도 조건 미달")
            
        if st.button("✈️ 텔레그램 리포트 전송"):
            t_msg = f"[ISA QLD 리포트]\n📅 {datetime.now().strftime('%Y-%m-%d')}\n가격: {m['price']:,}원\n상태: {msg}\n수익률: {(current_asset/principal-1)*100:.2f}%"
            send_telegram_msg(t_msg)

    with tab2:
        st.markdown("### 📘 ISA-VR 실전 운용 매뉴얼")
        st.markdown("""
        * **거래일:** 격주 월요일 오후 3시 (미국 금요일 종가 반영)
        * **종목:** KODEX 미국나스닥100레버리지 (409820.KS)
        * **밴드폭:** 10% ~ 15% 권장
        * **기울기:** 2주당 0.5% ~ 0.8% 목표 (코드엔 기본 0.6% 설정됨)
        """)

    with tab3:
        st.markdown("### 🛡️ ISA-VR 이중 안전장치")
        col_a, col_b = st.columns(2)
        with col_a:
            st.info("#### 1. 나스닥 낙폭 (DD)")
            st.write("- 정상장 (-10%): 가용현금 100%\n- 조정장 (-20%): 가용현금 50%\n- 하락장 (-20%↓): 가용현금 30%")
        with col_b:
            st.warning("#### 2. 공포지수 (FnG)")
            st.write("- 조정장: 20 이하 시 매수\n- 하락장: 15 이하 시 매수\n- 미달 시 시스템 강제 차단")
