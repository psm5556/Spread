import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import requests

# 페이지 설정
st.set_page_config(
    page_title="금리 스프레드 모니터링",
    page_icon="📊",
    layout="wide"
)

# FRED API 키 가져오기 (Streamlit Secrets 사용)
try:
    api_key = st.secrets["FRED_API_KEY"]
except Exception as e:
    st.error("⚠️ FRED API 키가 설정되지 않았습니다.")
    st.info("""
    **Streamlit Cloud Secrets 설정 방법:**
    
    1. Streamlit Cloud 대시보드에서 앱 선택
    2. Settings → Secrets 메뉴 클릭
    3. 다음 형식으로 입력:
    ```
    FRED_API_KEY = "your_api_key_here"
    ```
    4. Save 클릭
    
    **로컬 실행 시:**
    
    `.streamlit/secrets.toml` 파일 생성 후 동일한 형식으로 입력
    
    **FRED API 키 발급:**
    https://fred.stlouisfed.org/ 에서 무료 계정 생성 후 발급
    """)
    api_key = None

# 사이드바 설정
st.sidebar.title("설정")
st.sidebar.success("✅ API 키 연결됨" if api_key else "❌ API 키 없음")

st.sidebar.markdown("---")
st.sidebar.markdown("### 📊 스프레드 계산 방식")
st.sidebar.markdown("""
**각 스프레드는 다음과 같이 계산됩니다:**

1. **EFFR - IORB**
   - 시장금리 - Fed 지급금리
   - 보통 음수 (EFFR < IORB)

2. **SOFR - RRP**
   - 담보부 레포 - 역레포
   - 보통 양수 (SOFR > RRP)

3. **3M TB - EFFR**
   - 3개월 국채 - 연방기금
   - 텀 프리미엄 반영

4. **10Y - 2Y**
   - 장기물 - 단기물
   - 수익률 곡선 기울기
""")

# 스프레드 정의
SPREADS = {
    "EFFR-IORB": {
        "name": "EFFR - IORB",
        "series": ["EFFR", "IORB"],
        "multiplier": 1000,
        "threshold_min": -10,
        "threshold_max": -5,
        "description": "준비금 충분성 지표 (좁아질수록 준비금 부족 신호)",
        "normal_range": "-10 ~ -5bp",
        "interpretation": "정상: 충분한 준비금 / 주의(-5bp 초과): 준비금 감소, QT 종료 임박"
    },
    "SOFR-RRP": {
        "name": "SOFR - RRP",
        "series": ["SOFR", "RRPONTSYAWARD"],
        "multiplier": 1000,
        "threshold_min": 0,
        "threshold_max": 10,
        "description": "레포 시장 유동성 압박 지표",
        "normal_range": "0 ~ 10bp",
        "interpretation": "정상: 안정적 레포 시장 / 주의(10bp 초과): 유동성 긴축, 분기말 압박"
    },
    "DGS3MO-EFFR": {
        "name": "3M Treasury - EFFR",
        "series": ["DGS3MO", "EFFR"],
        "multiplier": 100,
        "threshold_min": -5,
        "threshold_max": 15,
        "description": "단기 금리 기대 및 정책 프리미엄",
        "normal_range": "-5 ~ 15bp",
        "interpretation": "음수: 금리인하 기대 강함 / 양수: 정상 텀 프리미엄"
    },
    "DGS10-DGS2": {
        "name": "10Y - 2Y Yield Curve",
        "series": ["DGS10", "DGS2"],
        "multiplier": 100,
        "threshold_min": 0,
        "threshold_max": 100,
        "description": "경기 사이클 및 경기침체 예측 지표",
        "normal_range": "0 ~ 100bp",
        "interpretation": "음수(역전): 12-18개월 내 경기침체 가능성 / 양수: 정상 성장 기대"
    }
}

