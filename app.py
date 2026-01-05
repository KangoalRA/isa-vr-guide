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
        st.error("텔레그램 전송 실패")

# --- [1. 시장 데이터 수집] ---
@st.cache_data(ttl=600)
def get_market_intelligence():
    # 가격 0으로 인한 에러 방지용 기본값
    data = {"price": 0, "dd": 0.0, "fng": 25.0, "bull": True}
    try:
        # Ticker: 409820.KS (SOL 미국테크TOP10 레버리지 예시)
        t_hist = yf.Ticker("409820.KS").history(period="5d")
        if not t_hist.empty: 
            data["price"] = int(t_hist['Close'].iloc[-1])
        
        n_hist = yf.Ticker("^NDX").history(period="2y")
        if not n_hist.empty:
            ndx_high = n_hist['Close'].max()
            curr_ndx = n_hist['Close'].iloc[-1]
            data["dd"] = round((curr_ndx / ndx_high - 1) * 100, 2)
            data["bull"] = curr_ndx > n_hist['Close'].rolling(window=200).mean().iloc[-1]
            
        r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/static/history", headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        if r.status_code == 200: data["fng"] = float(r.json()['fear_and_greed']['score'])
        
        return data
    except Exception as e:
        # 에러 발생 시 로그만 찍고 앱이 멈추지 않게 함
        print(f"Data Fetch Error: {e}")
        return data

m = get_market_intelligence()

# --- [2. 로직 함수 (수정 없음)] ---
def get_recommended_band_ui(dd, is_bull):
    if not is_bull or dd <= -20: return 10, "🟥 폭락장/역배열: 10% 추천", "error"
    elif -20 < dd <= -10: return 15, "🟧 조정장: 15% 추천", "warning"
    else: return 15, "🟩 상승장: 15% 추천", "success"

def check_safety(dd, fng):
    if dd > -10: return True, 1.0, f"🟩 정상장 (DD {dd}%): 100% 가동", "normal"
    elif -20 < dd <= -10:
        return (True, 0.5, f"🟧 조정장: 50% 제한 (FnG {fng})", "warning") if fng <= 20 else (False, 0.0, f"🚫 조정장 대기 (FnG {fng})", "error")
    else:
        return (True, 0.3, f"🚨 폭락장: 30% 제한 (FnG {fng})", "critical") if fng <= 15 else (False, 0.0, f"🚫 하락장 방어 (FnG {fng})", "error")

# --- [3. 사이드바 설정] ---
st.title("⚖️ ISA VR 매매 가이드")

with st.sidebar:
    st.header("⚙️ 시장 지표")
    if m['price'] > 0:
        st.metric("현재가", f"{m['price']:,}원")
    else:
        st.error("⚠️ 현재가 로딩 실패 (0원)")
        
    st.metric("나스닥 낙폭", f"{m['dd']}%")
    st.markdown("[👉 FnG Index (CNN)](https://edition.cnn.com/markets/fear-and-greed)")
    fng_input = st.number_input("FnG Index 입력", value=float(m['fng']))
    
    st.divider()
    _, rec_msg, style = get_recommended_band_ui(m['dd'], m['bull'])
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
            d_qty, d_pool, d_v, d_prin, d_avg = int(last_row.iloc[0]), int(last_row.iloc[1]), int(last_row.iloc[2]), int(last_row.iloc[3]), int(last_row.iloc[4])
            st.success(f"📈 {len(df_history)}회차 데이터 로드됨")
        else: raise Exception()
    except:
        d_qty, d_pool, d_v, d_prin, d_avg = 0, 0, 0, 20566879, 0
        df_history = pd.DataFrame(columns=["Qty", "Pool", "V_old", "Principal", "AvgPrice", "Date", "FnG"])

    mode = st.radio("운용 모드", ["최초 시작", "사이클 업데이트"])
    principal = st.number_input("총 투입 원금", value=int(d_prin))
    avg_price = st.number_input("내 평단가", value=int(d_avg))
    qty = st.number_input("보유 수량", value=int(d_qty), min_value=0)
    pool = st.number_input("Pool (예수금)", value=int(d_pool))
    
    g_val = 10 # G값 고정
    
    if mode == "최초 시작":
        v1 = m['price'] * qty
        v_to_save = v1
    else:
        v_old = st.number_input("직전 V1 (원)", value=int(d_v))
        target_roi = (pool / v_old) / g_val if v_old > 0 else 0.0
        st.caption(f"목표수익률: {target_roi*100:.2f}% (G=10)")
        v_to_save = int(v_old * (1 + target_roi))
        v1 = v_to_save
        
        add_cash = st.number_input("추가 입금액", value=0)
        if add_cash > 0: 
            v1 += add_cash
            principal += add_cash

    if st.button("💾 데이터 저장 (행 추가)"):
        new_row = pd.DataFrame([{
            "Qty": qty, "Pool": pool, "V_old": v_to_save, 
            "Principal": principal, "AvgPrice": avg_price,
            "Date": datetime.now().strftime('%Y-%m-%d'), "FnG": fng_input
        }])
        updated_df = pd.concat([df_history, new_row], ignore_index=True)
        conn.update(worksheet="ISA", data=updated_df)
        st.cache_data.clear() 
        st.success("✅ 데이터 추가 완료!")

