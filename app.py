import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime
import requests
from bs4 import BeautifulSoup
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
        st.error("텔레그램 전송 실패: secrets 설정을 확인하세요.")

# --- [1. 데이터 수집 (크롤링 백업 추가)] ---
@st.cache_data(ttl=300)
def get_market_intelligence():
    data = {"price": 0, "dd": 0.0, "fng": 25.0, "bull": True}
    ticker = "409820.KS"  # SOL 미국테크TOP10 (필요시 변경)
    
    # 1. 주가 수집 (1차: yfinance, 2차: 네이버금융 크롤링)
    try:
        t_hist = yf.Ticker(ticker).history(period="5d")
        if not t_hist.empty:
            data["price"] = int(t_hist['Close'].iloc[-1])
    except: pass

    # yfinance 실패 시 네이버 금융 크롤링 시도
    if data["price"] == 0:
        try:
            url = f"https://finance.naver.com/item/main.nhn?code={ticker.split('.')[0]}"
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(res.text, 'html.parser')
            no_today = soup.select_one("p.no_today span.blind")
            if no_today:
                data["price"] = int(no_today.text.replace(',', ''))
        except: pass

    # 2. 나스닥 낙폭 (yfinance 의존)
    try:
        n_hist = yf.Ticker("^NDX").history(period="2y")
        if not n_hist.empty:
            ndx_high = n_hist['Close'].max()
            curr_ndx = n_hist['Close'].iloc[-1]
            data["dd"] = round((curr_ndx / ndx_high - 1) * 100, 2)
            data["bull"] = curr_ndx > n_hist['Close'].rolling(window=200).mean().iloc[-1]
    except: pass
            
    # 3. 공포지수
    try:
        r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/static/history", headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        if r.status_code == 200: data["fng"] = float(r.json()['fear_and_greed']['score'])
    except: pass
        
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

# --- [3. 사이드바] ---
st.title("⚖️ ISA VR 매매 가이드")

with st.sidebar:
    st.header("⚙️ 데이터 입력")
    
    # [가격 로딩 실패 시 수동 입력 활성화]
    if m['price'] > 0:
        current_price = m['price']
        st.metric("현재가 (자동)", f"{current_price:,}원")
    else:
        st.error("⚠️ 주가 로딩 실패 (수동 입력)")
        current_price = st.number_input("현재가 직접 입력", value=10000, step=100)

    st.markdown("[👉 FnG Index 확인](https://edition.cnn.com/markets/fear-and-greed)")
    fng_input = st.number_input("FnG Index", value=float(m['fng']))
    
    st.divider()
    band_pct = st.slider("밴드폭 설정 (%)", 5, 25, 15) / 100
    
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
    
    g_val = 10 
    
    if mode == "최초 시작":
        v1 = current_price * qty
        v_to_save = v1
    else:
        v_old = st.number_input("직전 V1", value=int(d_v))
        if v_old > 0: target_roi = (pool / v_old) / g_val 
        else: target_roi = 0.0
        v_to_save = int(v_old * (1 + target_roi))
        v1 = v_to_save
        
        add_cash = st.number_input("추가 입금", value=0)
        if add_cash > 0: 
            v1 += add_cash
            principal += add_cash

    if st.button("💾 데이터 저장"):
        new_row = pd.DataFrame([{
            "Qty": qty, "Pool": pool, "V_old": v_to_save, 
            "Principal": principal, "AvgPrice": avg_price,
            "Date": datetime.now().strftime('%Y-%m-%d'), 
            "FnG": fng_input, "CurrentPrice": current_price
        }])
        
        for col in new_row.columns:
            if col not in df_history.columns:
                df_history[col] = 0
                
        updated_df = pd.concat([df_history, new_row], ignore_index=True)
        conn.update(worksheet="ISA", data=updated_df)
        st.cache_data.clear() 
        st.success("✅ 저장 완료!")

# --- [4. 메인 대시보드] ---
tab1, tab2, tab3 = st.tabs(["📊 통합 대시보드", "📋 사용방법", "🛡️ 안전장치"])

