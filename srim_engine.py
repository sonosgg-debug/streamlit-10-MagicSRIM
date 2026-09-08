"""
srim_engine.py
S-RIM(잔여이익모델) 가치평가 및 미래 ROE 추정, 민감도 분석을 수행하는 핵심 계산 엔진
"""

import math
from datetime import datetime, date
import pandas as pd
import numpy as np

def calculate_required_return(mode="fixed", fixed_rate=0.125, beta=1.0, rf=0.035, erp=0.065, bond_yield=0.095):
    """
    요구수익률(할인율) 산정
    mode:
      - 'bond': BBB- 5년 만기 회사채 수익률 기반 (사경인 회계사 권장 표준)
      - 'capm': CAPM 모델 (Rf + Beta * ERP)
      - 'fixed': 별도 고정 요구수익률 (예: 12.5%)
    """
    if mode == "bond":
        return bond_yield
    elif mode == "capm":
        b = beta if (beta is not None and beta > 0) else 1.0
        return rf + b * erp
    elif mode == "fixed":
        return fixed_rate
    return fixed_rate

def extract_roe_candidates(highlights_annual, highlights_quarter):
    """
    재무제표 데이터로부터 다양한 관점의 미래 ROE 후보들을 계산하여 전문가 권장 우선순위대로 반환
    """
    raw_cand = {}
    
    # 1. 연간 ROE 행 추출
    if highlights_annual is not None and not highlights_annual.empty:
        roe_row = None
        for idx in highlights_annual.index:
            if "ROE" in str(idx):
                roe_row = highlights_annual.loc[idx]
                break
                
        if roe_row is not None:
            # 과거 실적 연도와 컨센서스(E) 연도 구분
            hist_cols = [c for c in roe_row.index if "(E)" not in str(c) and str(c).strip()]
            cons_cols = [c for c in roe_row.index if "(E)" in str(c) and str(c).strip()]
            
            # [1순위 권장] 향후 3개년 평균 컨센서스
            valid_cons = [float(roe_row[c]) / 100.0 for c in cons_cols if roe_row[c] is not None and not pd.isna(roe_row[c])]
            if valid_cons:
                raw_cand['cons_avg'] = {
                    'name': f"향후 3개년 평균 컨센서스 ({len(valid_cons)}개년 평균)",
                    'value': sum(valid_cons) / len(valid_cons)
                }

            # [2순위] 당해년도(1년차) 컨센서스
            if cons_cols:
                v1 = roe_row[cons_cols[0]]
                if v1 is not None and not pd.isna(v1):
                    raw_cand['cons_1y'] = {
                        'name': f"당해년도(1년차) 컨센서스 ({cons_cols[0]})",
                        'value': float(v1) / 100.0
                    }

            # [3순위] 컨센서스 최종년도 (기존 엑셀 방식)
            if cons_cols:
                v_last = roe_row[cons_cols[-1]]
                if v_last is not None and not pd.isna(v_last):
                    raw_cand['cons_terminal'] = {
                        'name': f"최종년도({len(cons_cols)}년차) 컨센서스 ({cons_cols[-1]})",
                        'value': float(v_last) / 100.0
                    }

            # [4순위 / 컨센서스 부재시 1순위] 과거 실적 가중평균 (최근 3개년 3:2:1 가중치)
            valid_hist = [float(roe_row[c]) / 100.0 for c in hist_cols if roe_row[c] is not None and not pd.isna(roe_row[c])]
            if len(valid_hist) >= 3:
                # 최근 3개년: 마지막 3개 (최근 순 3:2:1 가중치)
                y3, y2, y1 = valid_hist[-1], valid_hist[-2], valid_hist[-3]
                weighted = (y3 * 3 + y2 * 2 + y1 * 1) / 6.0
                raw_cand['weighted_hist'] = {'name': "과거 3개년 가중평균 (3:2:1)", 'value': weighted}
            elif len(valid_hist) == 2:
                weighted = (valid_hist[-1] * 2 + valid_hist[-2] * 1) / 3.0
                raw_cand['weighted_hist'] = {'name': "과거 2개년 가중평균 (2:1)", 'value': weighted}
            elif len(valid_hist) == 1:
                raw_cand['weighted_hist'] = {'name': f"최근 1개년 결산 ROE ({hist_cols[-1]})", 'value': valid_hist[0]}

    # 2. [5순위] 최근 4분기 합산(LTM) ROE 계산 (동적 4개 분기 자동 추적)
    if highlights_quarter is not None and not highlights_quarter.empty:
        # (E)가 붙지 않은 실제 확정/잠정 실적 분기 칼럼만 동적으로 추출 (오름차순)
        q_cols = [c for c in highlights_quarter.columns if "(E)" not in str(c) and str(c).strip()]
        if len(q_cols) >= 4:
            recent_4q = q_cols[-4:]  # 가장 최신 4개 분기 (예: 2025/09 ~ 2026/06)
            
            # (방법 1) FnGuide 공식 산출 분기 ROE 행의 최신 분기값 확인
            fng_roe = None
            if "ROE" in highlights_quarter.index:
                last_col = recent_4q[-1]
                val = highlights_quarter.loc["ROE"].get(last_col)
                if val is not None and not pd.isna(val):
                    try:
                        fng_roe = float(val) / 100.0
                    except Exception:
                        pass

            # (방법 2) 지배주주순이익 4분기 합산 / 평균 지배주주지분 직접 계산
            calc_roe = None
            ni_row = None
            for k in ["당기순이익(지배)", "당기순이익"]:
                if k in highlights_quarter.index:
                    ni_row = highlights_quarter.loc[k]
                    break
            eq_row = None
            for k in ["자본총계(지배)", "자본총계"]:
                if k in highlights_quarter.index:
                    eq_row = highlights_quarter.loc[k]
                    break

            if ni_row is not None and eq_row is not None:
                try:
                    s_ni = sum([float(ni_row[c]) for c in recent_4q if c in ni_row and not pd.isna(ni_row[c])])
                    a_eq = sum([float(eq_row[c]) for c in recent_4q if c in eq_row and not pd.isna(eq_row[c])]) / 4.0
                    if a_eq > 0:
                        calc_roe = s_ni / a_eq
                except Exception:
                    pass

            final_ltm = fng_roe if fng_roe is not None else calc_roe
            if final_ltm is not None:
                raw_cand['ltm_qtr'] = {
                    'name': f"최근 4분기 합산(LTM) ROE ({recent_4q[0]}~{recent_4q[-1]})",
                    'value': final_ltm
                }

    # 전문가 권장 순위대로 정렬하여 반환
    pref_order = ['cons_avg', 'cons_1y', 'cons_terminal', 'weighted_hist', 'ltm_qtr']
    candidates = {k: raw_cand[k] for k in pref_order if k in raw_cand}
    for k in raw_cand:
        if k not in candidates:
            candidates[k] = raw_cand[k]

    return candidates

