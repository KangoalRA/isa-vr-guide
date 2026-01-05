import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime
import requests
from streamlit_gsheets import GSheetsConnection

# --- [0. 페이지 설정] ---
st.set_page_config(page_title="ISA VR 매매 가이드", layout="wide")

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
        st.error("텔레그램 전송 실패 (secrets 설정을 확인하세요)")

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

# --- [2. 로직 함수: 시장 상태별 UI] ---
def get_recommended_band_ui(dd, is_bull):
    if not is_bull or dd <= -20:
        return 10, "🟥 폭락장/역배열: 자산 방어를 위해 10% 추천", "error"
    elif -20 < dd <= -10:
        return 15, "🟧 조정장: 변동성 활용 15% 추천", "warning"
    else:
        return 15, "🟩 상승/정배열: 적극적 수익실현 15%~20% 추천", "success"

def check_safety(dd, fng):
    if dd > -10: return True, 1.0, f"🟩 정상장 (DD {dd}%): 100% 가동 가능", "normal"
    elif -20 < dd <= -10:
        return (True, 0.5, f"🟧 조정장: 50% 제한 (FnG {fng})", "warning") if fng <= 20 else (False, 0.0, f"🚫 조정장 대기 (FnG {fng})", "error")
    else:
        return (True, 0.3, f"🚨 폭락장: 30% 제한 (FnG {fng})", "critical") if fng <= 15 else (False, 0.0, f"🚫 하락장 방어 (FnG {fng})", "error")

# --- [3. 사이드바 설정] ---
st.title("⚖️ ISA VR 매매 가이드")

with st.sidebar:
    st.header("⚙️ 기본 설정")
    st.metric("현재가 (SOL미국테크)", f"{m['price']:,}원")
    st.metric("나스닥 낙폭", f"{m['dd']}%")
    fng_input = st.number_input("FnG Index (수동입력)", value=float(m['fng']))
    
    st.divider()
    rec_val, rec_msg, style = get_recommended_band_ui(m['dd'], m['bull'])
    if style == "error": st.error(rec_msg)
    elif style == "warning": st.warning(rec_msg)
    else: st.success(rec_msg)
    band_pct = st.slider("밴드폭 설정 (%)", 5, 25, 15) / 100
    
    st.divider()
    st.subheader("💾 자산 데이터 (ISA)")
    conn = st.connection("gsheets", type=GSheetsConnection)
    try:
        df_history = conn.read(worksheet="ISA", ttl=0).dropna(how='all')
        if not df_history.empty:
            last_row = df_history.iloc[-1]
            default_qty = int(last_row.iloc[0])
            default_pool = int(last_row.iloc[1])
            default_v = int(last_row.iloc[2])
            default_principal = int(last_row.iloc[3])
            # 기존 데이터에 평단가가 없다면 0으로 처리 (에러 방지)
            default_avg = int(last_row.iloc[4]) if len(last_row) > 4 else 0
            st.success(f"📈 {len(df_history)}회차 데이터 로드됨")
        else: raise Exception()
    except:
        default_qty, default_pool, default_v, default_principal, default_avg = 0, 0, 0, 20566879, 0
        df_history = pd.DataFrame(columns=["Qty", "Pool", "V_old", "Principal", "AvgPrice", "Date", "FnG"])

    mode = st.radio("운용 모드", ["최초 시작", "사이클 업데이트"])
    
    # [수정] 입력 필드 재배치 (평단가 추가)
    principal = st.number_input("총 투입 원금 (원)", value=int(default_principal), step=10000)
    avg_price = st.number_input("내 평단가 (원)", value=int(default_avg), step=100)
    qty = st.number_input("보유 수량 (주)", value=int(default_qty), min_value=0)
    pool = st.number_input("Pool (예수금)", value=int(default_pool), step=10000)
    
    if mode == "최초 시작":
        # 현재 보유한 주식 가치를 V1 시작점으로 설정
        v1 = m['price'] * qty
        v_to_save = v1
        if v1 == 0: st.warning("보유 수량이 0입니다. 현금으로 시작하려면 수량을 입력하세요.")
    else:
        v_old = st.number_input("직전 V1 (원)", value=int(default_v), step=10000)
        # G값 고정 (사용자 성향 반영: 10)
        g_val = 10 
        if v_old > 0: target_roi = (pool / v_old) / g_val
        else: target_roi = 0.0
        
        st.caption(f"자동 목표수익률: {target_roi*100:.2f}% (G={g_val})")
        
        v_to_save = int(v_old * (1 + target_roi))
        v1 = v_to_save
        add_cash = st.number_input("추가 입금액", value=0, step=10000)
        if add_cash > 0: 
            v1 += add_cash
            principal += add_cash

    if st.button("💾 데이터 저장 (구글시트)"):
        new_row = pd.DataFrame([{
            "Qty": qty, "Pool": pool, "V_old": v_to_save, 
            "Principal": principal, "AvgPrice": avg_price,
            "Date": datetime.now().strftime('%Y-%m-%d'),
            "FnG": fng_input
        }])
        # AvgPrice 컬럼이 없을 경우를 대비해 처리
        if "AvgPrice" not in df_history.columns:
            df_history["AvgPrice"] = 0
            
        updated_df = pd.concat([df_history, new_row], ignore_index=True)
        conn.update(worksheet="ISA", data=updated_df)
        st.cache_data.clear() 
        st.success("저장 완료!")

