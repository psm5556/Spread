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

# FRED API 키 입력 (사이드바)
st.sidebar.title("설정")
api_key = st.sidebar.text_input("FRED API Key", type="password", help="https://fred.stlouisfed.org/docs/api/api_key.html 에서 무료로 발급받을 수 있습니다")

# 스프레드 정의
SPREADS = {
    "EFFR-IORB": {
        "name": "EFFR - IORB",
        "series": ["EFFR", "IORB"],
        "multiplier": 1000,
        "threshold": -5,
        "description": "은행 준비금 부족, FED 대차대조표 축소 신호",
        "normal_range": "~-5bp"
    },
    "SOFR-RRP": {
        "name": "SOFR - RRP",
        "series": ["SOFR", "RRPONTSYAWARD"],
        "multiplier": 1000,
        "threshold": -10,
        "description": "MMF 역레포 이탈, 레포 시장 선호 전환",
        "normal_range": "~-10bp"
    },
    "DGS3MO-EFFR": {
        "name": "3M Treasury - EFFR",
        "series": ["DGS3MO", "EFFR"],
        "multiplier": 100,
        "threshold_min": -10,
        "threshold_max": 0,
        "description": "단기국채 프리미엄 축소, 인하 기대",
        "normal_range": "-10 ~ 0bp"
    },
    "DGS2-DGS10": {
        "name": "2Y - 10Y Yield Curve",
        "series": ["DGS2", "DGS10"],
        "multiplier": 100,
        "threshold_min": -50,
        "threshold_max": 0,
        "description": "금리커브 스티프닝, 경기 연착륙 기대",
        "normal_range": "-50 ~ 0bp"
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
    
    # 임계값 표시
    if 'threshold' in spread_info:
        fig.add_hline(
            y=spread_info['threshold'],
            line_dash="dash",
            line_color="red",
            annotation_text=f"경계선: {spread_info['threshold']}bp"
        )
    elif 'threshold_min' in spread_info and 'threshold_max' in spread_info:
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

if not api_key:
    st.warning("⚠️ FRED API 키를 왼쪽 사이드바에 입력해주세요")
    st.info("""
    FRED API 키 발급 방법:
    1. https://fred.stlouisfed.org/ 접속
    2. 무료 계정 생성
    3. API Keys 메뉴에서 키 발급
    4. 발급받은 키를 왼쪽 사이드바에 입력
    """)
else:
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
                    if 'threshold' in spread_info:
                        status = "⚠️ 주의" if latest_value < spread_info['threshold'] else "✅ 정상"
                        delta_color = "inverse" if latest_value < spread_info['threshold'] else "normal"
                    else:
                        in_range = spread_info['threshold_min'] <= latest_value <= spread_info['threshold_max']
                        status = "✅ 정상" if in_range else "⚠️ 주의"
                        delta_color = "normal" if in_range else "inverse"
                    
                    st.metric(
                        label=spread_info['name'],
                        value=f"{latest_value:.1f}bp",
                        delta=status
                    )
                    st.caption(spread_info['description'])
    
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
