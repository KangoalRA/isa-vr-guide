import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime
import requests
import time
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
    except Exception as e:
        st.error(f"텔레그램 전송 실패: {e}")

# --- [🛡️ 안전한 데이터 수집 함수] ---
def get_data_safe(ticker, period="5d"):
    for i in range(3):
        try:
            df = yf.Ticker(ticker).history(period=period)
            if not df.empty: return df
            time.sleep(1) 
        except: time.sleep(1)
    return pd.DataFrame() 

# --- [1. 시장 데이터 수집] ---
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
    except Exception as e: return data

m = get_market_intelligence()

# --- [2. 로직 함수] ---
def check_safety(dd, fng):
    if dd > -10: return True, 1.0, f"🟩 정상장 (DD {dd}%): 100% 가동 가능", "normal"
    elif -20 < dd <= -10:
        if fng <= 20: return True, 0.5, f"🟧 조정장 (DD {dd}%): 50% 제한 (FnG {fng})", "warning"
        else: return False, 0.0, f"🚫 조정장 대기: FnG {fng} (20 필요)", "error"
    else:
        if fng <= 15: return True, 0.3, f"🚨 폭락장 (DD {dd}%): 30% 제한 (FnG {fng})", "critical"
        else: return False, 0.0, f"🚫 하락장 방어: FnG {fng} (15 필요)", "error"

def get_recommended_band(dd, is_bull):
    if not is_bull or dd < -20: return 5, "🟥 하락장: 5% 추천"
    elif -20 <= dd < -10: return 7, "🟧 조정장: 7% ~ 10% 추천"
    return 10, "🟩 상승장: 10% ~ 15% 추천"

# --- [UI 시작] ---
st.title("⚖️ ISA VR 매매 사용 가이드")