# --- [4. 메인 대시보드] ---
tab1, tab2, tab3 = st.tabs(["📊 매매 가이드", "📋 사용방법", "🛡️ 안전장치 정보"])

with tab1:
    if v1 > 0:
        # 변수 계산
        v_l, v_u = int(v1 * (1 - band_pct)), int(v1 * (1 + band_pct))
        curr_stock_val = m['price'] * qty
        current_asset = curr_stock_val + pool
        ok, qta, msg, m_type = check_safety(m['dd'], fng_input)
        
        # 수익률 계산
        total_roi = (current_asset / principal - 1) * 100 if principal > 0 else 0
        stock_roi = (m['price'] / avg_price - 1) * 100 if avg_price > 0 else 0
        
        # 수량 계산 (중심값 V1 복귀 기준)
        # 현재 평가액이 V1보다 작으면 매수, 크면 매도
        diff_val = v1 - curr_stock_val
        req_qty = int(abs(diff_val) / m['price']) if m['price'] > 0 else 0

        # 상단 메트릭 (4열 배치)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 자산 평가", f"{current_asset:,.0f}원", f"{total_roi:.2f}%(전체)")
        c2.metric("목표 가치 (V1)", f"{v1:,.0f}원")
        c3.metric("내 주식 수익률", f"{stock_roi:.2f}%", delta_color="normal")
        c4.metric("V 대비 괴리", f"{(curr_stock_val/v1-1)*100:.1f}%")
        st.divider()

        # 안전장치 메시지 표시
        if m_type == "normal": st.success(msg)
        elif m_type == "warning": st.warning(msg)
        else: st.error(msg)

        # 매매 가이드 (수량 포함)
        l, r = st.columns(2)
        telegram_msg = f"[ISA VR 리포트]\n📅 {datetime.now().strftime('%Y-%m-%d')}\n상태: {msg}\n총수익: {total_roi:.2f}% / 주식수익: {stock_roi:.2f}%\n"
        
        with l:
            st.subheader("📉 BUY (매수)")
            if curr_stock_val < v_l:
                if ok:
                    st.info(f"🟢 매수 신호 발생 (강도 {qta*100:.0f}%)")
                    # LOC 단순 가이드
                    loc_price = int(v_l / (qty + 1)) 
                    
                    st.write(f"**필요 수량:** 약 {req_qty}주")
                    st.write(f"**예상 금액:** {req_qty * m['price']:,.0f}원")
                    
                    txt = f"✅ LOC 추천가: {loc_price:,}원 (또는 현재가)"
                    st.code(txt)
                    telegram_msg += f"매수: {req_qty}주 (약 {req_qty*m['price']/10000:.0f}만원)\n{txt}\n"
                else: 
                    st.error("🚫 안전장치 작동: 매수 금지")
                    telegram_msg += "안전장치로 매수 금지\n"
            else:
                st.markdown(f"진입까지 **{v_l - curr_stock_val:,.0f}원** 남음")

        with r:
            st.subheader("📈 SELL (매도)")
            if curr_stock_val > v_u:
                st.info("🔴 수익 실현 신호 발생")
                loc_price = int(v1 / (qty - 1)) if qty > 1 else int(m['price']*1.05)
                
                st.write(f"**매도 수량:** 약 {req_qty}주")
                st.write(f"**확보 현금:** {req_qty * m['price']:,.0f}원")
                
                txt = f"🔥 LOC 추천가: {loc_price:,}원"
                st.code(txt)
                telegram_msg += f"매도: {req_qty}주\n{txt}\n"
            else:
                st.markdown(f"목표까지 **{curr_stock_val - v_u:,.0f}원** 남음")

        st.divider()
        if st.button("✈️ 텔레그램 전송"):
            send_telegram_msg(telegram_msg)

        # 통합 그래프 (히스토리)
        if not df_history.empty:
            st.subheader("📈 자산 성장 & 시장 심리")
            combined_fig = go.Figure()
            # 목표선
            combined_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['V_old'], name="목표(V)", line=dict(color='gray', dash='dash')))
            # 내 자산
            combined_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['Qty'] * m['price'], name="주식 평가액", line=dict(color='#00FF00', width=3)))
            # FnG (보조축)
            if 'FnG' in df_history.columns:
                combined_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['FnG'], name="FnG(심리)", yaxis="y2", mode="lines", line=dict(color="orange", width=1, dash='dot')))
            
            combined_fig.update_layout(
                yaxis=dict(title="평가액 (원)"),
                yaxis2=dict(title="FnG Index", overlaying="y", side="right", range=[0, 100]),
                legend=dict(orientation="h", y=1.1),
                height=500,
                margin=dict(l=10, r=10, t=30, b=10)
            )
            st.plotly_chart(combined_fig, use_container_width=True)
    else:
        st.info("👈 사이드바에서 보유 수량/현금을 입력하고 [저장] 버튼을 눌러주세요.")

with tab2:
    st.markdown("### 📘 사용 가이드")
    st.write("1. **평단가**를 입력하면 '내 주식 수익률'을 별도로 계산해 줍니다.")
    st.write("2. 평단가는 **참고용**이며, VR 밴드 계산(V값)에는 영향을 주지 않습니다.")
    st.write("3. **사이클 업데이트** 시 실제 계좌의 수량과 현금을 정확히 입력하세요.")

with tab3:
    st.info("안전장치: 나스닥 낙폭(DD)과 공포지수(FnG)를 연동하여 하락장 매수를 제어합니다.")
