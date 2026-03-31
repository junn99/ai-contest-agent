from enum import Enum


class ContestState(str, Enum):
    DISCOVERED = "discovered"
    FILTERING = "filtering"
    SKIPPED = "skipped"
    ANALYZING = "analyzing"
    GENERATING = "generating"
    RETRY = "retry"
    NEEDS_REVIEW = "needs_review"
    REVIEW_READY = "review_ready"
    SUBMITTED = "submitted"
    EXPIRED = "expired"
    TRACKING = "tracking"
    COMPLETED = "completed"
    FAILED = "failed"


class ComplianceLevel(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class ContestType(str, Enum):
    REPORT = "보고서"
    IDEA = "아이디어"
    SW_DEV = "SW개발"
    DATA_ANALYSIS = "데이터분석"
    OTHER = "기타"


class Difficulty(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