def get_base_equity_data(highlights_annual, highlights_quarter):
    """
    S-RIM 평가의 기초가 되는 최신 지배주주지분(자본총계) 및 기준일자 추출
    """
    # 1. 분기 데이터에서 최신 실적 분기 확인
    if highlights_quarter is not None and not highlights_quarter.empty:
        eq_row = None
        for idx in highlights_quarter.index:
            idx_str = str(idx).replace(" ", "")
            if ("지배" in idx_str and "지분" in idx_str) or ("자본총계(지배)" in idx_str):
                eq_row = highlights_quarter.loc[idx]
                break
        if eq_row is None and "자본총계" in highlights_quarter.index:
            eq_row = highlights_quarter.loc["자본총계"]
            
        if eq_row is not None:
            hist_cols = [c for c in eq_row.index if "(E)" not in str(c)]
            for col in reversed(hist_cols):
                val = eq_row[col]
                if val is not None and not pd.isna(val) and float(val) > 0:
                    return float(val), str(col)

    # 2. 연간 데이터에서 최신 결산연도 확인
    if highlights_annual is not None and not highlights_annual.empty:
        eq_row = None
        for idx in highlights_annual.index:
            idx_str = str(idx).replace(" ", "")
            if ("지배" in idx_str and "지분" in idx_str) or ("자본총계(지배)" in idx_str):
                eq_row = highlights_annual.loc[idx]
                break
        if eq_row is None and "자본총계" in highlights_annual.index:
            eq_row = highlights_annual.loc["자본총계"]
            
        if eq_row is not None:
            hist_cols = [c for c in eq_row.index if "(E)" not in str(c)]
            for col in reversed(hist_cols):
                val = eq_row[col]
                if val is not None and not pd.isna(val) and float(val) > 0:
                    return float(val), str(col)
                    
    return 0.0, "N/A"

