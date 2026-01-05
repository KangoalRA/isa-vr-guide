import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime
import requests
from streamlit_gsheets import GSheetsConnection

# --- [0. 페이지 설정] ---
st.set_page_config(page_title="ISA VR 매매 가이드", layout="wide")

# 텔레그램 전송
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

# --- [1. 데이터 수집 (오류 방지)] ---
@st.cache_data(ttl=600)
def get_market_intelligence():
    data = {"price": 0, "dd": 0.0, "fng": 25.0, "bull": True}
    try:
        # Ticker: SOL 미국테크TOP10 레버리지 (409820.KS) 등 변경 가능
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
        print(f"Error: {e}")
        return data

m = get_market_intelligence()

# --- [2. 로직 함수] ---
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

# --- [3. 사이드바] ---
st.title("⚖️ ISA VR 매매 가이드")

with st.sidebar:
    st.header("⚙️ 입력 설정")
    if m['price'] > 0:
        st.metric("현재가", f"{m['price']:,}원")
    else:
        st.error("⚠️ 주가 로딩 실패")

    st.markdown("[👉 FnG Index 확인](https://edition.cnn.com/markets/fear-and-greed)")
    fng_input = st.number_input("FnG Index", value=float(m['fng']))
    
    st.divider()
    band_pct = st.slider("밴드폭 (%)", 5, 25, 15) / 100
    
    st.divider()
    conn = st.connection("gsheets", type=GSheetsConnection)
    try:
        df_history = conn.read(worksheet="ISA", ttl=0).dropna(how='all')
        if not df_history.empty:
            last_row = df_history.iloc[-1]
            d_qty = int(last_row.iloc[0])
            d_pool = int(last_row.iloc[1])
            d_v = int(last_row.iloc[2])
            d_prin = int(last_row.iloc[3])
            d_avg = int(last_row.iloc[4]) if len(last_row) > 4 else 0
            st.success(f"데이터 로드: {len(df_history)}회차")
        else: raise Exception()
    except:
        d_qty, d_pool, d_v, d_prin, d_avg = 0, 0, 0, 20566879, 0
        df_history = pd.DataFrame(columns=["Qty", "Pool", "V_old", "Principal", "AvgPrice", "Date", "FnG", "CurrentPrice"])

    mode = st.radio("모드", ["최초 시작", "사이클 업데이트"])
    principal = st.number_input("총 원금", value=int(d_prin))
    avg_price = st.number_input("내 평단가", value=int(d_avg))
    qty = st.number_input("보유 수량", value=int(d_qty))
    pool = st.number_input("예수금", value=int(d_pool))
    
    if mode == "최초 시작":
        v1 = m['price'] * qty
        v_to_save = v1
    else:
        v_old = st.number_input("직전 V1", value=int(d_v))
        g_val = 10 # G값 고정
        target_roi = (pool / v_old) / g_val if v_old > 0 else 0.0
        v_to_save = int(v_old * (1 + target_roi))
        v1 = v_to_save
        
        add_cash = st.number_input("추가 입금", value=0)
        if add_cash > 0: 
            v1 += add_cash
            principal += add_cash

    if st.button("💾 데이터 저장"):
        # [수정] CurrentPrice 컬럼 추가하여 그래프 정확도 향상
        new_row = pd.DataFrame([{
            "Qty": qty, "Pool": pool, "V_old": v_to_save, 
            "Principal": principal, "AvgPrice": avg_price,
            "Date": datetime.now().strftime('%Y-%m-%d'), 
            "FnG": fng_input, "CurrentPrice": m['price']
        }])
        
        # 컬럼 매칭 처리
        for col in new_row.columns:
            if col not in df_history.columns:
                df_history[col] = 0
                
        updated_df = pd.concat([df_history, new_row], ignore_index=True)
        conn.update(worksheet="ISA", data=updated_df)
        st.cache_data.clear() 
        st.success("저장 완료!")

