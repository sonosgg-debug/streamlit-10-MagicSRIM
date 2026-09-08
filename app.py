"""
app.py
Magic S-RIM 가치평가 및 미래 ROE 예측 웹 대시보드
Streamlit 기반 인터랙티브 분석 플랫폼 (다크 모드 최적화 & 32 FinancialChart 종목 선택 방식 탑재)
"""

import os
from datetime import datetime, date
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px

# 코어 모듈 임포트
from fnguide_scraper import scrape_company_data, get_krx_ticker_list
from srim_engine import (
    calculate_required_return,
    extract_roe_candidates,
    get_base_equity_data,
    calculate_srim_standard,
    calculate_srim_multiperiod,
    generate_sensitivity_matrix
)
from excel_exporter import generate_srim_excel

# 페이지 설정
st.set_page_config(
    page_title="Magic S-RIM 가치평가 대시보드",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 다크 모드 완벽 호환 세련된 금융 스타일 CSS
st.markdown("""
<style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    html, body, [class*="css"] {
        font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, Roboto, sans-serif;
    }
    .main-title {
        font-size: 2.2rem;
        font-weight: 800;
        color: #38BDF8;
        margin-bottom: 0.2rem;
        letter-spacing: -0.5px;
    }
    .sub-title {
        font-size: 0.95rem;
        color: #94A3B8;
        margin-bottom: 1.5rem;
    }
    /* 그레이 톤 메트릭 카드 (다크 모드 최적화) */
    .metric-card {
        background-color: #1E293B;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 1.2rem 1rem;
        text-align: center;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.25), 0 2px 4px -2px rgba(0, 0, 0, 0.2);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 12px -1px rgba(0, 0, 0, 0.35);
    }
    .card-title {
        font-size: 0.88rem;
        font-weight: 600;
        color: #94A3B8;
        letter-spacing: 0.3px;
    }
    .card-value {
        font-size: 1.8rem;
        font-weight: 800;
        margin-top: 0.4rem;
        margin-bottom: 0.2rem;
    }
    .card-sub {
        font-size: 0.9rem;
        color: #E2E8F0;
        margin-top: 0.3rem;
    }
    .card-desc {
        font-size: 0.78rem;
        color: #94A3B8;
        margin-top: 0.4rem;
        line-height: 1.35;
    }
    /* 밝고 화사한 강조 색상 */
    .buy-color { color: #34D399 !important; }   /* 산뜻한 에메랄드 그린 */
    .fair-color { color: #FBBF24 !important; }  /* 화사한 웜 골드/앰버 */
    .sell-color { color: #F87171 !important; }  /* 밝은 코랄 레드 */
    .blue-color { color: #38BDF8 !important; }  /* 일렉트릭 스카이블루 */
    
    /* 기업 시세 및 가치평가 요약 st.metric 숫자 폰트 크기 대폭 축소 및 다크 카드화 */
    [data-testid="stMetricValue"], [data-testid="stMetricValue"] * {
        font-size: 1.1rem !important;
        font-weight: 700 !important;
        white-space: nowrap !important;
        overflow: visible !important;
    }
    [data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * {
        font-size: 0.82rem !important;
        color: #94A3B8 !important;
    }
    [data-testid="stMetricDelta"], [data-testid="stMetricDelta"] * {
        font-size: 0.75rem !important;
    }
    div[data-testid="stMetric"] {
        background-color: #1E293B;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 10px 12px;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
        border-radius: 6px;
    }
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------
# 1. 종목 리스트 로드 (32 FinancialChart / 35 ShortSelling 방식)
# -------------------------------------------------------------
@st.cache_data(ttl=86400)
def load_stock_tickers():
    """상장 종목 전체 리스트 가져오기 (pykrx StockTicker 및 FDR, fnguide_scraper 로컬 캐시 폴백)"""
    try:
        from pykrx.website.krx.market.ticker import StockTicker
        st_ticker = StockTicker()
        df = st_ticker.listed
        if not df.empty and '종목' in df.columns:
            return df
    except Exception:
        pass
    
    try:
        import FinanceDataReader as fdr
        df = fdr.StockListing('KRX')
        df = df.set_index('Code')
        df['종목'] = df['Name']
        return df
    except Exception:
        pass

    try:
        tickers = get_krx_ticker_list()
        if tickers:
            df = pd.DataFrame(list(tickers.items()), columns=['Code', '종목']).set_index('Code')
            return df
    except Exception:
        pass
        
    return pd.DataFrame()

# -------------------------------------------------------------
# 세션 상태 초기화
# -------------------------------------------------------------
if 'selected_ticker' not in st.session_state:
    st.session_state.selected_ticker = "005930"  # 기본값: 삼성전자
if 'scraped_data' not in st.session_state:
    st.session_state.scraped_data = None

# -------------------------------------------------------------
# 사이드바 (컨트롤 패널 - 32 FinancialChart 방식 종목 선택)
# -------------------------------------------------------------
with st.sidebar:
    st.subheader("🔍 종목 선택")

    tickers_df = load_stock_tickers()
    if not tickers_df.empty:
        tickers_df['display_name'] = tickers_df['종목'] + " (" + tickers_df.index + ")"
        default_index = 0
        if st.session_state.selected_ticker in tickers_df.index:
            default_index = int(tickers_df.index.get_loc(st.session_state.selected_ticker))

        with st.form(key="stock_search_form"):
            selected_display = st.selectbox(
                "종목명(코드) 검색 / 선택",
                options=tickers_df['display_name'].tolist(),
                index=default_index,
                help="키보드로 종목명(예: 삼성전자) 또는 종목코드(예: 005930)를 입력하여 검색 및 선택할 수 있습니다."
            )
            submitted = st.form_submit_button("조회", use_container_width=True, type="primary")

            if submitted and selected_display:
                code_from_display = selected_display.split("(")[-1].replace(")", "").strip()
                if st.session_state.selected_ticker != code_from_display:
                    st.session_state.selected_ticker = code_from_display
                    st.session_state.scraped_data = None
                    st.rerun()

    # 빠른 대표 종목 바로가기 버튼
    st.markdown("<small style='color:#94A3B8;'>주요 대표 종목 바로가기</small>", unsafe_allow_html=True)
    quick_cols = st.columns(3)
    quick_picks = [
        ("삼성전자", "005930"),
        ("SK하이닉스", "000660"),
        ("SK스퀘어", "402340"),
        ("삼성전기", "009150"),
        ("LG에너지솔루션", "373220"),
        ("현대차", "005380")
    ]
    for idx, (q_name, q_code) in enumerate(quick_picks):
        with quick_cols[idx % 3]:
            if st.button(q_name, key=f"quick_{q_code}", use_container_width=True):
                st.session_state.selected_ticker = q_code
                st.session_state.scraped_data = None
                st.rerun()

    st.markdown("---")
    st.markdown("### ⚙️ 가치평가 파라미터 설정")

    # 1. 요구수익률 (할인율) 설정
    with st.expander("📌 요구수익률(할인율) 산정 방식", expanded=True):
        req_mode = st.radio(
            "산정 모델 선택",
            options=["bond", "capm", "fixed"],
            format_func=lambda x: {
                "bond": "한국신용평가 BBB- 회사채 (사경인 표준)",
                "capm": "CAPM 모델 (Rf + Beta × ERP)",
                "fixed": "사용자 직접 지정 고정값"
            }[x],
            index=0
        )
        
        if req_mode == "bond":
            bond_rate = st.number_input(
                "BBB- 5년 만기 회사채 수익률 (%)",
                min_value=4.0, max_value=25.0, value=9.5, step=0.1,
                help="사경인 회계사가 S-RIM의 기본 할인율로 추천하는 지표입니다."
            ) / 100.0
            req_return = bond_rate
        elif req_mode == "capm":
            col_rf, col_erp = st.columns(2)
            with col_rf:
                rf_val = st.number_input("무위험수익률(Rf, %)", min_value=1.0, max_value=10.0, value=3.5, step=0.1) / 100.0
            with col_erp:
                erp_val = st.number_input("시장위험프리미엄(ERP, %)", min_value=2.0, max_value=15.0, value=6.5, step=0.1) / 100.0
            st.caption("※ 종목 고유의 52주 베타(β)가 자동으로 적용됩니다.")
            req_return = None
        else:
            fixed_val = st.number_input(
                "별도 요구수익률 (%)",
                min_value=5.0, max_value=30.0, value=12.5, step=0.5,
                help="투자자가 목표로 하는 최소 요구수익률(Hurdle Rate)입니다."
            ) / 100.0
            req_return = fixed_val

    # 2. 계산 모델 선택
    with st.expander("⚖️ 가치평가 모델 엔진 선택", expanded=True):
        model_engine = st.radio(
            "평가 공식 선택",
            options=["standard", "multiperiod", "compare"],
            format_func=lambda x: {
                "standard": "사경인 정통 S-RIM (표준 모델)",
                "multiperiod": "향후 10년 예측 적용 (응용 모델)",
                "compare": "두 모델 동시 비교 (Dual Comparison)"
            }[x],
            index=0,
            help="사경인 표준 모델은 최신 자본총계 기반 공식이며, 10년 모델은 장기 예측 시뮬레이션 방식입니다."
        )

# -------------------------------------------------------------
# 데이터 스크래핑 및 로딩 처리
# -------------------------------------------------------------
active_ticker = st.session_state.selected_ticker
if (st.session_state.scraped_data is None) or (st.session_state.scraped_data.get('ticker') != active_ticker):
    with st.spinner("fnGuide에서 최신 재무 및 시세 데이터를 불러오는 중..."):
        try:
            data = scrape_company_data(active_ticker)
            st.session_state.scraped_data = data
        except Exception as e:
            st.error(f"데이터 스크래핑 중 오류 발생: {e}")
            st.stop()

data = st.session_state.scraped_data
if not data:
    st.stop()

# -------------------------------------------------------------
# ROE 추정 모드 선택 (사이드바 연동)
# -------------------------------------------------------------
highlights_ann = data.get('highlights_annual')
highlights_qtr = data.get('highlights_quarter')
roe_candidates = extract_roe_candidates(highlights_ann, highlights_qtr)

with st.sidebar:
    with st.expander("🎯 미래 ROE 추정 모드", expanded=True):
        # 전문가 권장 순위대로 옵션 정렬
        pref_order = ['cons_avg', 'cons_1y', 'cons_terminal', 'weighted_hist', 'ltm_qtr']
        ordered_keys = [k for k in pref_order if k in roe_candidates]
        for k in roe_candidates:
            if k not in ordered_keys:
                ordered_keys.append(k)
        roe_options = ordered_keys + ["custom"]
        
        def format_roe_opt(k):
            if k == "custom":
                return "✏️ [직접설정] 사용자 직접 입력 (%)"
            cand = roe_candidates.get(k, {})
            name = cand.get('name', '')
            val = cand.get('value', 0) * 100
            prefix = ""
            if k == "cons_avg":
                prefix = "⭐ [1순위 권장] "
            elif k == "cons_1y":
                prefix = "🥈 [2순위] "
            elif k == "cons_terminal":
                prefix = "🥉 [3순위] "
            elif k == "weighted_hist":
                prefix = "🛡️ [4순위/컨센부재시 1순위] "
            elif k == "ltm_qtr":
                prefix = "⚡ [5순위/최신실적] "
            return f"{prefix}{name} ({val:.2f}%)"

        default_roe_idx = 0
        if "cons_avg" in roe_options:
            default_roe_idx = roe_options.index("cons_avg")
        elif "weighted_hist" in roe_options:
            default_roe_idx = roe_options.index("weighted_hist")
        elif "cons_1y" in roe_options:
            default_roe_idx = roe_options.index("cons_1y")

        selected_roe_key = st.selectbox(
            "적용할 ROE 기준",
            options=roe_options,
            format_func=format_roe_opt,
            index=default_roe_idx
        )

        if selected_roe_key == "custom":
            applied_roe = st.number_input(
                "직접 입력할 미래 ROE (%)",
                min_value=-50.0, max_value=100.0, value=15.0, step=0.5
            ) / 100.0
            roe_desc = "사용자 지정 ROE"
        else:
            applied_roe = roe_candidates[selected_roe_key]['value']
            roe_desc = roe_candidates[selected_roe_key]['name']

# 요구수익률 최종 확정
info = data.get('info', {})
beta_val = info.get('beta') or 1.0
if req_mode == "capm":
    final_req_return = rf_val + beta_val * erp_val
    req_desc = f"CAPM (Rf {rf_val*100:.1f}% + β {beta_val:.2f} × ERP {erp_val*100:.1f}%)"
elif req_mode == "bond":
    final_req_return = bond_rate
    req_desc = f"한국신용평가 BBB- 회사채 ({bond_rate*100:.1f}%)"
else:
    final_req_return = fixed_val
    req_desc = f"별도 고정 요구수익률 ({fixed_val*100:.1f}%)"

# 기초 자본총계 및 유효주식수 추출
base_equity_val, base_date_str = get_base_equity_data(highlights_ann, highlights_qtr)
net_shares = info.get('shares_net') or 1
current_price = info.get('current_price') or 0

# -------------------------------------------------------------
# S-RIM 평가 실행
# -------------------------------------------------------------
std_eval = calculate_srim_standard(base_equity_val, net_shares, applied_roe, final_req_return)
multi_eval = calculate_srim_multiperiod(base_equity_val, net_shares, applied_roe, final_req_return, base_date_str)

# -------------------------------------------------------------
# 메인 대시보드 화면 구성
# -------------------------------------------------------------

# 0. 최상단 메인 대시보드 제목 (가로 가운데 정렬, #8AB4F8 컬러)
st.markdown("<h1 style='text-align: center; color: #8AB4F8; font-size: 2.2rem; font-weight: 800; margin-top: -10px; margin-bottom: 8px; letter-spacing: -0.5px;'>Magic S-RIM 가치 평가 모델</h1>", unsafe_allow_html=True)
st.markdown("<div style='text-align: center; color: #94A3B8; font-size: 0.95rem; margin-bottom: 6px;'>fnGuide 실시간 재무 데이터 기반 적정주가 산출 및 미래 ROE 예측 대시보드</div>", unsafe_allow_html=True)
st.markdown("<div style='text-align: center; color: #64748B; font-size: 0.82rem; margin-bottom: 22px;'>이 평가 모델은 사경인 회계사가 제공한 엑셀 파일을 토대로 인공지능(AI)의 도움으로 설계했습니다.</div>", unsafe_allow_html=True)
st.markdown("<hr style='border: 0; height: 1px; background-color: #334155; margin-bottom: 22px;'>", unsafe_allow_html=True)

# 1. 헤더 영역
col_header_title, col_header_btn = st.columns([3, 1])
with col_header_title:
    st.markdown(f"<div class='main-title'>{data.get('company_name')} <span style='font-size:1.35rem; color:#94A3B8;'>({data.get('ticker')})</span></div>", unsafe_allow_html=True)
    consol_tag = "연결재무제표" if data.get('is_consolidated') else "별도재무제표"
    st.markdown(f"<div class='sub-title'>조회일: {data.get('inquiry_date')} | 기준자본: <b>{base_equity_val:,.0f} 억원</b> ({base_date_str} 기준) | 재무제표: <b>{consol_tag}</b></div>", unsafe_allow_html=True)

with col_header_btn:
    try:
        excel_bytes = generate_srim_excel(data, form_path="000_Form.xlsx")
        filename = f"{data.get('ticker')}_SRIM_{datetime.now().strftime('%Y%m%d')}.xlsx"
        st.download_button(
            label="📥 엑셀 파일 다운로드 (.xlsx)",
            data=excel_bytes,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            type="secondary"
        )
    except Exception as e:
        st.caption(f"엑셀 생성 대기 중: {e}")

# 2. 기업 시세 & 밸류에이션 요약 카드
st.markdown("#### 📌 기업 시세 및 가치평가 요약")
m_cols = st.columns(6)
with m_cols[0]:
    p_change_str = info.get('price_change', '')
    p_rate_str = info.get('price_change_rate', '')
    delta_display = f"{p_change_str} ({p_rate_str})" if p_change_str else None
    st.metric("현재주가", f"{current_price:,} 원", delta=delta_display)

with m_cols[1]:
    mkt_cap = info.get('market_cap_common') or info.get('market_cap_total') or 0
    st.metric("시가총액", f"{mkt_cap:,.0f} 억원")

with m_cols[2]:
    st.metric("추정 ROE", f"{applied_roe*100:.2f}%", help=roe_desc)

with m_cols[3]:
    st.metric("요구수익률 (r)", f"{final_req_return*100:.2f}%", help=req_desc)

with m_cols[4]:
    per_val = info.get('per')
    st.metric("PER / 12M PER", f"{per_val if per_val else '-'} / {info.get('fwd_per') or '-'}")

with m_cols[5]:
    pbr_val = info.get('pbr')
    st.metric("PBR / 베타(β)", f"{pbr_val if pbr_val else '-'} / {beta_val:.2f}")

st.markdown("<br>", unsafe_allow_html=True)

# 3. 핵심 적정주가 결과 섹션 (그레이 톤 다크 모드 카드)
chosen_eval = std_eval if model_engine == "standard" else multi_eval
engine_label = "사경인 정통 S-RIM (표준 모델)" if model_engine == "standard" else "향후 10년 예측 적용 (응용 모델)"

st.markdown(f"### 🎯 S-RIM 적정주가 평가 결과 <span style='font-size:1rem; color:#94A3B8;'>[{engine_label}]</span>", unsafe_allow_html=True)

if chosen_eval['is_aligned']:
    st.success("🟢 **정배열 상태 (ROE > 요구수익률)**: 기업이 주주 요구수익률 이상의 초과이익(Excess Earnings)을 창출하고 있어 주당 가치가 지속 성장합니다.")
else:
    st.warning("🟠 **역배열 상태 (ROE < 요구수익률)**: 기업의 ROE가 주주 요구수익률(자본비용)에 미달하여 시간이 지날수록 기업가치가 훼손될 수 있으므로 보수적 접근이 필요합니다.")

card_cols = st.columns(3)

# 매수 권장가
buy_price = chosen_eval['target_buy']
buy_diff = ((buy_price - current_price) / current_price) * 100 if current_price > 0 else 0
with card_cols[0]:
    st.markdown(f"""
    <div class='metric-card' style='border-top: 5px solid #34D399;'>
        <div class='card-title'>🟢 매수 권장가 (초과이익 20% 감소)</div>
        <div class='card-value buy-color'>{buy_price:,} 원</div>
        <div class='card-sub'>현재가 대비 안전마진: <b>{buy_diff:+.1f}%</b></div>
        <div class='card-desc'>초과이익이 매년 20%씩 급격히 감소해도 담보되는 보수적 매수 구간</div>
    </div>
    """, unsafe_allow_html=True)

# 기준 적정주가
fair_price = chosen_eval['target_fair']
fair_diff = ((fair_price - current_price) / current_price) * 100 if current_price > 0 else 0
with card_cols[1]:
    st.markdown(f"""
    <div class='metric-card' style='border-top: 5px solid #FBBF24;'>
        <div class='card-title'>🟡 기준 적정주가 (초과이익 10% 감소)</div>
        <div class='card-value fair-color'>{fair_price:,} 원</div>
        <div class='card-sub'>현재가 대비 괴리율: <b>{fair_diff:+.1f}%</b></div>
        <div class='card-desc'>경쟁 심화로 초과이익이 연 10%씩 완만하게 감소할 때의 기준 가치</div>
    </div>
    """, unsafe_allow_html=True)

# 매도 목표가
sell_price = chosen_eval['target_sell']
sell_diff = ((sell_price - current_price) / current_price) * 100 if current_price > 0 else 0
with card_cols[2]:
    st.markdown(f"""
    <div class='metric-card' style='border-top: 5px solid #F87171;'>
        <div class='card-title'>🔴 매도 목표가 (초과이익 지속)</div>
        <div class='card-value sell-color'>{sell_price:,} 원</div>
        <div class='card-sub'>현재가 대비 목표 수익률: <b>{sell_diff:+.1f}%</b></div>
        <div class='card-desc'>강력한 해자(Moat)로 초과이익이 영구히 유지될 때의 낙관적 상한가</div>
    </div>
    """, unsafe_allow_html=True)

# 듀얼 비교 모드일 경우 비교 테이블 노출
if model_engine == "compare":
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("##### ⚖️ 두 모델(표준 모델 vs 응용 모델) 비교 표")
    cmp_df = pd.DataFrame({
        "구분": ["매수 권장가 (20% 감소)", "기준 적정가 (10% 감소)", "매도 목표가 (지속)"],
        "사경인 정통 S-RIM (표준 모델)": [f"{std_eval['target_buy']:,} 원", f"{std_eval['target_fair']:,} 원", f"{std_eval['target_sell']:,} 원"],
        "향후 10년 예측 적용 (응용 모델)": [f"{multi_eval['target_buy']:,} 원", f"{multi_eval['target_fair']:,} 원", f"{multi_eval['target_sell']:,} 원"],
        "차이율 (응용/표준)": [
            f"{(multi_eval['target_buy']/std_eval['target_buy'] - 1)*100:+.1f}%" if std_eval['target_buy']>0 else "-",
            f"{(multi_eval['target_fair']/std_eval['target_fair'] - 1)*100:+.1f}%" if std_eval['target_fair']>0 else "-",
            f"{(multi_eval['target_sell']/std_eval['target_sell'] - 1)*100:+.1f}%" if std_eval['target_sell']>0 else "-"
        ]
    })
    st.dataframe(cmp_df, use_container_width=True, hide_index=True)

# -------------------------------------------------------------
# 4. 시각화 섹션 (밝고 화사한 Plotly 인터랙티브 차트)
# -------------------------------------------------------------
st.markdown("<br>", unsafe_allow_html=True)
st.markdown("#### 📊 주가 밴드 및 가치평가 비교 차트")

chart_cols = st.columns([1, 1])

with chart_cols[0]:
    # 밝고 화사한 아치형 게이지 차트 (상단 2줄 제목 여유 확보 및 우측 차트와 대칭 크기 유지)
    max_range = max(current_price, sell_price, fair_price, buy_price, 1) * 1.25
    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=current_price,
        domain={'x': [0.02, 0.98], 'y': [0.0, 0.92]},
        number={'suffix': " 원", 'font': {'size': 26, 'color': '#FFFFFF'}, 'valueformat': ',d'},
        delta={
            'reference': fair_price,
            'increasing': {'color': "#F87171"},
            'decreasing': {'color': "#34D399"},
            'valueformat': ',d',
            'prefix': "적정가 대비: "
        },
        gauge={
            'axis': {'range': [0, max_range], 'tickformat': ',d', 'tickcolor': '#94A3B8', 'tickfont': {'color': '#94A3B8', 'size': 11}},
            'bar': {'color': "#38BDF8", 'thickness': 0.28}, # 산뜻한 일렉트릭 스카이블루 바
            'bgcolor': "rgba(255, 255, 255, 0.08)",
            'borderwidth': 1,
            'bordercolor': "#334155",
            'steps': [
                {'range': [0, buy_price], 'color': "rgba(52, 211, 153, 0.75)"},          # 밝고 산뜻한 민트 에메랄드
                {'range': [buy_price, fair_price], 'color': "rgba(251, 191, 36, 0.75)"},     # 밝고 산뜻한 웜 골드/옐로우
                {'range': [fair_price, sell_price], 'color': "rgba(251, 146, 60, 0.75)"},    # 밝고 화사한 오렌지
                {'range': [sell_price, max_range], 'color': "rgba(244, 63, 94, 0.85)"}       # 밝은 비비드 로즈 레드
            ],
            'threshold': {
                'line': {'color': "#FFFFFF", 'width': 4}, # 선명한 화이트 마커
                'thickness': 0.85,
                'value': current_price
            }
        }
    ))
    fig_gauge.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font={'color': '#F8FAFC'},
        title=dict(
            text="<b>현재주가 위치 vs S-RIM 밸류에이션 밴드</b><br><span style='font-size:0.82em; color:#94A3B8;'>🟢 매수권장가 | 🟡 기준적정가 | 🔴 매도목표가</span>",
            font=dict(color='#F8FAFC', size=15),
            x=0.5,
            xanchor='center',
            y=0.90
        ),
        height=410,
        margin=dict(l=20, r=20, t=75, b=25)
    )
    st.plotly_chart(fig_gauge, use_container_width=True)

with chart_cols[1]:
    # 증권사 컨센서스 vs S-RIM 비교 차트 (선명한 색상 테마, 좌측 차트와 동일 규격 및 여백 대칭 일치)
    cons_info = data.get('consensus_info', {})
    cons_avg = cons_info.get('target_price_avg')
    cons_high = cons_info.get('target_price_high')
    cons_low = cons_info.get('target_price_low')

    categories = ['매수 권장가', '기준 적정가', '매도 목표가', '현재주가']
    values = [buy_price, fair_price, sell_price, current_price]
    colors = ['#34D399', '#FBBF24', '#F87171', '#38BDF8']

    if cons_avg:
        categories.append('증권사 평균목표가')
        values.append(cons_avg)
        colors.append('#818CF8')
    if cons_high:
        categories.append('증권사 최고목표가')
        values.append(cons_high)
        colors.append('#A5B4FC')
    if cons_low:
        categories.append('증권사 최저목표가')
        values.append(cons_low)
        colors.append('#C7D2FE')

    fig_bar = go.Figure(go.Bar(
        x=categories,
        y=values,
        text=[f"{v:,.0f}원" for v in values],
        textposition='outside',
        marker_color=colors,
        textfont=dict(color='#F8FAFC', size=12)
    ))
    fig_bar.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font={'color': '#F8FAFC'},
        title=dict(
            text="<b>S-RIM 적정주가 vs 증권사 목표주가 비교</b><br><span style='font-size:0.82em; color:#94A3B8;'>최근 3개월 발표 증권사 리포트 기준</span>",
            font=dict(color='#F8FAFC', size=15),
            x=0.5,
            xanchor='center',
            y=0.90
        ),
        yaxis=dict(title="주가 (원)", tickformat=',d', gridcolor='#334155', tickfont=dict(color='#94A3B8')),
        xaxis=dict(tickfont=dict(color='#E2E8F0', size=11)),
        height=410,
        margin=dict(l=20, r=20, t=75, b=25)
    )
    st.plotly_chart(fig_bar, use_container_width=True)

# -------------------------------------------------------------
# 5. 실적 추이 및 ROE 트렌드 차트
# -------------------------------------------------------------
if highlights_ann is not None and not highlights_ann.empty:
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("#### 📈 ROE 및 실적 추이 (과거 5년 실적 + 향후 3년 컨센서스)")
    
    roe_series = None
    for idx in highlights_ann.index:
        if "ROE" in str(idx):
            roe_series = highlights_ann.loc[idx]
            break
            
    ni_series = None
    for idx in highlights_ann.index:
        clean_idx = str(idx).replace(" ", "")
        if "지배" in clean_idx and "순이익" in clean_idx:
            ni_series = highlights_ann.loc[idx]
            break

    if roe_series is not None:
        fig_trend = go.Figure()
        
        # ROE 막대
        fig_trend.add_trace(go.Bar(
            x=list(roe_series.index),
            y=list(roe_series.values),
            name="ROE (%)",
            text=[f"{v:.1f}%" if (v is not None and not pd.isna(v)) else "-" for v in roe_series.values],
            textposition='outside',
            marker_color=['#64748B' if '(E)' not in str(c) else '#38BDF8' for c in roe_series.index],
            textfont=dict(color='#F8FAFC'),
            yaxis='y1'
        ))

        # 요구수익률 기준선
        fig_trend.add_trace(go.Scatter(
            x=list(roe_series.index),
            y=[final_req_return * 100.0] * len(roe_series),
            mode='lines',
            name=f"요구수익률 ({final_req_return*100:.1f}%)",
            line=dict(color='#F87171', width=2.5, dash='dash'),
            yaxis='y1'
        ))

        # 지배주주순이익 꺾은선 (억원)
        if ni_series is not None:
            fig_trend.add_trace(go.Scatter(
                x=list(ni_series.index),
                y=list(ni_series.values),
                name="지배주주순이익 (억원)",
                mode='lines+markers',
                line=dict(color='#34D399', width=3),
                marker=dict(size=7),
                yaxis='y2'
            ))

        fig_trend.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font={'color': '#F8FAFC'},
            title=dict(text="<b>연도별 ROE 추이 vs 요구수익률 및 순이익 (회색: 실적, 하늘색: 컨센서스)</b>", font=dict(color='#F8FAFC', size=16)),
            xaxis=dict(title="연도", gridcolor='#334155', tickfont=dict(color='#94A3B8')),
            yaxis=dict(title="ROE (%)", side='left', gridcolor='#334155', tickfont=dict(color='#94A3B8')),
            yaxis2=dict(title="지배주주순이익 (억원)", side='right', overlaying='y', showgrid=False, tickformat=',d', tickfont=dict(color='#94A3B8')),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(color='#F8FAFC')),
            height=380,
            margin=dict(l=20, r=20, t=55, b=20)
        )
        st.plotly_chart(fig_trend, use_container_width=True)

# -------------------------------------------------------------
# 6. 세부 분석 탭 섹션 (Tabs)
# -------------------------------------------------------------
st.markdown("<br>", unsafe_allow_html=True)
st.markdown("#### 🔍 세부 분석 데이터 및 시뮬레이션")

tabs = st.tabs([
    "📊 민감도 분석 매트릭스",
    "📑 재무 하이라이트 (연간/분기)",
    "🏢 증권사 리포트 컨센서스",
    "📈 10개년 잔여이익(RI) 시뮬레이션 표"
])

# Tab 1: 민감도 분석 매트릭스
with tabs[0]:
    st.markdown("##### 🎯 할인율(요구수익률) × 추정 ROE 변동에 따른 적정주가 민감도 표")
    st.caption("초과이익 10% 감소(기준 적정주가) 시나리오 기반. 현재주가 대비 안전마진이 확보된 셀(적정가 > 현재가)은 녹색으로 강조됩니다.")
    
    sens_df = generate_sensitivity_matrix(base_equity_val, net_shares, current_price, applied_roe, final_req_return)
    if sens_df is not None:
        def style_sensitivity(val):
            if isinstance(val, (int, float)):
                if current_price > 0 and val >= current_price:
                    return "background-color: rgba(52, 211, 153, 0.25); font-weight: bold; color: #34D399;"
                else:
                    return "color: #94A3B8;"
            return ""

        styled_sens = sens_df.style.map(style_sensitivity).format("{:,.0f}원")
        st.dataframe(styled_sens, use_container_width=True)
    else:
        st.info("민감도 분석에 필요한 주식수 또는 자본총계 데이터가 부족합니다.")

# Tab 2: 재무 하이라이트
with tabs[1]:
    subtab_ann, subtab_qtr = st.tabs(["연간 실적 & 컨센서스", "최근 분기 실적"])
    with subtab_ann:
        if highlights_ann is not None and not highlights_ann.empty:
            st.dataframe(highlights_ann.style.format(precision=2, na_rep="-"), use_container_width=True)
        else:
            st.info("연간 재무 하이라이트 데이터가 없습니다.")
            
    with subtab_qtr:
        if highlights_qtr is not None and not highlights_qtr.empty:
            st.dataframe(highlights_qtr.style.format(precision=2, na_rep="-"), use_container_width=True)
        else:
            st.info("분기 재무 하이라이트 데이터가 없습니다.")

# Tab 3: 증권사 리포트 컨센서스
with tabs[2]:
    reports = data.get('consensus_reports', [])
    if reports:
        count_3m = cons_info.get('analyst_count_3m', 0)
        avg_3m = cons_info.get('target_price_avg')
        avg_str = f"{avg_3m:,.0f}원" if avg_3m else "3개월 내 리포트 없음"
        st.markdown(f"##### 📋 증권사 리포트 투자의견 및 목표주가 (최근 3개월 반영: **{count_3m}건**, 3개월 평균 목표가: **{avg_str}**)")
        
        rep_rows = []
        for r in reports:
            is_3m = r.get('is_recent_3m', True)
            rep_rows.append({
                "추정기관": r.get('broker'),
                "작성일자": r.get('date'),
                "목표주가": r.get('target_price'),
                "직전 목표주가": r.get('prev_price'),
                "증감율(%)": r.get('change_rate'),
                "투자의견": r.get('opinion'),
                "3개월 집계": "🟢 반영" if is_3m else "⚪ 제외 (3개월 초과)"
            })
        rep_df = pd.DataFrame(rep_rows)
        st.dataframe(
            rep_df.style.format({
                "목표주가": lambda v: f"{v:,.0f}원" if pd.notnull(v) and isinstance(v, (int, float)) else "-",
                "직전 목표주가": lambda v: f"{v:,.0f}원" if pd.notnull(v) and isinstance(v, (int, float)) else "-",
                "증감율(%)": lambda v: f"{v:+.2f}%" if pd.notnull(v) and isinstance(v, (int, float)) else "-"
            }),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("해당 종목에 등록된 최근 증권사 리포트 컨센서스가 없습니다 (중소형주 등).")

# Tab 4: 10개년 잔여이익(RI) 시뮬레이션 표
with tabs[3]:
    st.markdown("##### 📈 엑셀 'RIM계산' 시트 연도별 잔여이익(RI) 추정 스케줄 (10% 감쇠 기준)")
    st.caption("매년 창출되는 초과이익(Excess Earnings)을 사내 유보하여 자본을 증대시키고, 각 연도 초과이익을 현재가치로 할인한 표입니다.")
    
    if multi_eval and multi_eval.get('schedule'):
        sch_df = pd.DataFrame(multi_eval['schedule'])
        sch_df.columns = ["연차", "ROE(%)", "지배주주순이익(억원)", "초과이익(억원)", "기말지배주주지분(억원)"]
        st.dataframe(
            sch_df.style.format({
                "ROE(%)": "{:.2f}%",
                "지배주주순이익(억원)": "{:,.1f}",
                "초과이익(억원)": "{:,.1f}",
                "기말지배주주지분(억원)": "{:,.1f}"
            }),
            use_container_width=True,
            hide_index=True
        )
        st.markdown(f"""
        - **초과이익 현재가치 합계(NPV of RI)**: **{multi_eval['scenarios']['decay10']['npv_ri']:,.1f} 억원**
        - **기준시점 기업가치**: **{multi_eval['scenarios']['decay10']['val_base']:,.1f} 억원**
        - **오늘 시점 할인 기업가치**: **{multi_eval['scenarios']['decay10']['val_today']:,.1f} 억원**
        """)
    else:
        st.info("다기간 시뮬레이션 데이터가 없습니다.")

st.markdown("<br><hr>", unsafe_allow_html=True)
st.markdown("<div style='text-align:center; color:#64748B; font-size:0.85rem;'>Magic S-RIM Dashboard | Data Source: fnGuide (wcomp.fnguide.com) | Based on Sa Gyeong-in Residual Income Model</div>", unsafe_allow_html=True)
