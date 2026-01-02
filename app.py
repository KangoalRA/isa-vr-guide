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
        r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/static/history", headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        if r.status_code == 200: data["fng"] = float(r.json()['fear_and_greed']['score'])
        return data
    except: return data

m = get_market_intelligence()

# --- [2. 로직 함수: 안전장치 멘트 강화] ---
def check_safety(dd, fng):
    if dd > -10: 
        return True, 1.0, f"✅ 정상장 (DD {dd}%): 안전장치 미작동. 가용 현금 100% 매수 가능.", "normal"
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

# --- [UI 시작] ---
st.title("⚖️ ISA QLD VR STRATEGY MANAGER")

if m["price"] > 0:
    with st.sidebar:
        st.header("⚙️ 시장 지표")
        st.metric("나스닥 낙폭", f"{m['dd']}%")
        st.markdown("[👉 FnG 지수 (CNN)](https://edition.cnn.com/markets/fear-and-greed)")
        fng_input = st.number_input("FnG Index", value=float(m['fng']))
        st.divider()
        st.subheader("💾 자산 데이터 (ISA)")
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
            st.warning("⚠️ 신규 데이터 입력 필요")

        mode = st.radio("운용 모드", ["최초 시작", "사이클 업데이트"])
        principal = st.number_input("총 투입 원금 (원)", value=int(default_principal), step=10000)
        qty = st.number_input("보유 수량 (주)", value=int(default_qty), min_value=0)
        pool = st.number_input("Pool (현금/파킹)", value=int(default_pool), step=10000)
        band_pct = st.slider("밴드 설정 (%)", 5, 20, 10) / 100
        
        if mode == "최초 시작":
            v1 = m['price'] * qty
            v_to_save = v1
        else:
            v_old = st.number_input("직전 V1 (원)", value=int(default_v), step=10000)
            target_roi = st.slider("목표 수익률 (%)", 0.0, 1.5, 0.6, step=0.1) / 100
            v_to_save = int(v_old * (1 + target_roi))
            v1 = v_to_save
            add_cash = st.number_input("추가 입금액 (원)", value=0, step=10000)
            if add_cash > 0:
                v1 += add_cash
                principal += add_cash

        if st.button("💾 ISA 시트에 저장"):
            # 1. 저장할 데이터 생성 (날짜 포함)
            new_row = pd.DataFrame([{
                "Qty": qty, 
                "Pool": pool, 
                "V_old": v_to_save, 
                "Principal": principal, 
                "Date": datetime.now().strftime('%Y-%m-%d')
            }])
            
            # 2. 기존 데이터와 합치기 (데이터가 없을 경우 대비)
            if 'existing_data' in locals() and not existing_data.empty:
                updated_df = pd.concat([existing_data, new_row], ignore_index=True)
            else:
                updated_df = new_row
            
            # 3. 시트 업데이트
            conn.update(worksheet="ISA", data=updated_df)
            
            # 4. 캐시 삭제 및 성공 메시지 (날짜 표시로 확인 사살)
            st.cache_data.clear()
            st.success(f"✅ {datetime.now().strftime('%Y-%m-%d')} 기록이 E열에 저장되었습니다!")

    # --- 계산 ---
    v_l, v_u = int(v1 * (1 - band_pct)), int(v1 * (1 + band_pct))
    curr_stock_val = m['price'] * qty
    current_asset = curr_stock_val + pool
    ok, qta, msg, m_type = check_safety(m['dd'], fng_input)
    roi_pct = (current_asset / principal - 1) * 100 if principal > 0 else 0

    # 상단 요약
    c1, c2, c3 = st.columns(3)
    c1.metric("총 자산(평가금+현금)", f"{current_asset:,.0f}원")
    c2.metric("목표 V 대비 편차", f"{(curr_stock_val/v1-1)*100:.2f}%" if v1>0 else "0%")
    c3.metric("누적 수익률", f"{roi_pct:.2f}%")
    st.divider()

    # --- 메인 탭 ---
    tab1, tab2, tab3 = st.tabs(["📊 매매 가이드", "📋 사용방법(매뉴얼)", "🛡️ 안전장치 로직"])
    
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
                else: st.error("🚫 안전장치 작동: 매수 금지")
            else: st.info("😴 관망 (하단 밴드 미달)")
        with r:
            st.markdown("#### 📈 SELL (매도)")
            if curr_stock_val > v_u:
                for i in range(1, 5):
                    t_q = qty - i
                    if t_q > 0:
                        p = int(v1 / t_q)
                        if p > m['price']: st.code(f"🔥 LOC 매도: {p:,}원 ({qty-t_q}주 판매)")
            else: st.info("😴 관망 (상단 밴드 미달)")

        if st.button("✈️ 텔레그램 전송"):
            t_msg = f"[ISA QLD 리포트]\n📅 {datetime.now().strftime('%Y-%m-%d')}\n가격: {m['price']:,}원\n수익률: {roi_pct:.2f}%"
            send_telegram_msg(t_msg)

        if not existing_data.empty:
            st.subheader("📈 자산 성장 추이")
            hist_fig = go.Figure()
            hist_fig.add_trace(go.Scatter(x=existing_data.index, y=existing_data['V_old'], name="목표(V)", line=dict(color='gray', dash='dash')))
            hist_fig.add_trace(go.Scatter(x=existing_data.index, y=existing_data['Qty'] * m['price'], name="실제 평가액", line=dict(color='#00FF00', width=3)))
            st.plotly_chart(hist_fig, use_container_width=True)

    with tab2:
        st.markdown("### 📘 ISA-VR 실전 운영 매뉴얼")
        c1, c2 = st.columns(2)
        with c1:
            st.info("#### 1️⃣ 최초 시작 시 설정")
            st.write("""
            - **총 투입 원금:** ISA 계좌에 입금된 총액(현금+주식)을 입력합니다.
            - **운용 모드:** 반드시 '최초 시작'을 선택합니다.
            - **저장:** 현재의 수량과 원금을 시트에 기록하여 기준점(V)을 만듭니다.
            """)
        with c2:
            st.info("#### 2️⃣ 사이클 업데이트 (격주 월요일)")
            st.write("""
            - **운용 모드:** '사이클 업데이트'를 선택합니다.
            - **목표 수익률:** 2주간의 V값 성장률(0.6% 권장)을 설정합니다.
            - **추가 입금:** 계좌에 새로 돈을 넣었다면 '추가 입금액'에 입력합니다.
            """)
        st.success("""
        #### 💡 핵심 매매 루틴
        1. **격주 월요일 오후 3시:** 앱을 켜고 현재 수량과 현금을 입력합니다.
        2. **가이드 확인:** 매수/매도 신호가 뜨면 지시된 가격으로 **LOC 주문**을 넣습니다.
        3. **기록 저장:** 매매 후 반드시 **[💾 ISA 시트에 저장]** 버튼을 눌러 회차를 마감합니다.
        """)

    with tab3:
        st.markdown("### 🛡️ ISA-VR 이중 안전장치 (Safety Brake)")
        st.warning("폭락장에서 현금이 조기에 고갈되는 것을 막기 위해 **나스닥 낙폭(DD)**과 **공포지수(FnG)**를 동시에 체크합니다.")
        
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("1. 나스닥 낙폭 (DD) 기준")
            st.write("- **정상장 (-10% 이내):** 매수 가이드 금액의 **100% 가동**.")
            st.write("- **조정장 (-10% ~ -20%):** 리스크 관리를 위해 매수 강도를 **50%로 제한**.")
            st.write("- **폭락장 (-20% 초과):** 현금 보존을 위해 매수 강도를 **30%로 극도 제한**.")
        with col_b:
            st.subheader("2. 공포지수 (FnG) 승인 조건")
            st.write("- **조정장:** FnG 수치가 **20 이하(Extreme Fear)**일 때만 매수 신호가 승인됩니다.")
            st.write("- **폭락장:** FnG 수치가 **15 이하**로 떨어져 극도의 공포가 만연할 때만 보수적 매수를 승인합니다.")
        
        st.error("⚠️ **주의:** 주가가 매수 밴드(하단)에 진입했어도, 위 조건(DD+FnG)이 하나라도 충족되지 않으면 시스템은 **'매수 금지'** 상태를 유지하여 현금을 방어합니다.")

else:
    st.error("📉 데이터 로드 실패 (잠시 후 다시 시도하세요)")
