"""
fnguide_scraper.py
fnGuide(https://wcomp.fnguide.com/) 및 KRX 데이터를 수집하여 구조화된 데이터로 반환하는 모듈
"""

import os
import re
import json
import urllib.parse
from datetime import datetime
from io import StringIO
import requests
import pandas as pd
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
}

COMMON_ALIASES = {
    '삼전': '005930',
    '삼성전자': '005930',
    '삼성전자우': '005935',
    '하이닉스': '000660',
    'SK하이닉스': '000660',
    '현대차': '005380',
    '현대자동차': '005380',
    '현대차우': '005385',
    '기아': '000270',
    '기아차': '000270',
    '네이버': '035420',
    'NAVER': '035420',
    '카카오': '035720',
    'LG엔솔': '373220',
    'LG에너지솔루션': '373220',
    '포스코': '005490',
    'POSCO홀딩스': '005490',
    '삼바': '207940',
    '삼성바이오로직스': '207940',
    '셀트리온': '068270',
    '알테오젠': '196170',
    '에코프로': '086520',
    '에코프로비엠': '247540',
    '신한지주': '055550',
    'KB금융': '105560',
    'SK스퀘어': '402340',
    '삼성전기': '009150',
}

def clean_num(val, is_fraction=False):
    """숫자, 쉼표, 퍼센트 문자열을 float 또는 int로 변환 (결측 시 None 반환)"""
    if pd.isna(val) or val is None:
        return None
    val_str = str(val).strip().replace(",", "")
    if val_str in ("-", "", "N/A", "NaN", "NAN", "None"):
        return None
    if "%" in val_str:
        try:
            num = float(val_str.replace("%", "").strip())
            return num / 100.0 if is_fraction else num
        except ValueError:
            return val_str
    try:
        if "." in val_str:
            num = float(val_str)
            return round(num, 4)
        else:
            return int(val_str)
    except ValueError:
        return val_str

def get_krx_ticker_list(cache_dir="."):
    """KRX 상장기업 목록을 다운로드하여 {종목코드: 회사명} 딕셔너리로 반환 및 로컬 캐싱"""
    cache_path = os.path.join(cache_dir, "krx_tickers.json")
    if os.path.exists(cache_path):
        try:
            mtime = os.path.getmtime(cache_path)
            if (datetime.now().timestamp() - mtime) < 7 * 86400:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass

    url = 'http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13'
    tickers = {}
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            tables = pd.read_html(StringIO(res.text), flavor='lxml')
            df = tables[0]
            df['종목코드'] = df['종목코드'].astype(str).str.zfill(6)
            for _, row in df.iterrows():
                code = row['종목코드']
                name = str(row['회사명']).strip()
                tickers[code] = name
                
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(tickers, f, ensure_ascii=False, indent=2)
            return tickers
    except Exception as e:
        print(f"KRX list download error: {e}")
        
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def resolve_ticker(query, cache_dir="."):
    """
    사용자 입력(종목명 또는 6자리 코드)을 (종목코드, 정식종목명)으로 변환
    """
    q = str(query).strip()
    if not q:
        return None, None
        
    if re.match(r"^\d{6}$", q):
        tickers = get_krx_ticker_list(cache_dir)
        name = tickers.get(q, q)
        return q, name

    clean_q = q.replace(" ", "").upper()
    for alias, code in COMMON_ALIASES.items():
        if alias.replace(" ", "").upper() == clean_q:
            tickers = get_krx_ticker_list(cache_dir)
            name = tickers.get(code, alias)
            return code, name

    tickers = get_krx_ticker_list(cache_dir)
    # 1. 완전 일치
    for code, name in tickers.items():
        if name.replace(" ", "").upper() == clean_q:
            return code, name
            
    # 2. 접두사 일치
    for code, name in tickers.items():
        clean_name = name.replace(" ", "").upper()
        if clean_name.startswith(clean_q):
            return code, name

    # 3. 부분 포함
    for code, name in tickers.items():
        clean_name = name.replace(" ", "").upper()
        if clean_q in clean_name:
            return code, name

    return None, None

def _get_div_table(soup, div_id):
    """특정 div_id 하위의 HTML table 파싱"""
    div = soup.find('div', id=div_id)
    if not div:
        return None
    tbl = div.find('table')
    if not tbl:
        return None
    try:
        dfs = pd.read_html(StringIO(str(tbl)), flavor='lxml')
        return dfs[0] if dfs else None
    except Exception:
        return None

