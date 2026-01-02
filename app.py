import streamlit as st
import pandas as pd
import yfinance as yf
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
        r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/static/history", headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        if r.status_code == 200: data["fng"] = float(r.json()['fear_and_greed']['score'])
        return data
    except: return data

m = get_market_intelligence()

# --- [2. 로직 함수] ---
def check_safety(dd, fng):
    if dd > -10: return True, 1.0, f"🟩 정상장 (DD {dd}%): 100% 가동 가능", "normal"
    elif -20 < dd <= -10:
        if fng <= 20: return True, 0.5, f"🟧 조정장 (DD {dd}%): 50% 제한 (FnG {fng})", "warning"
        else: return False, 0.0, f"🚫 조정장 대기: FnG {fng} (20 이하 필요)", "error"
    else:
        if fng <= 15: return True, 0.3, f"🚨 폭락장 (DD {dd}%): 30% 극보수 매수 (FnG {fng})", "critical"
        else: return False, 0.0, f"⛔ 폭락장 방어: FnG {fng} (15 이하 필요)", "error"

def get_recommended_band(dd, is_bull):
    if not is_bull or dd < -20: return 5, "🟥 하락장: 5% 추천"
    elif -20 <= dd < -10: return 7, "🟧 조정장: 7~10% 추천"
    return 10, "🟩 상승장: 10~15% 추천"

# --- [3. UI & 사이드바] ---
st.title("⚖️ ISA QLD VR STRATEGY MANAGER")

if m["price"] > 0:
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
            # [수정 포인트 1] usecols를 제거하여 Date(E열)까지 모든 데이터를 다 읽어옵니다.
            existing_data = conn.read(worksheet="ISA", ttl=0).dropna(how='all')
            if not existing_data.empty:
                last_row = existing_data.iloc[-1]
                # 컬럼명으로 접근하여 안전하게 데이터를 가져옵니다.
                default_qty = int(last_row.get('Qty', 0))
                default_pool = int(last_row.get('Pool', 0))
                default_v = int(last_row.get('V_old', 0))
                default_principal = int(last_row.get('Principal', 20566879))
                st.success("☁️ 데이터 로드 완료")
            else: raise Exception()
        except:
            default_qty, default_pool, default_v, default_principal = 0, 0, 0, 20566879
            st.warning("⚠️ 신규 시작 또는 데이터 없음")

        mode = st.radio("운용 모드", ["최초 시작", "사이클 업데이트"])
        principal = st.number_input("총 투입 원금 (원)", value=int(default_principal), step=10000)
        qty = st.number_input("보유 수량 (주)", value=int(default_qty), min_value=0)
        pool = st.number_input("Pool (현금)", value=int(default_pool), step=10000)
        
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
                v1 += add_