def calculate_srim_standard(base_equity, net_shares, roe, req_return):
    """
    사경인 회계사 오리지널 S-RIM 가치평가 모델 (대한민국 가치투자 업계 표준)
    base_equity: 지배주주지분 (억원 단위)
    net_shares: 유효발행주식수 (보통주 + 우선주 - 자사주)
    roe: 추정 ROE (소수점, 예: 0.15)
    req_return: 요구수익률 (소수점, 예: 0.10)
    """
    if net_shares <= 0 or req_return <= 0 or base_equity <= 0:
        return {
            'is_aligned': True,
            'status_text': '계산 불가 (데이터 부족)',
            'val_persist': 0, 'price_persist': 0,
            'val_decay10': 0, 'price_decay10': 0,
            'val_decay20': 0, 'price_decay20': 0,
            'target_buy': 0, 'target_fair': 0, 'target_sell': 0
        }

    excess_spread = roe - req_return # (ROE - r)
    is_aligned = excess_spread >= 0 # 정배열 여부 (ROE >= 요구수익률)

    # Case 1: 초과이익 지속 (omega = 1.0)
    # V = B0 + B0 * (ROE - r) / r = B0 * ROE / r
    val_persist = base_equity * (roe / req_return)
    price_persist = (val_persist * 1e8) / net_shares

    # Case 2: 초과이익 10% 감소 (omega = 0.9)
    # V = B0 + B0 * (ROE - r) * 0.9 / (1 + r - 0.9)
    denom_10 = 1.0 + req_return - 0.9
    val_decay10 = base_equity + (base_equity * excess_spread * 0.9) / denom_10
    price_decay10 = (val_decay10 * 1e8) / net_shares

    # Case 3: 초과이익 20% 감소 (omega = 0.8)
    # V = B0 + B0 * (ROE - r) * 0.8 / (1 + r - 0.8)
    denom_20 = 1.0 + req_return - 0.8
    val_decay20 = base_equity + (base_equity * excess_spread * 0.8) / denom_20
    price_decay20 = (val_decay20 * 1e8) / net_shares

    if is_aligned:
        # 정배열: 지속 > 10%감소 > 20%감소
        target_sell = price_persist # 매도 목표가
        target_fair = price_decay10 # 기준 적정가
        target_buy = price_decay20  # 매수 권장가
        status_text = "정배열 (ROE > 요구수익률: 초과이익 창출)"
    else:
        # 역배열: 지속 < 10%감소 < 20%감소 (ROE가 요구수익률 미만)
        target_sell = price_decay20 # 상단
        target_fair = price_decay10 # 기준 적정가
        target_buy = price_persist  # 최하단 안전마진
        status_text = "역배열 (ROE < 요구수익률: 자본비용 미달)"

    return {
        'is_aligned': is_aligned,
        'status_text': status_text,
        'val_persist': round(val_persist, 1),
        'price_persist': round(price_persist),
        'val_decay10': round(val_decay10, 1),
        'price_decay10': round(price_decay10),
        'val_decay20': round(val_decay20, 1),
        'price_decay20': round(price_decay20),
        'target_buy': round(target_buy),
        'target_fair': round(target_fair),
        'target_sell': round(target_sell),
        'base_equity': base_equity,
        'net_shares': net_shares,
        'roe': roe,
        'req_return': req_return
    }