# --- [4. 메인 대시보드] ---
tab1, tab2, tab3 = st.tabs(["📊 매매 대시보드", "📈 차트 분석", "🛡️ 안전장치"])

with tab1:
    if v1 > 0:
        v_l = int(v1 * (1 - band_pct))
        v_u = int(v1 * (1 + band_pct))
        curr_stock_val = m['price'] * qty
        current_asset = curr_stock_val + pool
        ok, qta, msg, m_type = check_safety(m['dd'], fng_input)
        
        total_roi = (current_asset / principal - 1) * 100 if principal > 0 else 0
        stock_roi = (m['price'] / avg_price - 1) * 100 if avg_price > 0 else 0

        # 현황판
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 자산", f"{current_asset:,.0f}원", f"{total_roi:.2f}%")
        c2.metric("목표 V", f"{v1:,.0f}원")
        c3.metric("주식 수익", f"{stock_roi:.2f}%", f"평단 {avg_price:,}")
        c4.metric("밴드 이탈", f"{(curr_stock_val/v1-1)*100:.1f}%") # 괴리율
        
        st.divider()

        # [안전장치 알림]
        if m_type == "normal": st.success(f"🛡️ {msg}")
        elif m_type == "warning": st.warning(f"🛡️ {msg}")
        else: st.error(f"🛡️ {msg}")

        # [매매 가이드] - 그래프 위로 배치
        l, r = st.columns(2)
        telegram_msg = f"[ISA VR]\n📅 {datetime.now().strftime('%Y-%m-%d')}\n상태: {msg}\n"
        
        with l:
            st.markdown("#### 📉 BUY (매수)")
            if m['price'] > 0:
                if curr_stock_val < v_l:
                    if ok:
                        req_qty = int((v_l - curr_stock_val) / m['price'])
                        cost = req_qty * m['price']
                        st.info(f"✅ **매수 추천: {req_qty}주**")
                        st.write(f"• 필요 금액: {cost:,.0f}원")
                        st.code(f"LOC 예약가: {int(v_l/(qty+1)):,}원")
                        telegram_msg += f"매수: {req_qty}주 ({cost:,.0f}원)\n"
                    else: st.error("🚫 안전장치로 매수 금지")
                else:
                    gap = v_l - curr_stock_val
                    st.write(f"• 현재 평가액: {curr_stock_val:,.0f}원")
                    st.write(f"• 매수 시작선: {v_l:,.0f}원")
                    st.warning(f"👉 **{gap:,.0f}원** 더 하락해야 매수")
            else: st.error("가격 로딩중...")

        with r:
            st.markdown("#### 📈 SELL (매도)")
            if m['price'] > 0:
                if curr_stock_val > v_u:
                    req_qty = int((curr_stock_val - v_u) / m['price'])
                    cash_get = req_qty * m['price']
                    st.info(f"🔥 **매도 추천: {req_qty}주**")
                    st.write(f"• 확보 현금: {cash_get:,.0f}원")
                    st.code(f"LOC 예약가: {int(v1/(qty-1)) if qty>1 else int(m['price']*1.05):,}원")
                    telegram_msg += f"매도: {req_qty}주\n"
                else:
                    gap = v_u - curr_stock_val
                    st.write(f"• 현재 평가액: {curr_stock_val:,.0f}원")
                    st.write(f"• 매도 시작선: {v_u:,.0f}원")
                    st.warning(f"👉 **{gap:,.0f}원** 더 상승해야 매도")
            else: st.error("가격 로딩중...")

        st.divider()

        # [그래프 1: 현재 위치 (확대판)]
        st.subheader("🎯 현재 밴드 위치 (Zoom)")
        pos_fig = go.Figure()
        
        # 밴드 영역 그리기
        pos_fig.add_shape(type="rect", x0=v_l, x1=v_u, y0=-0.5, y1=0.5, fillcolor="rgba(128,128,128,0.3)", line_width=0)
        
        # 선 그리기
        pos_fig.add_vline(x=v_l, line_color="red", annotation_text="매수선", annotation_position="bottom right")
        pos_fig.add_vline(x=v_u, line_color="blue", annotation_text="매도선", annotation_position="top left")
        pos_fig.add_vline(x=v1, line_dash="dash", line_color="gray", annotation_text="목표(V)")
        
        # 내 위치 마커
        color = 'green' if v_l <= curr_stock_val <= v_u else 'red'
        pos_fig.add_trace(go.Scatter(
            x=[curr_stock_val], y=[0], mode='markers+text',
            marker=dict(size=25, symbol='diamond', color=color),
            text=[f"현재: {curr_stock_val:,.0f}"], textposition="bottom center",
            name="내 자산"
        ))

        # [핵심 수정] X축 범위를 밴드 근처로 강제 고정 (0부터 시작 X)
        margin = (v_u - v_l) * 0.5
        pos_fig.update_layout(
            height=200, showlegend=False,
            xaxis=dict(showgrid=True, range=[v_l - margin, v_u + margin], tickformat=","), # 콤마 포맷
            yaxis=dict(showticklabels=False, showgrid=False, range=[-1, 1]),
            margin=dict(l=20, r=20, t=30, b=20)
        )
        st.plotly_chart(pos_fig, use_container_width=True)
        
        if st.button("✈️ 텔레그램 리포트 전송"):
            send_telegram_msg(telegram_msg)