# --- [4. 메인 대시보드] ---
tab1, tab2, tab3 = st.tabs(["📊 매매 대시보드", "📋 사용방법", "🛡️ 안전장치 상세"])

with tab1:
    if v1 > 0:
        # 변수 계산
        v_l = int(v1 * (1 - band_pct))
        v_u = int(v1 * (1 + band_pct))
        curr_stock_val = m['price'] * qty
        current_asset = curr_stock_val + pool
        ok, qta, msg, m_type = check_safety(m['dd'], fng_input)
        
        # 수익률 (0으로 나누기 방지)
        total_roi = (current_asset / principal - 1) * 100 if principal > 0 else 0
        stock_roi = (m['price'] / avg_price - 1) * 100 if avg_price > 0 else 0

        # 상단 현황판
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 자산 평가", f"{current_asset:,.0f}원", f"{total_roi:.2f}%")
        c2.metric("목표 가치(V1)", f"{v1:,.0f}원", f"밴드 ±{int(band_pct*100)}%")
        c3.metric("내 주식 수익률", f"{stock_roi:.2f}%", f"평단 {avg_price:,}원")
        c4.metric("V 대비 괴리율", f"{(curr_stock_val/v1-1)*100:.1f}%")
        st.divider()

        # 안전장치 상태 표시
        if m_type == "normal": st.success(f"🛡️ 안전장치: {msg}")
        elif m_type == "warning": st.warning(f"🛡️ 안전장치: {msg}")
        else: st.error(f"🛡️ 안전장치: {msg}")

        # [배치 수정됨: 매매 가이드를 그래프 위로 올림]
        l, r = st.columns(2)
        telegram_msg = f"[ISA VR 리포트]\n📅 {datetime.now().strftime('%Y-%m-%d')}\n상태: {msg}\n총수익: {total_roi:.2f}%\n"
        
        # 매수/매도 로직 (ZeroDivisionError 완벽 수정)
        with l:
            st.markdown("#### 📉 BUY (매수)")
            if curr_stock_val < v_l:
                if ok:
                    # [핵심 수정] 가격이 0이면 계산 스킵
                    if m['price'] > 0:
                        req_qty = int((v_l - curr_stock_val) / m['price'])
                        cost = req_qty * m['price']
                    else:
                        req_qty = 0
                        cost = 0
                    
                    st.info(f"✅ 매수 신호 발생 (강도 {qta*100:.0f}%)")
                    st.write(f"**추천 수량:** {req_qty}주")
                    st.write(f"**필요 금액:** {cost:,.0f}원")
                    
                    loc_price = int(v_l / (qty + 1))
                    txt = f"LOC 예약가: {loc_price:,}원"
                    st.code(txt)
                    telegram_msg += f"매수: {req_qty}주 (약 {cost/10000:.0f}만원)\n{txt}\n"
                else: 
                    st.error("🚫 안전장치 작동: 매수 금지 (현금 보존)")
                    telegram_msg += "안전장치로 매수 금지\n"
            else:
                st.markdown(f"매수선까지 **{v_l - curr_stock_val:,.0f}원** 하락 시 진입")

        with r:
            st.markdown("#### 📈 SELL (매도)")
            if curr_stock_val > v_u:
                # [핵심 수정] 가격이 0이면 계산 스킵
                if m['price'] > 0:
                    req_qty = int((curr_stock_val - v_u) / m['price'])
                    cash_secure = req_qty * m['price']
                else:
                    req_qty = 0
                    cash_secure = 0
                
                st.info("🔥 수익 실현 신호 발생")
                st.write(f"**추천 수량:** {req_qty}주")
                st.write(f"**확보 현금:** {cash_secure:,.0f}원")
                
                loc_price = int(v1 / (qty - 1)) if qty > 1 else int(m['price']*1.05)
                txt = f"LOC 예약가: {loc_price:,}원"
                st.code(txt)
                telegram_msg += f"매도: {req_qty}주\n{txt}\n"
            else:
                st.markdown(f"매도선까지 **{curr_stock_val - v_u:,.0f}원** 상승 시 진입")
        
        st.divider()

        # [배치 수정됨: 그래프를 매매 가이드 아래로 내림]
        st.subheader("🎯 현재 포지션 (밴드 내 위치)")
        pos_fig = go.Figure()
        
        # 1. 밴드 영역
        pos_fig.add_shape(type="rect", x0=v_l, x1=v_u, y0=-1, y1=1, fillcolor="lightgray", opacity=0.3, line_width=0)
        
        # 2. 주요 라인
        pos_fig.add_vline(x=v_l, line_width=2, line_dash="dot", line_color="red", annotation_text="매수선", annotation_position="bottom right")
        pos_fig.add_vline(x=v_u, line_width=2, line_dash="dot", line_color="blue", annotation_text="매도선", annotation_position="top left")
        pos_fig.add_vline(x=v1, line_width=2, line_dash="dash", line_color="gray", annotation_text="목표(V)", annotation_position="top")
        
        # 3. 내 위치
        pos_fig.add_trace(go.Scatter(
            x=[curr_stock_val], y=[0], 
            mode='markers+text', 
            marker=dict(size=20, symbol='diamond', color='green' if v_l < curr_stock_val < v_u else 'red'),
            text=[f"현재: {curr_stock_val:,.0f}"], textposition="bottom center",
            name="현재 평가액"
        ))

        pos_fig.update_layout(
            height=200, 
            xaxis=dict(title="자산 가치 (원)", showgrid=False),
            yaxis=dict(showticklabels=False, range=[-0.5, 0.5], showgrid=False),
            margin=dict(l=20, r=20, t=20, b=20),
            showlegend=False
        )
        st.plotly_chart(pos_fig, use_container_width=True)

        if st.button("✈️ 텔레그램 전송"):
            send_telegram_msg(telegram_msg)

        # 히스토리 그래프
        if not df_history.empty:
            st.subheader("📈 자산 성장 히스토리")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['V_old'], name="목표(V)", line=dict(dash='dash', color='gray')))
            fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['Qty'].astype(float) * m['price'], name="주식평가액", line=dict(color='#00FF00', width=3)))
            if 'FnG' in df_history.columns:
                fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['FnG'], name="FnG(심리)", yaxis="y2", mode="lines", line=dict(color="orange", width=1, dash='dot')))
            
            fig.update_layout(yaxis=dict(title="평가액 (원)"), yaxis2=dict(title="FnG", overlaying="y", side="right", range=[0, 100]), height=400)
            st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.markdown("### 📋 사용 방법")
    st.write("1. **FnG 확인:** 사이드바 링크를 통해 공포지수를 확인하고 입력합니다.")
    st.write("2. **잔고 입력:** 증권사 어플을 보고 수량, 예수금을 정확히 입력합니다.")
    st.write("3. **저장:** '데이터 저장' 버튼을 눌러 시트에 기록을 남깁니다.")
    st.write("4. **주문:** 대시보드에 뜨는 **'추천 수량'** 만큼 LOC 매수/매도 주문을 겁니다.")

with tab3:
    st.markdown("### 🛡️ 안전장치 로직")
    st.write("하락장에서 현금이 마르는 것을 방지하기 위해 아래 규칙을 엄격히 따릅니다.")
    st.error(f"**현재 상태:** 낙폭(DD) {m['dd']}% / 공포지수(FnG) {fng_input}")
    st.info("💡 **핵심:** 지수가 아무리 떨어져도, 사람들이 충분히 공포를 느끼지 않으면(FnG가 높으면) 바닥이 아닙니다.")
