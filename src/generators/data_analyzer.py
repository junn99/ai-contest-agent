"""CSV/Excel 데이터 기본 분석 + 시각화."""
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import pandas as pd
from pydantic import BaseModel


# 한글 폰트 설정
_FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
if Path(_FONT_PATH).exists():
    fm.fontManager.addfont(_FONT_PATH)
    matplotlib.rcParams["font.family"] = "WenQuanYi Zen Hei"
matplotlib.rcParams["axes.unicode_minus"] = False
matplotlib.use("Agg")


class DataAnalysisResult(BaseModel):
    row_count: int
    column_count: int
    columns: list[dict]  # [{"name": "col", "dtype": "int64", "missing_pct": 0.05}, ...]
    summary_stats: dict   # describe() 결과
    correlations: dict | None
    insights: list[str]   # 자동 발견된 인사이트


class DataAnalyzer:
    """CSV/Excel 데이터 기본 분석 + 시각화"""

    # 인코딩 시도 순서
    _ENCODINGS = ["utf-8", "euc-kr", "cp949"]

    def _load(self, data_path: Path) -> pd.DataFrame:
        """파일 로드 — CSV: 인코딩 순차 시도, Excel: 직접 로드."""
        suffix = data_path.suffix.lower()
        if suffix in (".xlsx", ".xls"):
            return pd.read_excel(data_path)

        last_exc: Exception = ValueError("알 수 없는 오류")
        for enc in self._ENCODINGS:
            try:
                return pd.read_csv(data_path, encoding=enc)
            except (UnicodeDecodeError, LookupError) as exc:
                last_exc = exc
        raise ValueError(f"CSV 인코딩 감지 실패 ({data_path}): {last_exc}") from last_exc

    def analyze(self, data_path: Path) -> DataAnalysisResult:
        """pandas로 CSV/Excel 로드 후 기술통계 및 인사이트 추출."""
        df = self._load(data_path)

        # 컬럼 메타
        columns: list[dict] = []
        for col in df.columns:
            missing_pct = float(df[col].isna().mean())
            columns.append(
                {"name": str(col), "dtype": str(df[col].dtype), "missing_pct": round(missing_pct, 4)}
            )

        # 기술통계
        summary_stats: dict = {}
        if not df.empty:
            try:
                raw_stats = df.describe(include="all")
                summary_stats = raw_stats.fillna("").astype(str).to_dict()
            except Exception:
                summary_stats = {}

        # 상관관계 (수치형 컬럼 2개 이상)
        correlations: dict | None = None
        num_cols = df.select_dtypes(include="number").columns.tolist()
        if len(num_cols) >= 2:
            try:
                corr_df = df[num_cols].corr()
                correlations = corr_df.fillna("").astype(str).to_dict()
            except Exception:
                correlations = None

        # 인사이트 자동 추출
        insights: list[str] = []
        for col_info in columns:
            if col_info["missing_pct"] >= 0.3:
                pct = int(col_info["missing_pct"] * 100)
                insights.append(f"{col_info['name']} 컬럼의 결측치가 {pct}% 이상입니다.")
        if df.empty:
            insights.append("데이터가 비어 있습니다.")
        if len(num_cols) == 0 and not df.empty:
            insights.append("수치형 컬럼이 없어 통계 분석이 제한됩니다.")

        return DataAnalysisResult(
            row_count=len(df),
            column_count=len(df.columns),
            columns=columns,
            summary_stats=summary_stats,
            correlations=correlations,
            insights=insights,
        )

    def create_visualizations(
        self, data_path: Path, output_dir: Path, contest_title: str
    ) -> list[Path]:
        """matplotlib 차트 생성 (최대 4개)."""
        output_dir.mkdir(parents=True, exist_ok=True)
        df = self._load(data_path)
        if df.empty:
            return []

        num_cols = df.select_dtypes(include="number").columns.tolist()
        cat_cols = df.select_dtypes(include=["str", "object", "category"]).columns.tolist()

        # 날짜/시간 컬럼 감지
        date_cols = [
            c for c in df.columns
            if "date" in c.lower() or "time" in c.lower() or "년" in c or "월" in c
        ]

        paths: list[Path] = []

        # 1) 수치형 상위 3개 컬럼 bar chart
        if num_cols:
            top_num = num_cols[:3]
            fig, ax = plt.subplots(figsize=(8, 5))
            df[top_num].mean().plot(kind="bar", ax=ax)
            ax.set_title(f"{contest_title} - 주요 수치 평균")
            ax.set_ylabel("평균값")
            ax.tick_params(axis="x", rotation=30)
            fig.tight_layout()
            out = output_dir / "bar_chart.png"
            fig.savefig(out, dpi=100)
            plt.close(fig)
            paths.append(out)

        # 2) 상관관계 heatmap (수치형 5개 이상)
        if len(num_cols) >= 5:
            import numpy as np
            corr = df[num_cols].corr()
            fig, ax = plt.subplots(figsize=(8, 6))
            im = ax.imshow(corr.values, cmap="coolwarm", vmin=-1, vmax=1)
            fig.colorbar(im, ax=ax)
            ax.set_xticks(range(len(corr.columns)))
            ax.set_yticks(range(len(corr.columns)))
            ax.set_xticklabels(corr.columns, rotation=45, ha="right")
            ax.set_yticklabels(corr.columns)
            ax.set_title(f"{contest_title} - 상관관계 히트맵")
            fig.tight_layout()
            out = output_dir / "heatmap.png"
            fig.savefig(out, dpi=100)
            plt.close(fig)
            paths.append(out)

        # 3) 시계열 line chart
        if date_cols and num_cols:
            date_col = date_cols[0]
            num_col = num_cols[0]
            try:
                tmp = df[[date_col, num_col]].dropna().copy()
                tmp[date_col] = pd.to_datetime(tmp[date_col], errors="coerce")
                tmp = tmp.dropna(subset=[date_col]).sort_values(date_col)
                if len(tmp) >= 2:
                    fig, ax = plt.subplots(figsize=(10, 4))
                    ax.plot(tmp[date_col], tmp[num_col], marker="o", markersize=3)
                    ax.set_title(f"{contest_title} - 시계열 추이")
                    ax.set_xlabel(date_col)
                    ax.set_ylabel(num_col)
                    fig.autofmt_xdate()
                    fig.tight_layout()
                    out = output_dir / "timeseries.png"
                    fig.savefig(out, dpi=100)
                    plt.close(fig)
                    paths.append(out)
            except Exception:
                pass

        # 4) 카테고리형 pie chart
        if cat_cols and len(paths) < 4:
            cat_col = cat_cols[0]
            vc = df[cat_col].value_counts().head(8)
            if len(vc) >= 2:
                fig, ax = plt.subplots(figsize=(7, 7))
                ax.pie(vc.values, labels=vc.index, autopct="%1.1f%%", startangle=140)
                ax.set_title(f"{contest_title} - {cat_col} 분포")
                fig.tight_layout()
                out = output_dir / "pie_chart.png"
                fig.savefig(out, dpi=100)
                plt.close(fig)
                paths.append(out)

        return paths[:4]