def fetch_fred_data(series_id, api_key, start_date=None):
    """FRED API로부터 데이터 가져오기"""
    if not start_date:
        start_date = (datetime.now() - timedelta(days=365*2)).strftime('%Y-%m-%d')
    
    url = f"https://api.stlouisfed.org/fred/series/observations"
    params = {
        'series_id': series_id,
        'api_key': api_key,
        'file_type': 'json',
        'observation_start': start_date
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if 'observations' in data:
            df = pd.DataFrame(data['observations'])
            df['date'] = pd.to_datetime(df['date'])
            df['value'] = pd.to_numeric(df['value'], errors='coerce')
            df = df[['date', 'value']].dropna()
            df = df.set_index('date')
            return df
    except Exception as e:
        st.error(f"데이터 로딩 실패 ({series_id}): {str(e)}")
        return None

def calculate_spread(spread_info, api_key, start_date):
    """스프레드 계산"""
    series1_id, series2_id = spread_info['series']
    
    # 데이터 가져오기
    df1 = fetch_fred_data(series1_id, api_key, start_date)
    df2 = fetch_fred_data(series2_id, api_key, start_date)
    
    if df1 is None or df2 is None:
        return None, None, None
    
    # 데이터 병합
    df = df1.join(df2, how='outer', rsuffix='_2')
    df.columns = [series1_id, series2_id]
    df = df.fillna(method='ffill').dropna()
    
    # 스프레드 계산
    df['spread'] = (df[series1_id] - df[series2_id]) * spread_info['multiplier']
    
    # 최신 값
    latest_value = df['spread'].iloc[-1] if len(df) > 0 else None
    
    return df, latest_value, df[[series1_id, series2_id]]

def create_spread_chart(df, spread_name, spread_info, latest_value):
    """스프레드 차트 생성"""
    fig = go.Figure()
    
    # 스프레드 라인
    fig.add_trace(go.Scatter(
        x=df.index,
        y=df['spread'],
        mode='lines',
        name='Spread',
        line=dict(color='#2E86DE', width=2)
    ))
    
    # 정상 범위 표시
    fig.add_hrect(
        y0=spread_info['threshold_min'],
        y1=spread_info['threshold_max'],
        fillcolor="green",
        opacity=0.1,
        line_width=0,
        annotation_text="정상 범위",
        annotation_position="top left"
    )
    
    # 레이아웃
    fig.update_layout(
        title=f"{spread_name} ({spread_info['normal_range']})",
        xaxis_title="날짜",
        yaxis_title="Basis Points (bp)",
        hovermode='x unified',
        height=400,
        showlegend=True
    )
    
    return fig

def create_components_chart(df_components, series_ids):
    """구성 요소 차트 생성"""
    fig = go.Figure()
    
    colors = ['#EE5A6F', '#4ECDC4']
    for i, series in enumerate(series_ids):
        fig.add_trace(go.Scatter(
            x=df_components.index,
            y=df_components[series],
            mode='lines',
            name=series,
            line=dict(color=colors[i], width=2)
        ))
    
    fig.update_layout(
        title="구성 요소",
        xaxis_title="날짜",
        yaxis_title="Rate (%)",
        hovermode='x unified',
        height=300,
        showlegend=True
    )
    
    return fig

# 메인 UI
st.title("📊 금리 스프레드 모니터링 대시보드")
st.markdown("**미국 금리 시장 스프레드 실시간 모니터링**")

if api_key:
    # 기간 선택
    col1, col2 = st.columns(2)
    with col1:
        period = st.selectbox(
            "조회 기간",
            ["1개월", "3개월", "6개월", "1년", "2년", "전체"],
            index=3
        )
    
    period_map = {
        "1개월": 30,
        "3개월": 90,
        "6개월": 180,
        "1년": 365,
        "2년": 730,
        "전체": 365 * 10
    }
    
    start_date = (datetime.now() - timedelta(days=period_map[period])).strftime('%Y-%m-%d')
    
    # 현재 상태 요약
    st.subheader("📍 현재 상태 (2025-11)")
    
    summary_cols = st.columns(4)
    
    for idx, (key, spread_info) in enumerate(SPREADS.items()):
        with summary_cols[idx]:
            with st.spinner(f'{spread_info["name"]} 로딩 중...'):
                df_spread, latest_value, df_components = calculate_spread(
                    spread_info, api_key, start_date
                )
                
                if latest_value is not None:
                    # 상태 판단
                    in_range = spread_info['threshold_min'] <= latest_value <= spread_info['threshold_max']
                    status = "✅ 정상" if in_range else "⚠️ 주의"
                    delta_color = "normal" if in_range else "inverse"
                    
                    st.metric(
                        label=spread_info['name'],
                        value=f"{latest_value:.1f}bp",
                        delta=status
                    )
                    st.caption(spread_info['description'])
    
    # 연준 정책금리 및 주요 금리 차트
    st.subheader("🎯 연준 정책금리 프레임워크")
    
    with st.spinner('데이터 로딩 중...'):
        # 정책금리 관련 데이터 가져오기
        policy_series = {
            'SOFR': '담보부 익일물 금리',
            'RRPONTSYAWARD': 'ON RRP (하한)',
            'IORB': '준비금 이자율',
            'EFFR': '연방기금 실효금리',
            'DFEDTARL': 'FF 목표 하한',
            'DFEDTARU': 'FF 목표 상한'
        }
        
        policy_data = {}
        for series_id in policy_series.keys():
            df = fetch_fred_data(series_id, api_key, start_date)
            if df is not None:
                policy_data[series_id] = df
        
        if len(policy_data) > 0:
            # 모든 데이터 병합
            combined_df = pd.DataFrame()
            for series_id, df in policy_data.items():
                combined_df[series_id] = df['value']
            
            combined_df = combined_df.fillna(method='ffill').dropna()
            
            # 차트 생성
            fig = go.Figure()
            
            # 목표 범위 (음영)
            if 'DFEDTARL' in combined_df.columns and 'DFEDTARU' in combined_df.columns:
                fig.add_trace(go.Scatter(
                    x=combined_df.index,
                    y=combined_df['DFEDTARU'],
                    mode='lines',
                    name='FF 목표 상한',
                    line=dict(color='rgba(200,200,200,0.3)', width=1, dash='dash'),
                    showlegend=True
                ))
                fig.add_trace(go.Scatter(
                    x=combined_df.index,
                    y=combined_df['DFEDTARL'],
                    mode='lines',
                    name='FF 목표 하한',
                    line=dict(color='rgba(200,200,200,0.3)', width=1, dash='dash'),
                    fill='tonexty',
                    fillcolor='rgba(200,200,200,0.1)',
                    showlegend=True
                ))
            
            # 주요 금리들
            colors = {
                'SOFR': '#FF6B6B',
                'RRPONTSYAWARD': '#4ECDC4',
                'IORB': '#95E1D3',
                'EFFR': '#F38181'
            }
            
            for series_id, label in policy_series.items():
                if series_id in combined_df.columns and series_id not in ['DFEDTARL', 'DFEDTARU']:
                    fig.add_trace(go.Scatter(
                        x=combined_df.index,
                        y=combined_df[series_id],
                        mode='lines',
                        name=f'{series_id} ({label})',
                        line=dict(color=colors.get(series_id, '#999999'), width=2)
                    ))
            
            fig.update_layout(
                title="연준 정책금리 프레임워크 및 시장 금리",
                xaxis_title="날짜",
                yaxis_title="금리 (%)",
                hovermode='x unified',
                height=500,
                showlegend=True,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            # 설명
            col1, col2 = st.columns(2)
            with col1:
                st.info("""
                **연준의 금리 조절 메커니즘:**
                - **목표 범위**: FOMC가 설정한 정책금리 범위 (회색 음영)
                - **IORB**: 은행 준비금에 대한 이자 (상한 역할)
                - **ON RRP**: 역레포 금리 (하한 역할)
                - **EFFR**: 실제 시장에서 거래되는 금리
                - **SOFR**: 국채 담보부 레포 금리
                """)
            
            with col2:
                if combined_df is not None and len(combined_df) > 0:
                    latest = combined_df.iloc[-1]
                    st.success(f"""
                    **최신 금리 (%):**
                    - SOFR: {latest.get('SOFR', 0):.2f}%
                    - EFFR: {latest.get('EFFR', 0):.2f}%
                    - IORB: {latest.get('IORB', 0):.2f}%
                    - ON RRP: {latest.get('RRPONTSYAWARD', 0):.2f}%
                    - 목표범위: {latest.get('DFEDTARL', 0):.2f}% - {latest.get('DFEDTARU', 0):.2f}%
                    """)
    
    st.markdown("---")
    
    # 상세 차트
    st.subheader("📈 상세 차트")
    
    tabs = st.tabs([spread_info['name'] for spread_info in SPREADS.values()])
    
    for idx, (key, spread_info) in enumerate(SPREADS.items()):
        with tabs[idx]:
            with st.spinner('데이터 로딩 중...'):
                df_spread, latest_value, df_components = calculate_spread(
                    spread_info, api_key, start_date
                )
                
                if df_spread is not None:
                    col1, col2 = st.columns([2, 1])
                    
                    with col1:
                        # 최신 값 및 통계
                        stat_cols = st.columns(4)
                        with stat_cols[0]:
                            st.metric("현재 값", f"{latest_value:.2f}bp")
                        with stat_cols[1]:
                            st.metric("평균", f"{df_spread['spread'].mean():.2f}bp")
                        with stat_cols[2]:
                            st.metric("최대", f"{df_spread['spread'].max():.2f}bp")
                        with stat_cols[3]:
                            st.metric("최소", f"{df_spread['spread'].min():.2f}bp")
                    
                    with col2:
                        st.info(f"""
                        **정상 범위:** {spread_info['normal_range']}
                        
                        **의미:** {spread_info['description']}
                        
                        **해석:** {spread_info['interpretation']}
                        """)
                    
                    # 스프레드 차트
                    st.plotly_chart(
                        create_spread_chart(df_spread, spread_info['name'], spread_info, latest_value),
                        use_container_width=True
                    )
                    
                    # 구성 요소 차트
                    if df_components is not None:
                        with st.expander("구성 요소 보기"):
                            st.plotly_chart(
                                create_components_chart(df_components, spread_info['series']),
                                use_container_width=True
                            )
                            
                            # 최신 값 테이블
                            latest_components = df_components.iloc[-1]
                            st.dataframe(
                                pd.DataFrame({
                                    '지표': spread_info['series'],
                                    '현재 값 (%)': [f"{val:.4f}" for val in latest_components.values]
                                }),
                                hide_index=True
                            )
                else:
                    st.error("데이터를 불러올 수 없습니다.")

    # 푸터
    st.markdown("---")
    st.caption(f"데이터 출처: Federal Reserve Economic Data (FRED) | 최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
