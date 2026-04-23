from datetime import date, datetime
from src.models.contest import ContestInfo

AI_DATA_KEYWORDS = [
    "AI",
    "인공지능",
    "데이터",
    "빅데이터",
    "머신러닝",
    "딥러닝",
    "공공데이터",
    "데이터분석",
    "데이터 분석",
    "data",
    "자연어처리",
    "NLP",
    "컴퓨터비전",
    "챗봇",
    "LLM",
    "생성형",
    "디지털전환",
    "스마트시티",
]

ELIGIBLE_TAGS = [
    "누구나",
    "일반인",
    "재직자",
    "직장인",
    "19세이상",
    "20세이상",
    "해당자",
    "제한없음",
]

EXCLUDE_ONLY_TAGS = ["대학생", "대학교", "대학원생"]

MIN_PREPARATION_DAYS = 7


def filter_by_keywords(contest: ContestInfo) -> bool:
    """Return True if contest is relevant based on AI/data keywords."""
    text = " ".join(
        filter(
            None,
            [
                contest.title,
                contest.description or "",
                contest.category,
            ],
        )
    ).lower()

    return any(kw.lower() in text for kw in AI_DATA_KEYWORDS)


def filter_by_eligibility(contest: ContestInfo) -> bool | None:
    """
    Return True if eligible, False if definitely ineligible, None if ambiguous
    (Claude judgment needed).
    """
    tags = [t.strip() for t in contest.eligibility_tags]

    # Definitely eligible if any positive tag is present
    if any(t in ELIGIBLE_TAGS for t in tags):
        return True

    # Definitely ineligible if ONLY student-exclusive tags present and no eligible tags
    if tags and all(t in EXCLUDE_ONLY_TAGS for t in tags):
        return False

    # No tags or mixed/unknown tags — ambiguous, needs Claude
    if not tags:
        return None

    # Has tags but none matched either list — ambiguous
    return None


def filter_by_deadline(
    contest: ContestInfo,
    min_days: int = MIN_PREPARATION_DAYS,
    today: date | None = None,
) -> bool:
    """
    Return True if deadline is far enough away (>= min_days) or unknown.
    Return False if deadline has passed or too close.
    """
    if today is None:
        today = datetime.utcnow().date()

    if contest.deadline is None:
        # No deadline info — optimistically allow through
        return True

    days_remaining = (contest.deadline - today).days
    return days_remaining >= min_days


def apply_all_filters(
    contests: list[ContestInfo],
    min_preparation_days: int = MIN_PREPARATION_DAYS,
    today: date | None = None,
) -> list[ContestInfo]:
    """3-필터 체인 단일 진입점: 키워드 → 마감일 → 자격."""
    after_kw = [c for c in contests if filter_by_keywords(c)]
    after_dl = [c for c in after_kw if filter_by_deadline(c, min_days=min_preparation_days, today=today)]
    return [c for c in after_dl if filter_by_eligibility(c) is not False]
