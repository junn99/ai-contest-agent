from pydantic import BaseModel
from datetime import datetime


class ContestAnalysis(BaseModel):
    contest_id: str
    contest_type: str                # "보고서" | "아이디어" | "SW개발" | "데이터분석" | "기타"
    difficulty: str                  # "LOW" | "MEDIUM" | "HIGH"
    is_eligible: bool
    eligibility_reason: str
    roi_score: float                 # 0.0 ~ 10.0
    roi_breakdown: dict              # {"prize": 3.5, "difficulty": 3.0, ...}
    required_deliverables: list[str]
    suggested_approach: str
    relevant_public_data: list[str]
    keywords: list[str]
    ai_restriction: str | None       # "없음" | "AI 활용 금지" | "AI 활용 권장" 등
    analyzed_at: datetime