def calculate_srim_multiperiod(base_equity, net_shares, roe, req_return, base_date_str=None, today=None):
    """
    기존 엑셀 파일의 'RIM계산' 10개년 명시적 잔여이익(RI) 예측 시뮬레이션 모델 (버그 수정판)
    - 10년간 이익 전액 사내유보 및 잔여이익 NPV 할인
    - 기준일자(base_date)부터 오늘(today)까지의 기간 할인/할증 반영
    """
    if net_shares <= 0 or req_return <= 0 or base_equity <= 0:
        return None

    if today is None:
        today = date.today()
        
    diff_days = 0
    if base_date_str:
        try:
            clean_d = base_date_str.replace("(E)", "").strip()
            parts = clean_d.split("/")
            if len(parts) == 2:
                b_date = date(int(parts[0]), int(parts[1]), 28)
                diff_days = (b_date - today).days
        except Exception:
            diff_days = 0

    scenarios = {}
    schedule_data = [] # 10년 연도별 테이블

    for label, omega in [('persist', 1.0), ('decay10', 0.9), ('decay20', 0.8)]:
        equity = base_equity
        excess_spread = roe - req_return
        current_spread = excess_spread
        ri_list = []
        yearly_rows = []

        for yr in range(1, 11):
            if yr > 1:
                current_spread *= omega
            roe_t = req_return + current_spread
            net_income = equity * roe_t
            excess_earnings = equity * current_spread
            ri_list.append(excess_earnings)
            equity += net_income
            
            if label == 'decay10': # 대표 스케줄 표 저장
                yearly_rows.append({
                    'year': f"+{yr}년차",
                    'roe': roe_t * 100.0,
                    'net_income': net_income,
                    'excess_earnings': excess_earnings,
                    'end_equity': equity
                })

        npv_ri = sum(ri / ((1.0 + req_return) ** t) for t, ri in enumerate(ri_list, 1))
        val_base = base_equity + npv_ri
        
        # 오늘 시점 할인: val_today = val_base / (1+r)^(diff_days/365)
        discount_factor = (1.0 + req_return) ** (diff_days / 365.0) if diff_days != 0 else 1.0
        val_today = val_base / discount_factor
        
        price_base = (val_base * 1e8) / net_shares
        price_today = (val_today * 1e8) / net_shares
        
        scenarios[label] = {
            'npv_ri': round(npv_ri, 1),
            'val_base': round(val_base, 1),
            'val_today': round(val_today, 1),
            'price_base': round(price_base),
            'price_today': round(price_today)
        }
        
        if label == 'decay10':
            schedule_data = yearly_rows

    is_aligned = (roe >= req_return)
    if is_aligned:
        target_sell = scenarios['persist']['price_today']
        target_fair = scenarios['decay10']['price_today']
        target_buy = scenarios['decay20']['price_today']
    else:
        target_sell = scenarios['decay20']['price_today']
        target_fair = scenarios['decay10']['price_today']
        target_buy = scenarios['persist']['price_today']

    return {
        'is_aligned': is_aligned,
        'scenarios': scenarios,
        'target_buy': round(target_buy),
        'target_fair': round(target_fair),
        'target_sell': round(target_sell),
        'diff_days': diff_days,
        'schedule': schedule_data
    }

def generate_sensitivity_matrix(base_equity, net_shares, current_price, center_roe, center_req_return):
    """
    할인율(요구수익률)과 추정 ROE 변동에 따른 적정주가(10% 감소 시나리오 기준) 민감도 매트릭스 생성
    """
    if net_shares <= 0 or base_equity <= 0:
        return None

    # 할인율 축: center 주변 7개 구간 (예: 8% ~ 14%)
    r_steps = [round(center_req_return + delta, 3) for delta in [-0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03]]
    r_steps = [r for r in r_steps if 0.04 <= r <= 0.25]
    if len(r_steps) < 5:
        r_steps = [0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14]

    # ROE 축: center 주변 5개 구간
    roe_steps = [round(center_roe + delta, 3) for delta in [-0.06, -0.03, 0.0, 0.03, 0.06]]
    roe_steps = [roe for roe in roe_steps if roe > -0.5]

    matrix_data = []
    for roe_val in roe_steps:
        row = {'ROE': f"{roe_val*100:.1f}%"}
        for r_val in r_steps:
            col_name = f"할인율 {r_val*100:.1f}%"
            # 10% 감소 기준 적정가
            res = calculate_srim_standard(base_equity, net_shares, roe_val, r_val)
            fair_p = res['price_decay10']
            row[col_name] = fair_p
        matrix_data.append(row)

    df_matrix = pd.DataFrame(matrix_data).set_index('ROE')
    return df_matrix

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    print("Testing srim_engine with Samsung Electronics sample data...")
    # Base equity = 565,064 억원 (2026/06 지배주주지분), Net shares = 6,548,979,017
    std_res = calculate_srim_standard(
        base_equity=565064.74,
        net_shares=6548979017,
        roe=0.3475,
        req_return=0.125
    )
    print("\n--- Standard S-RIM Results ---")
    print("정배열 여부:", std_res['status_text'])
    print(f"매수 권장가 (20% 감소): {std_res['target_buy']:,} 원")
    print(f"기준 적정가 (10% 감소): {std_res['target_fair']:,} 원")
    print(f"매도 목표가 (초과이익 지속): {std_res['target_sell']:,} 원")

    multi_res = calculate_srim_multiperiod(
        base_equity=15125863.35, # 2028E equity (기존 엑셀 방식)
        net_shares=6548979017,
        roe=0.3475,
        req_return=0.125,
        base_date_str="2028/12"
    )
    print("\n--- Multi-period 10-Year Excel Engine Results ---")
    print(f"매수 권장가: {multi_res['target_buy']:,} 원")
    print(f"기준 적정가: {multi_res['target_fair']:,} 원")
    print(f"매도 목표가: {multi_res['target_sell']:,} 원")