if m["price"] > 0:
    # 1. 좌측 UI 패널 (절대 수정 금지 원칙 준수)
    with st.sidebar:
        st.header("⚙️ 시장 지표")
        st.metric("나스닥 낙폭", f"{m['dd']}%")
        st.markdown("[👉 FnG 지수 (CNN)](https://edition.cnn.com/markets/fear-and-greed)")
        fng_input = st.number_input("FnG Index", value=float(m['fng']))
        st.divider()
        st.subheader("🛠️ 밴드폭 추천")
        rec_val, rec_msg = get_recommended_band(m['dd'], m['bull'])
        st.info(rec_msg)
        band_pct = st.slider("밴드 설정 (%)", 5, 20, rec_val) / 100
        st.divider()
        st.subheader("💾 자산 데이터 (ISA)")
        conn = st.connection("gsheets", type=GSheetsConnection)
        
        try:
            # Date열(인덱스 4)까지 포함하여 로드
            existing_data = conn.read(worksheet="ISA", ttl=0).dropna(how='all')
            if not existing_data.empty:
                last_row = existing_data.iloc[-1]
                default_qty = int(last_row.iloc[0])
                default_pool = int(last_row.iloc[1])
                default_v = int(last_row.iloc[2])
                default_principal = int(last_row.iloc[3]) if len(last_row) > 3 else 20566879
                st.success(f"☁️ 데이터 로드 완료")
            else: raise Exception()
        except:
            default_qty, default_pool, default_v, default_principal = 0, 0, 0, 0
            st.warning("⚠️ 신규 시작 또는 데이터 없음")

        mode = st.radio("운용 모드", ["최초 시작", "사이클 업데이트"])
        principal = st.number_input("총 투입 원금 (원)", value=int(default_principal), step=10000)
        qty = st.number_input("보유 수량 (주)", value=int(default_qty), min_value=0)
        pool = st.number_input("Pool (파킹ETF 평가금)", value=int(default_pool), step=10000)
        
        if mode == "최초 시작":
            v1 = m['price'] * qty
            v_to_save = v1
        else:
            v_old = st.number_input("직전 V1 (원)", value=int(default_v), step=10000)
            target_roi = st.slider("이번 텀 목표 수익률 (%)", 0.0, 1.5, 0.5, step=0.1) / 100
            v_to_save = int(v_old * (1 + target_roi))
            v1 = v_to_save
            add_cash = st.number_input("추가 입금액 (원)", value=0, step=10000)
            if add_cash > 0:
                v1 += add_cash
                principal += add_cash

        if st.button("💾 ISA 시트에 저장"):
            # E열에 날짜 데이터 추가
            new_row = pd.DataFrame([{
                "Qty": qty, "Pool": pool, "V_old": v_to_save, 
                "Principal": principal, "Date": datetime.now().strftime('%Y-%m-%d')
            }])
            updated_df = pd.concat([existing_data, new_row], ignore_index=True) if not existing_data.empty else new_row
            conn.update(worksheet="ISA", data=updated_df)
            st.cache_data.clear() # 그래프 갱신용 캐시 삭제
            st.success("✅ 저장 완료 (날짜 기록됨)!")

    # --- 계산 및 메인 화면 ---
    v_l, v_u = int(v1 * (1 - band_pct)), int(v1 * (1 + band_pct))
    curr_stock_val = m['price'] * qty
    current_asset = curr_stock_val + pool
    ok, qta, msg, m_type = check_safety(m['dd'], fng_input)
    roi_pct = (current_asset / principal - 1) * 100 if principal > 0 else 0

    st.subheader(f"📈 KODEX QLD 현재가: {m['price']:,}원")
    c1, c2, c3 = st.columns(3)
    c1.metric("총 투입 원금", f"{principal:,.0f}원")
    c2.metric("ISA 총 자산", f"{current_asset:,.0f}원", delta=f"{current_asset-principal:,.0f}원")
    c3.metric("누적 수익률", f"{roi_pct:.2f}%")
    st.divider()

    # 탭 구성 (가이드, 사용방법, 안전장치)
    tab1, tab2, tab3 = st.tabs(["📊 매매 가이드 & 그래프", "📋 사용방법", "🛡️ 안전장치 설정"])
    
    with tab1:
        if m_type == "normal": st.success(msg)
        elif m_type == "warning": st.warning(msg)
        else: st.error(msg)
        
        # 1. 포지션 시각화 그래프
        if v1 > 0:
            pos_fig = go.Figure()
            pos_fig.add_trace(go.Scatter(x=[0], y=[v_u], name="매도선", mode="markers+text", text=[f"매도: {v_u:,}"], textposition="top center", marker=dict(color="blue", size=12)))
            pos_fig.add_trace(go.Scatter(x=[0], y=[v_l], name="매수선", mode="markers+text", text=[f"매수: {v_l:,}"], textposition="bottom center", marker=dict(color="red", size=12)))
            pos_fig.add_trace(go.Scatter(x=[0], y=[curr_stock_val], name="현재", mode="markers+text", text=[f"평가액: {curr_stock_val:,}"], textposition="middle right", marker=dict(color="green", size=18, symbol="diamond")))
            pos_fig.update_layout(title="현재 사이클 포지션", yaxis_title="금액(원)", xaxis=dict(showticklabels=False, range=[-1, 1]), height=400, showlegend=False)
            st.plotly_chart(pos_fig, use_container_width=True)

        # 2. 매수/매도 상세 가이드
        l, r = st.columns(2)
        telegram_msg = f"[ISA QLD 리포트]\n📅 {datetime.now().strftime('%Y-%m-%d')}\n상태: {msg}\n"
        with l:
            st.markdown("#### 📉 매수 가이드")
            if curr_stock_val < v_l:
                if ok:
                    st.write(f"쿼터 {qta*100:.0f}% 적용")
                    for i in range(1, 10): 
                        t_q = qty + i
                        p = int(v_l / t_q)
                        if p < m['price'] * 1.05:
                            st.code(f"✅ LOC 매수: {p:,}원 ({t_q}주)")
                            telegram_msg += f"✅ 매수: {p:,}원\n"
                else: st.error("🚫 안전장치 작동: 매수 금지")
            else: st.info("😴 매수 관망 (밴드 상단)")
        with r:
            st.markdown("#### 📈 매도 가이드")
            if curr_stock_val > v_u:
                for i in range(1, 5):
                    t_q = qty - i
                    if t_q > 0:
                        p = int(v1 / t_q)
                        if p > m['price']:
                            st.code(f"🔥 LOC 매도: {p:,}원 ({qty-t_q}주 판매)")
                            telegram_msg += f"🔥 매도: {p:,}원\n"
            else: st.info("😴 매도 관망 (밴드 하단)")
        
        st.divider()
        # 3. DB 기반 누적 성장 그래프
        if not existing_data.empty:
            st.subheader("📈 자산 성장 히스토리 (DB 연동)")
            hist_fig = go.Figure()
            hist_fig.add_trace(go.Scatter(x=existing_data['Date'], y=existing_data['V_old'], name="목표 가치(V)", line=dict(color='gray', dash='dash')))
            hist_fig.add_trace(go.Scatter(x=existing_data['Date'], y=existing_data['Qty'] * m['price'], name="실제 주식 평가액", line=dict(color='#00FF00', width=3)))
            hist_fig.update_layout(xaxis_title="기록 날짜", yaxis_title="금액(원)", height=400)
            st.plotly_chart(hist_fig, use_container_width=True)

        if st.button("✈️ 텔레그램 전송"): send_telegram_msg(telegram_msg)

    with tab2:
        st.markdown("### 📘 ISA VR 실전 사용방법")
        st.success("#### 🟢 상승장 대응 (매도 시기)\n- 주가 평가액이 파란색 **매도선(110%)**을 넘으면 수익 실현 타이밍입니다.\n- 가이드에 나온 가격으로 매도 주문을 넣고, 판 돈은 **Pool(현금)**에 보관하세요.")
        st.warning("#### 🟡 횡보장 대응 (관망 시기)\n- 주가가 밴드 안에서 움직이면 아무것도 하지 않습니다.\n- 매회차 V값을 조금씩 늘려가며(0.6% 권장) 자산의 기초 체력을 키웁니다.")
        st.error("#### 🔴 하락장 대응 (매수 시기)\n- 주가 평가액이 빨간색 **매수선(90%)** 아래로 떨어지면 줍줍 타이밍입니다.\n- 단, **안전장치(탭3)**가 허락할 때만 현금을 투입하여 생존을 우선합니다.")
        st.divider()
        st.markdown("""
        **📝 운영 루틴**
        1. **격주 월요일 오후 3시:** 앱을 켜고 현재 수량과 현금을 입력한다.
        2. **저장:** '사이클 업데이트' 모드로 이번 회차 기록을 저장한다. (E열 날짜 기록 확인)
        3. **주문:** 가이드가 제시한 가격으로 **LOC 예약 주문**을 넣는다.
        """)

    with tab3:
        st.markdown("### 🛡️ ISA-VR 이중 안전장치 설정")
        st.info("시장의 폭락장에서 현금이 고갈되는 것을 방지하기 위해 아래 두 지표를 동시 체크합니다.")
        c_a, c_b = st.columns(2)
        with c_a:
            st.subheader("1️⃣ 나스닥 낙폭 (DD)")
            st.write("- **정상 (-10% 이내):** 매수 강도 100% 🚀")
            st.write("- **조정 (-20% 이내):** 매수 강도 50% ⚠️")
            st.write("- **폭락 (-20% 초과):** 매수 강도 30% 🚨")
        with c_b:
            st.subheader("2️⃣ 공포지수 (FnG)")
            st.write("- **조정장 통과:** 20 이하 시에만 매수 승인")
            st.write("- **폭락장 통과:** 15 이하 시에만 매수 승인")
        st.divider()
        st.warning("⚠️ **핵심 원칙:** 주가가 싸 보인다고 사는 것이 아니라, **시장이 공포에 질렸을 때만** 기계적으로 현금을 투입합니다.")

else:
    st.error("📉 데이터 로드 실패 (잠시 후 다시 시도하세요)")
