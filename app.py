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

# --- [🛡️ 안전한 데이터 수집 함수 (재시도 로직)] ---
def get_data_safe(ticker, period="5d"):
    for i in range(3):
        try:
            df = yf.Ticker(ticker).history(period=period)
            if not df.empty:
                return df
            time.sleep(1) 
        except:
            time.sleep(1)
    return pd.DataFrame() 

# --- [1. 시장 데이터 수집] ---
@st.cache_data(ttl=600)
def get_market_intelligence():
    data = {"price": 0, "dd": 0.0, "fng": 25.0, "bull": True}
    try:
        # 1. KODEX QLD (409820.KS)
        t_hist = get_data_safe("409820.KS", period="5d")
        if not t_hist.empty:
            data["price"] = int(t_hist['Close'].iloc[-1])
        
        # 2. 나스닥 지수
        n_hist = get_data_safe("^NDX", period="2y")
        if not n_hist.empty:
            ndx_high = n_hist['Close'].max()
            curr_ndx = n_hist['Close'].iloc[-1]
            data["dd"] = round((curr_ndx / ndx_high - 1) * 100, 2)
            data["bull"] = curr_ndx > n_hist['Close'].rolling(window=200).mean().iloc[-1]
        
        # 3. 공포지수
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/static/history", headers=headers, timeout=3)
            if r.status_code == 200: data["fng"] = float(r.json()['fear_and_greed']['score'])
        except: pass
        
        return data

    except Exception as e:
        return data

m = get_market_intelligence()

# --- [2. 로직 함수] ---
def check_safety(dd, fng):
    if dd > -10: return True, 1.0, "🟩 정상장: 100% 가동", "normal"
    elif -20 < dd <= -10:
        if fng <= 20: return True, 0.5, "🟧 조정장: 50% (FnG 20↓)", "warning"
        else: return False, 0.0, f"🚫 조정장 대기: FnG {fng} (20 필요)", "error"
    else:
        if fng <= 15: return True, 0.3, "🟥 하락장: 30% (FnG 15↓)", "critical"
        else: return False, 0.0, f"🚫 하락장 방어: FnG {fng} (15 필요)", "error"

def get_recommended_band(dd, is_bull):
    if not is_bull or dd < -20: return 5, "🟥 하락장: 방어 위해 5% 추천"
    elif -20 <= dd < -10: return 7, "🟧 조정장: 7% ~ 10% 추천"
    elif dd >= -10 and is_bull: return 10, "🟩 상승장: 10% ~ 15% 추천"
    return 10, "⬜ 일반: 10% 추천"

# --- [UI 시작] ---
st.title("🇰🇷 ISA 매매 가이드 (KODEX QLD)")

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
            # ISA 시트 읽기 시도
            existing_data = conn.read(worksheet="ISA", usecols=[0, 1, 2, 3], ttl=0).dropna()
            if not existing_data.empty:
                last_row = existing_data.iloc[-1]
                default_qty = int(last_row.iloc[0])
                default_pool = int(last_row.iloc[1])
                default_v = int(last_row.iloc[2])
                default_principal = int(last_row.iloc[3]) if len(last_row) > 3 else 20566879
                st.success(f"☁️ ISA 데이터 로드 완료")
            else: raise Exception("Empty")
        except:
            default_qty, default_pool, default_v, default_principal = 0, 0, 0, 0
            st.warning("⚠️ 신규 시작 또는 데이터 없음 (초기값 0)")

        mode = st.radio("운용 모드", ["최초 시작", "사이클 업데이트"])
        principal = st.number_input("총 투입 원금 (원)", value=int(default_principal), step=10000)
        
        # [수정된 부분] min_value를 1에서 0으로 변경!
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
            new_data = pd.DataFrame([{"Qty": qty, "Pool": pool, "V_old": v_to_save, "Principal": principal}])
            conn.update(worksheet="ISA", data=new_data)
            st.success("✅ 저장 완료!")

    v_l = int(v1 * (1 - band_pct))
    v_u = int(v1 * (1 + band_pct))
    ok, qta, msg, m_type = check_safety(m['dd'], fng_input)
    current_asset = (m['price'] * qty) + pool
    roi_val = current_asset - principal
    roi_pct = (roi_val / principal) * 100 if principal > 0 else 0

    st.subheader(f"📈 QLD 현재가: {m['price']:,}원")
    col1, col2, col3 = st.columns(3)
    col1.metric("총 투입 원금", f"{principal:,.0f}원")
    col2.metric("ISA 총 자산", f"{current_asset:,.0f}원", delta=f"{roi_val:,.0f}원")
    col3.metric("누적 수익률", f"{roi_pct:.2f}%", delta_color="normal")
    st.divider()

    tab1, tab2 = st.tabs(["📊 매매 가이드", "📋 상세 정보"])
    telegram_msg = ""
    with tab1:
        if m_type == "normal": st.success(msg)
        elif m_type == "warning": st.warning(msg)
        else: st.error(msg)
        telegram_msg += f"[ISA QLD 리포트]\n📅 {datetime.now().strftime('%Y-%m-%d')}\n가격: {m['price']:,}원\n상태: {msg}\n수익률: {roi_pct:.2f}% ({roi_val:,.0f}원)\n\n"
        c1, c2, c3 = st.columns(3)
        c1.metric("평가금", f"{m['price']*qty:,.0f}원")
        c2.metric("목표 V", f"{v1:,.0f}원")
        c3.metric("매수선", f"{v_l:,.0f}원")
        st.divider()
        l, r = st.columns(2)
        with l:
            st.markdown("#### 📉 매수 가이드")
            if m['price'] * qty < v_l:
                if ok:
                    st.write(f"쿼터 {qta*100:.0f}%")
                    for i in range(1, 10): 
                        t_q = qty + i
                        p = int(v_l / t_q)
                        if p < m['price'] * 1.05:
                            txt = f"✅ LOC 매수: {p:,}원 ({t_q}주)"
                            st.code(txt)
                            telegram_msg += f"{txt}\n"
                else:
                    st.error("🚫 매수 금지")
                    telegram_msg += "🚫 FnG 경고: 매수 금지\n"
            else:
                st.info("😴 매수 관망")
                telegram_msg += "😴 관망\n"
        with r:
            st.markdown("#### 📈 매도 가이드")
            if m['price'] * qty > v_u:
                for i in range(1, 5):
                    t_q = qty - i
                    if t_q > 0:
                        p = int(v1 / t_q)
                        if p > m['price']:
                            txt = f"🔥 LOC 매도: {p:,}원 ({qty-t_q}주 판매)"
                            st.code(txt)
                            telegram_msg += f"{txt}\n"
            else:
                st.info("😴 매도 관망")
                telegram_msg += "😴 관망\n"
        st.divider()
        if st.button("✈️ 텔레그램 전송"):
            send_telegram_msg(telegram_msg)
    with tab2: st.write("격주 월요일 리밸런싱 권장")
else:
    st.error("📉 데이터 로드 실패 (잠시 후 다시 시도하세요)")
    st.info("💡 팁: 새로고침을 너무 자주 하면 야후 파이낸스에서 일시적으로 차단합니다. 5~10분 뒤에 다시 접속해보세요.")