with tab1:
    if v1 > 0 and current_price > 0:
        v_l = int(v1 * (1 - band_pct))
        v_u = int(v1 * (1 + band_pct))
        curr_stock_val = current_price * qty
        current_asset = curr_stock_val + pool
        ok, qta, msg, m_type = check_safety(m['dd'], fng_input)
        
        total_roi = (current_asset / principal - 1) * 100 if principal > 0 else 0
        stock_roi = (current_price / avg_price - 1) * 100 if avg_price > 0 else 0

        # 현황판
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 자산", f"{current_asset:,.0f}원", f"{total_roi:.2f}%")
        c2.metric("목표 V", f"{v1:,.0f}원")
        c3.metric("주식 수익", f"{stock_roi:.2f}%", f"평단 {avg_price:,}")
        c4.metric("밴드 이탈", f"{(curr_stock_val/v1-1)*100:.1f}%")
        
        st.divider()

        # 안전장치 알림
        if m_type == "normal": st.success(f"🛡️ {msg}")
        elif m_type == "warning": st.warning(f"🛡️ {msg}")
        else: st.error(f"🛡️ {msg}")

        # 매매 가이드
        l, r = st.columns(2)
        telegram_msg = f"[ISA VR]\n📅 {datetime.now().strftime('%Y-%m-%d')}\n상태: {msg}\n"
        
        with l:
            st.markdown("#### 📉 BUY (매수)")
            if curr_stock_val < v_l:
                if ok:
                    req_qty = int((v_l - curr_stock_val) / current_price)
                    cost = req_qty * current_price
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

        with r:
            st.markdown("#### 📈 SELL (매도)")
            if curr_stock_val > v_u:
                req_qty = int((curr_stock_val - v_u) / current_price)
                cash_get = req_qty * current_price
                st.info(f"🔥 **매도 추천: {req_qty}주**")
                st.write(f"• 확보 현금: {cash_get:,.0f}원")
                st.code(f"LOC 예약가: {int(v1/(qty-1)) if qty>1 else int(current_price*1.05):,}원")
                telegram_msg += f"매도: {req_qty}주\n"
            else:
                gap = v_u - curr_stock_val
                st.write(f"• 현재 평가액: {curr_stock_val:,.0f}원")
                st.write(f"• 매도 시작선: {v_u:,.0f}원")
                st.warning(f"👉 **{gap:,.0f}원** 더 상승해야 매도")

        st.divider()

        # [그래프 수정 완료] Y축을 가격으로, 가로선으로 밴드 표시
        st.subheader("🎯 현재 포지션 (밴드 내 위치)")
        pos_fig = go.Figure()

        # 1. 밴드 영역 (배경)
        pos_fig.add_hrect(y0=v_l, y1=v_u, fillcolor="gray", opacity=0.1, line_width=0)
        
        # 2. 기준선 (가로선)
        pos_fig.add_hline(y=v_u, line_dash="dot", line_color="blue", annotation_text="매도선", annotation_position="top left")
        pos_fig.add_hline(y=v_l, line_dash="dot", line_color="red", annotation_text="매수선", annotation_position="bottom left")
        pos_fig.add_hline(y=v1, line_dash="dash", line_color="black", annotation_text="목표(V)")

        # 3. 내 위치 (마커)
        color = 'green' if v_l <= curr_stock_val <= v_u else 'red'
        pos_fig.add_trace(go.Scatter(
            x=["내 자산"], y=[curr_stock_val], 
            mode='markers+text',
            marker=dict(size=30, symbol='diamond', color=color),
            text=[f"{curr_stock_val:,.0f}원"], textposition="middle right",
            name="현재 평가액"
        ))

        # 4. Y축 범위 설정 (밴드 구간 확대)
        margin = (v_u - v_l) * 0.5
        pos_fig.update_layout(
            height=400,
            yaxis=dict(title="자산 가치 (원)", range=[v_l - margin, v_u + margin], tickformat=","),
            xaxis=dict(showticklabels=False), # X축 라벨 숨김
            showlegend=False,
            margin=dict(l=50, r=50, t=30, b=30)
        )
        st.plotly_chart(pos_fig, use_container_width=True)

        # 5. 시계열 히스토리
        if not df_history.empty:
            st.subheader("📈 자산 성장 히스토리")
            
            df_history['V_upper'] = df_history['V_old'] * (1 + band_pct)
            df_history['V_lower'] = df_history['V_old'] * (1 - band_pct)
            df_history['Eval'] = df_history.apply(
                lambda x: x['Qty'] * x['CurrentPrice'] if 'CurrentPrice' in df_history.columns and x['CurrentPrice'] > 0 else x['Qty'] * current_price, 
                axis=1
            )

            hist_fig = go.Figure()
            hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['V_upper'], name="매도선", line=dict(color='yellow', width=1)))
            hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['V_lower'], name="매수선", line=dict(color='yellow', width=1), fill='tonexty', fillcolor='rgba(255,255,0,0.1)'))
            hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['V_old'], name="목표(V)", line=dict(color='red', width=2)))
            hist_fig.add_trace(go.Scatter(x=df_history['Date'], y=df_history['Eval'], name="평가액", line=dict(color='skyblue', width=3), mode='lines+markers'))

            hist_fig.update_layout(height=400, xaxis_title="날짜", yaxis_title="금액", hovermode="x unified")
            st.plotly_chart(hist_fig, use_container_width=True)

        if st.button("✈️ 텔레그램 리포트 전송"):
            send_telegram_msg(telegram_msg)
            
    else:
        st.warning("👈 사이드바에서 정보를 입력해주세요.")

with tab2:
    st.markdown("### 📘 ISA VR 실전 사용 매뉴얼")
    st.success("#### 🟢 상승장 (매도 타임)\n- 평가액이 파란색 **매도선**을 넘으면 수익 실현 타이밍입니다.\n- 가이드 가격으로 매도 주문을 넣고, 판 돈은 **Pool(현금)**에 보관하세요. 💰")
    st.warning("#### 🟡 횡보장 (관망 타임)\n- 주가가 밴드 안에서 움직이면 아무것도 하지 않는 것이 핵심입니다.\n- 매회차 V값을 조금씩 늘려가며 자산의 기초 체력을 키웁니다. ☕")
    st.error("#### 🔴 하락장 (매수 타임)\n- 평가액이 빨간색 **매수선** 아래로 떨어지면 줍줍 타이밍입니다.\n- 단, **안전장치(탭3)**가 허락할 때만 현금을 투입하여 생존을 우선합니다. 📉")
    st.divider()
    st.write("**📝 매매 운영 루틴**\n1. 격주 월요일 오후 3시: 수량과 현금을 정확히 입력\n2. 저장: '사이클 업데이트' 모드로 기록 저장\n3. 주문: LOC 예약 주문 실행")

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