def _find_val_next_to(df, term):
    """DataFrame에서 term이 들어간 셀 바로 오른쪽 셀의 값을 반환"""
    if df is None or df.empty:
        return None
    term_clean = str(term).replace(" ", "").replace("\xa0", "").strip()
    for r in range(df.shape[0]):
        for c in range(df.shape[1]):
            cell_clean = str(df.iloc[r, c]).replace(" ", "").replace("\xa0", "").strip()
            if term_clean in cell_clean:
                if c + 1 < df.shape[1]:
                    return df.iloc[r, c + 1]
    return None

def _fetch_snp_financial(ticker, consol_typ='M', freq_typ='Y'):
    """
    fnGuide getSnpFinancial API 호출을 통한 8개 칼럼(실적 5년 + 컨센서스 3년) 하이라이트 테이블 획득
    consol_typ: 'M' (연결), 'P' (별도)
    freq_typ: 'Y' (연간), 'Q' (분기)
    """
    url = "https://wcomp.fnguide.com/CompanyInfo/getSnpFinancial"
    params = {
        "cmp_cd": ticker,
        "consol_typ": consol_typ,
        "freq_typ": freq_typ
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        dataset = data.get("dataset", {})
        headers_list = dataset.get("header", [])
        data_list = dataset.get("data", [])
        
        if not headers_list or not data_list:
            return None
            
        col_keys = []
        col_names = []
        for h in headers_list:
            cd = h.get("CD")
            yymm = h.get("YYMM")
            ep_chk = str(h.get("EP_CHK", "")).strip()
            col_name = f"{yymm}(E)" if ep_chk == "E" else yymm
            col_keys.append(cd)
            col_names.append(col_name)
            
        rows = {}
        for item in data_list:
            name = str(item.get("NAME", "")).replace("\xa0", " ").strip()
            if not name:
                continue
            vals = [clean_num(item.get(cd)) for cd in col_keys]
            rows[name] = vals
            
        df = pd.DataFrame(rows, index=col_names).T
        return df
    except Exception as e:
        print(f"Error fetching getSnpFinancial for {ticker} ({consol_typ}/{freq_typ}): {e}")
        return None

def scrape_company_data(ticker):
    """
    주어진 종목코드에 대해 fnGuide에서 전체 재무/시세/컨센서스 데이터를 수집
    """
    ticker = str(ticker).strip().zfill(6)
    result = {
        'ticker': ticker,
        'company_name': '',
        'inquiry_date': datetime.now().strftime("%Y/%m/%d"),
        'info': {},
        'highlights_annual': None,
        'highlights_quarter': None,
        'consensus_info': {},
        'consensus_reports': [],
        'industry_comp': {},
        'finance_ratios': {},
        'is_consolidated': True
    }

    # 1. Snapshot HTML
    snap_url = f"https://wcomp.fnguide.com/?cmp_cd={ticker}"
    res = requests.get(snap_url, headers=HEADERS, timeout=10)
    if res.status_code != 200:
        raise ValueError(f"fnGuide Snapshot 페이지 접속 실패 (상태 코드: {res.status_code})")
    soup = BeautifulSoup(res.text, 'html.parser')

    # 회사명
    corp_elem = soup.find('h1', id='giName')
    if corp_elem:
        result['company_name'] = corp_elem.get_text(strip=True)
    else:
        title_elem = soup.find('title')
        if title_elem:
            result['company_name'] = title_elem.get_text(strip=True).split("-")[0].strip()

    info = {}
    # 밸류에이션 지표 (PER, PBR, 배당수익률 등)
    corp_group2 = soup.find('div', id='corp_group2')
    if corp_group2:
        val_ratios = {}
        for btn in corp_group2.find_all('button', class_='tip_in'):
            b_id = btn.get('id')
            ul = btn.find_parent('ul')
            if ul:
                lis = ul.find_all('li')
                if len(lis) >= 2:
                    val_ratios[b_id] = lis[1].get_text(strip=True)
        info['per'] = clean_num(val_ratios.get('h_per'))
        info['fwd_per'] = clean_num(val_ratios.get('h_12m'))
        info['industry_per'] = clean_num(val_ratios.get('h_u_per'))
        info['pbr'] = clean_num(val_ratios.get('h_pbr'))
        info['dividend_yield'] = clean_num(val_ratios.get('h_rate'), is_fraction=True)

    # 시세 현황 (div1)
    t1 = _get_div_table(soup, 'div1')
    if t1 is not None:
        price_val = _find_val_next_to(t1, "종가/ 전일대비/수익률") or _find_val_next_to(t1, "종가/ 전일대비/ 수익률")
        if price_val and "/" in str(price_val):
            parts = str(price_val).split("/")
            info['current_price'] = clean_num(parts[0].strip())
            info['price_change'] = parts[1].strip() if len(parts) >= 2 else ""
            info['price_change_rate'] = parts[2].strip() if len(parts) >= 3 else ""
        else:
            info['current_price'] = clean_num(price_val)

        hl_val = _find_val_next_to(t1, "52주.최고가/ 최저가") or _find_val_next_to(t1, "52주 최고가/ 최저가")
        if hl_val and "/" in str(hl_val):
            hl_parts = str(hl_val).split("/")
            info['high_52'] = clean_num(hl_parts[0])
            info['low_52'] = clean_num(hl_parts[1])
        else:
            info['high_52'] = None
            info['low_52'] = None

        info['market_cap_total'] = clean_num(_find_val_next_to(t1, "시가총액 (상장예정포함,억원)")) or clean_num(_find_val_next_to(t1, "시가총액(상장예정포함,억원)"))
        info['market_cap_common'] = clean_num(_find_val_next_to(t1, "시가총액 (보통주,억원)")) or clean_num(_find_val_next_to(t1, "시가총액(보통주,억원)"))

        shares_str = _find_val_next_to(t1, "발행주식수(보통주/ 우선주)")
        if shares_str and "/" in str(shares_str):
            s_parts = str(shares_str).split("/")
            info['shares_common'] = clean_num(s_parts[0]) or 0
            info['shares_pref'] = clean_num(s_parts[1]) or 0
        else:
            info['shares_common'] = clean_num(shares_str) or 0
            info['shares_pref'] = 0
            
        info['shares_total'] = info['shares_common'] + info['shares_pref']
        info['beta'] = clean_num(_find_val_next_to(t1, "베타"))

    # 주주현황 - 자기주식 수량 (div4)
    t4 = _get_div_table(soup, 'div4')
    treasury_val = 0
    if t4 is not None:
        for _, row in t4.iterrows():
            label = str(row.iloc[0])
            if "자사주" in label or "자기주식" in label:
                treasury_val = clean_num(row.iloc[1]) or 0
                break
    info['shares_treasury'] = treasury_val
    info['shares_net'] = max(0, info.get('shares_total', 0) - treasury_val)
    result['info'] = info

    # 투자의견 컨센서스 (div6)
    t6 = _get_div_table(soup, 'div6')
    cons_info = {}
    if t6 is not None and not t6.empty:
        cons_info['opinion_score'] = clean_num(t6.iloc[0].get('투자의견'))
        cons_info['target_price_avg'] = clean_num(t6.iloc[0].get('목표주가'))
        cons_info['eps'] = clean_num(t6.iloc[0].get('EPS'))
        cons_info['per'] = clean_num(t6.iloc[0].get('PER'))
        cons_info['analyst_count'] = clean_num(t6.iloc[0].get('추정기관수'))

    # 업종비교 snpSector JSON
    html_text = res.text
    m_sec = re.search(r'snpSector\s*:\s*(\{.*?\})\s*,\s*\n', html_text, re.DOTALL)
    if m_sec:
        try:
            sec_data = json.loads(m_sec.group(1))
            header = sec_data.get("header", {})
            data_list = sec_data.get("data", [])
            ind_comp = {
                'company_name': header.get("VAL1"),
                'industry_name': header.get("VAL2"),
                'market_name': header.get("VAL3"),
                'metrics': {}
            }
            for r in data_list:
                m_name = r.get("NAME_S")
                ind_comp['metrics'][m_name] = {
                    'company': clean_num(r.get('VAL1')),
                    'industry': clean_num(r.get('VAL2')),
                    'market': clean_num(r.get('VAL3'))
                }
            result['industry_comp'] = ind_comp
        except Exception as e:
            print(f"Warning parsing snpSector JSON: {e}")

    # ============================================================
    # 2. Financial Highlights API (연결 시도 -> 별도 시도)
    # ============================================================
    df_ann_m = _fetch_snp_financial(ticker, consol_typ='M', freq_typ='Y')
    df_qtr_m = _fetch_snp_financial(ticker, consol_typ='M', freq_typ='Q')
    
    if df_ann_m is not None and not df_ann_m.empty:
        result['highlights_annual'] = df_ann_m
        result['highlights_quarter'] = df_qtr_m
        result['is_consolidated'] = True
    else:
        # 별도 재무제표로 fallback
        df_ann_p = _fetch_snp_financial(ticker, consol_typ='P', freq_typ='Y')
        df_qtr_p = _fetch_snp_financial(ticker, consol_typ='P', freq_typ='Q')
        result['highlights_annual'] = df_ann_p
        result['highlights_quarter'] = df_qtr_p
        result['is_consolidated'] = False

    # ============================================================
    # 3. Consensus 상세 페이지 스크래핑
    # ============================================================
    cons_url = f"https://wcomp.fnguide.com/CompanyInfo/Consensus?cmp_cd={ticker}"
    try:
        res_c = requests.get(cons_url, headers=HEADERS, timeout=10)
        if res_c.status_code == 200:
            soup_c = BeautifulSoup(res_c.text, 'html.parser')
            for tbl in soup_c.find_all('table'):
                tbl_text = tbl.get_text()
                if '적정주가' in tbl_text and '추정기관' in tbl_text:
                    c_dfs = pd.read_html(StringIO(str(tbl)), flavor='lxml')
                    if c_dfs:
                        c_df = c_dfs[0]
                        reports = []
                        target_prices = []
                        for _, row in c_df.iterrows():
                            broker = str(row.iloc[0]).strip()
                            if broker in ('Consensus', '평균', 'None', '', 'NaN') or '추정기관' in broker:
                                continue
                            date_s = str(row.iloc[1]).strip()
                            target_p = clean_num(row.iloc[2])
                            prev_p = clean_num(row.iloc[3]) if len(row) > 3 else None
                            change_r = clean_num(row.iloc[4]) if len(row) > 4 else None
                            opinion = str(row.iloc[5]).strip() if len(row) > 5 else ''
                            if target_p and isinstance(target_p, (int, float)):
                                target_prices.append(target_p)
                            reports.append({
                                'broker': broker,
                                'date': date_s,
                                'target_price': target_p,
                                'prev_price': prev_p,
                                'change_rate': change_r,
                                'opinion': opinion
                            })
                        result['consensus_reports'] = reports
                        if target_prices:
                            cons_info['target_price_high'] = max(target_prices)
                            cons_info['target_price_low'] = min(target_prices)
                            if not cons_info.get('target_price_avg'):
                                cons_info['target_price_avg'] = round(sum(target_prices) / len(target_prices))
                    break
    except Exception as e:
        print(f"Warning fetching consensus details: {e}")

    result['consensus_info'] = cons_info

    # 4. FinanceRatio (재무비율)
    ratio_url = f"https://wcomp.fnguide.com/CompanyInfo/FinanceRatio?cmp_cd={ticker}"
    try:
        res_r = requests.get(ratio_url, headers=HEADERS, timeout=10)
        if res_r.status_code == 200:
            soup_r = BeautifulSoup(res_r.text, 'html.parser')
            for s in soup_r.find_all('script'):
                if s.string and "rtoAccumulate" in s.string:
                    idx_ann = s.string.find("rtoAccumulate:")
                    if idx_ann != -1:
                        brace = s.string.find("{", idx_ann)
                        decoder = json.JSONDecoder()
                        ann_json, _ = decoder.raw_decode(s.string[brace:])
                        result['finance_ratios']['annual'] = ann_json
                    break
    except Exception as e:
        print(f"Warning fetching finance ratios: {e}")

    return result

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    print("Testing fnguide_scraper on 005930 (Samsung Electronics)...")
    data = scrape_company_data("005930")
    print("Company:", data['company_name'])
    print("Price:", data['info'].get('current_price'))
    print("Market Cap (억원):", data['info'].get('market_cap_common'))
    print("Shares Total:", data['info'].get('shares_total'))
    print("Treasury Shares:", data['info'].get('shares_treasury'))
    print("Net Shares:", data['info'].get('shares_net'))
    print("Beta:", data['info'].get('beta'))
    print("Consensus Info:", data['consensus_info'])
    print("Consensus Reports Count:", len(data['consensus_reports']))
    if data['highlights_annual'] is not None:
        print("\nAnnual Highlights Columns:", list(data['highlights_annual'].columns))
        print("Annual Highlights Indices (first 10):", list(data['highlights_annual'].index[:10]))
        if 'ROE' in data['highlights_annual'].index:
            print("\nROE:", data['highlights_annual'].loc['ROE'].to_dict())
