import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime
import requests
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

# --- [1. 데이터 수집: 국내장 QLD + 나스닥 지수] ---
@st.cache_data(ttl=600)
def get_market_intelligence():
    data = {"price": 0, "dd": 0.0, "fng": 25.0, "bull": True}
    try:
        # KODEX 미국나스닥100레버리지 (409820.KS)
        ticker = "409820.KS" 
        t_hist = yf.Ticker(ticker).history(period="5d")
        
        if not t_hist.empty:
            data["price"] = int(t_hist['Close'].iloc[-1])
        
        # 나스닥 지수 (시장 상황 판단용)
        n_hist = yf.Ticker("^NDX").history(period="2y")
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

    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return data

m = get_market_intelligence()

# --- [2. 로직 함수 (원화 버전)] ---
def check_safety(dd, fng):
    # ISA는 장기/안정형이므로 본진보다 조금 더 보수적 기준 적용
    if dd > -10: return True, 1.0, "🟩 정상장: 100% 가동", "normal"
    elif -20 < dd <= -10:
        if fng <= 20: return True, 0.5, "🟧 조정장: 50% (FnG 20↓)", "warning"
        else: return False, 0.0, f"🚫 조정장 대기: FnG {fng} (20 필요)", "error"
    else:
        if fng <= 15: return True, 0.3, "🟥 하락장: 30% (FnG 15↓)", "critical"
        else: return False, 0.0, f"🚫 하락장 방어: FnG {fng} (15 필요)", "error"

def get_recommended_band(dd, is_bull):
    # QLD(2배)는 변동성이 TQQQ보다 작으므로 밴드를 좁게 잡음
    if not is_bull or dd < -20: return 5, "🟥 하락장: 방어 위해 5% 추천"
    elif -20 <= dd < -10: return 7, "🟧 조정장: 7% ~ 10% 추천"
    elif dd >= -10 and is_bull: return 10, "🟩 상승장: 10% ~ 15% 추천"
    return 10, "⬜ 일반: 10% 추천"

# --- [UI 시작] ---
st.title("🇰🇷 ISA 매매 가이드 (KODEX QLD)")

with st.expander("📘 ISA 운영 매뉴얼 (격주 월요일 추천)", expanded=False):
    st.markdown("""
    * **종목:** KODEX 미국나스닥100레버리지 (409820.KS)
    * **거래일:** **격주 월요일 오후 3시** (미국 금요일 장 마감 반영)
    * **Pool:** '파킹 ETF' 등의 현재 평가금액을 입력
    * **목표:** 연 10~15% 수준의 안정적 우상향
    """)

if m["price"] > 0:
    with st.sidebar:
        st.header("⚙️ 시장 지표 (나스닥)")
        st.metric("나스닥 낙폭", f"{m['dd']}%")
        st.markdown("[👉 FnG 지수 (CNN)](https://edition.cnn.com/markets/fear-and-greed)")
        fng_input = st.number_input("FnG Index", value=float(m['fng']))
        
        st.divider()
        st.subheader("🛠️ 밴드폭 추천 (QLD 전용)")
        rec_val, rec_msg = get_recommended_band(m['dd'], m['bull'])
        st.info(rec_msg)
        band_pct = st.slider("밴드 설정 (%)", 5, 20, rec_val) / 100
        
        st.divider()
        
        # --- 구글 시트 연결 (ISA 시트 사용) ---
        st.subheader("💾 자산 데이터 (ISA)")
        conn = st.connection("gsheets", type=GSheetsConnection)
        
        # [중요] 구글 시트에 'ISA' 라는 이름의 탭(시트)가 있어야 함
        try:
            existing_data = conn.read(worksheet="ISA", usecols=[0, 1, 2, 3], ttl=0).dropna()
            if not existing_data.empty:
                last_row = existing_data.iloc[-1]
                default_qty = int(last_row.iloc[0])
                default_pool = int(last_row.iloc[1])
                default_v = int(last_row.iloc[2])
                default_principal = int(last_row.iloc[3]) if len(last_row) > 3 else 20566879
                st.success(f"☁️ ISA 데이터 로드 완료")
            else:
                raise Exception("Data Empty")
        except:
            default_qty, default_pool, default_v, default_principal = 0, 0, 0, 0
            st.warning("⚠️ 신규 시작: 초기값 0원 (입력 필요)")

        mode = st.radio("운용 모드", ["최초 시작", "사이클 업데이트"])
        
        principal = st.number_input("총 투입 원금 (원)", value=int(default_principal), step=10000)
        qty = st.number_input("보유 수량 (주)", value=int(default_qty), min_value=1)
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
            new_data = pd.DataFrame([{"Qty": qty, "Pool": pool, "V_old": v_to_save, "Principal": principal}])
            conn.update(worksheet="ISA", data=new_data)
            st.success("✅ ISA 데이터 저장 완료!")

    # --- 계산 로직 ---
    v_l = int(v1 * (1 - band_pct))
    v_u = int(v1 * (1 + band_pct))
    ok, qta, msg, m_type = check_safety(m['dd'], fng_input)
    
    current_asset