with tab2:
    # [그래프 2: 요청하신 VR 히스토리 차트]
    if not df_history.empty:
        st.subheader("📈 VR 밴드 추적 (History)")
        
        # 데이터 전처리: 히스토리 데이터에서 밴드값 역산
        # (과거 밴드폭은 저장 안했으므로 현재 설정값(band_pct)으로 추정하여 그립니다)
        df_history['V_upper'] = df_history['V_old'] * (1 + band_pct)
        df_history['V_lower'] = df_history['V_old'] * (1 - band_pct)
        
        # 과거 주식 평가액 계산 (저장된 CurrentPrice가 있으면 사용, 없으면 당시 Qty * 현재가로 추정)
        if 'CurrentPrice' in df_history.columns:
            # 0인 값은 현재가로 대체 (데이터 없는 경우 방지)
            df_history['Eval'] = df_history.apply(lambda x: x['Qty'] * x['CurrentPrice'] if x['CurrentPrice'] > 0 else x['Qty'] * m['price'], axis=1)
        else:
            df_history['Eval'] = df_history['Qty'] * m['price']

        hist_fig = go.Figure()
        
        # 1. 매도선 (노란색 상단)
        hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['V_upper'], name="매도선", line=dict(color='yellow', width=2)))
        
        # 2. 매수선 (노란색 하단)
        hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['V_lower'], name="매수선", line=dict(color='yellow', width=2), fill='tonexty', fillcolor='rgba(255,255,0,0.1)'))
        
        # 3. 목표선 (빨간색)
        hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['V_old'], name="목표(V)", line=dict(color='red', width=2)))
        
        # 4. 내 평가액 (파란색 + 마커)
        hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['Eval'], name="주식 평가액", line=dict(color='skyblue', width=3), mode='lines+markers'))

        hist_fig.update_layout(height=500, xaxis_title="날짜", yaxis_title="평가금액 (원)", hovermode="x unified")
        st.plotly_chart(hist_fig, use_container_width=True)
    else:
        st.info("데이터가 저장되면 히스토리 차트가 그려집니다.")

with tab3:
    st.markdown("### 🛡️ 안전장치 가동 기준")
    st.error(f"**현재 낙폭(DD):** {m['dd']}%")
    st.write(f"**공포지수(FnG):** {fng_input}")
    
    st.table(pd.DataFrame({
        "구분": ["정상장", "조정장", "폭락장"],
        "낙폭(DD)": ["-10% 이내", "-10% ~ -20%", "-20% 초과"],
        "필요 FnG": ["상관없음", "20 이하", "15 이하"],
        "매수 강도": ["100%", "50% (반만)", "30% (찔끔)"]
    }))
