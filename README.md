# 📈 Magic S-RIM 가치 평가 및 미래 ROE 예측 대시보드

fnGuide(`https://wcomp.fnguide.com/`)의 실시간 재무 데이터와 증권사 컨센서스를 연동하여, **S-RIM(잔여이익모델, Residual Income Model)**을 통해 미래 ROE를 추정하고 적정주가를 정밀 산출하는 Streamlit 기반 인터랙티브 웹 대시보드입니다.

---

## 🌟 주요 특징 및 기능

1. **듀얼 S-RIM 가치평가 엔진**:
   - **사경인 정통 모델**: $B_0 + \frac{B_0 \times (ROE - r)}{r}$ 기본형 및 초과이익 지속/10% 감소/20% 감소 시나리오(매도 목표가, 기준 적정가, 매수 권장가)
   - **10개년 다기간 모델 (응용판)**: 10개년 미래 잔여이익(RI)의 복리 현재가치 할인 총합 기반 정밀 가치평가
2. **fnGuide 실시간 크롤링 & 컨센서스 자동 연동**:
   - 최신 지배주주지분(기준 자본총계), 발행주식수, 현재가, 8개년 재무제표(과거 5개년 실적 + 미래 3개년 컨센서스), 증권사 리포트 목록 실시간 수집
   - 컨센서스 부재 시 과거 3개년 가중평균(3:2:1) ROE 안전 자동 폴백
3. **스마트 종목 검색 및 드롭다운 (32 FinancialChart 연동)**:
   - KRX 상장 전종목(2,800여 개) 데이터베이스 기반 한글/코드 자동 필터링 검색
   - 대표 우량주(삼성전자, SK하이닉스, SK스퀘어, 삼성전기, LG에너지솔루션, 현대차) 원클릭 바로가기 버튼 지원
4. **다크 모드 최적화 UI & 시각화**:
   - 세련된 다크 그레이 톤 메트릭 카드
   - 화사하고 선명한 Plotly 아치형 주가 밴드 게이지 차트 & 증권사 목표주가 비교 막대 차트 (1:1 완벽 대칭 레이아웃)
   - 연간/분기 실적 추이, ROE 트렌드 꺾은선/막대 차트
5. **할인율 × ROE 2차원 민감도 분석 히트맵**:
   - 요구수익률과 추정 ROE 변화에 따른 적정주가 매트릭스 및 안전마진 확보 구간(녹색) 시각화
6. **버그 수정된 원클릭 엑셀 내보내기**:
   - 수작업 모델의 수식 오류(할인율 단절, 0 나누기 에러, 컨센서스 빈 셀 에러)를 완전 정정한 원본 양식 엑셀 파일(`.xlsx`) 생성 및 다운로드

---

## 🛠️ 기술 스택

- **UI / Frontend**: [Streamlit](https://streamlit.io/)
- **Visualizations**: [Plotly](https://plotly.com/)
- **Data Scraping**: `requests`, `BeautifulSoup4` (FnGuide Company Guide 웹 스크래핑 및 내부 REST API 연동)
- **Financial Modeling**: Python, `pandas`, `numpy`, `openpyxl`
- **Automation**: GitHub Actions (Streamlit Community Cloud 3일 주기 수면 방지 워크플로)

---

## 🚀 실행 방법

### 1. 필수 패키지 설치
```bash
pip install -r requirements.txt
```

### 2. 대시보드 실행
```bash
streamlit run app.py
```
브라우저에서 `http://localhost:8501`로 접속하여 이용하실 수 있습니다. (Windows 사용자는 `run_app.bat`을 더블 클릭하여 바로 실행 가능합니다.)
