from pydantic import BaseModel
from datetime import date, datetime


class ContestInfo(BaseModel):
    id: str                          # "ck_202603180064"
    platform: str                    # "contestkorea" | "wevity"
    title: str
    url: str
    organizer: str
    deadline: date | None
    start_date: date | None
    prize: str | None
    prize_amount: int | None         # KRW
    eligibility_raw: str
    eligibility_tags: list[str]      # ["일반인", "대학생", ...]
    submission_format: str | None
    category: str
    description: str | None
    status: str                      # "접수중" | "접수예정" | "마감"
    d_day: int | None
    scraped_at: datetime
