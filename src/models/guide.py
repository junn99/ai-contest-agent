from pydantic import BaseModel
from datetime import date


class SubmissionGuide(BaseModel):
    contest_id: str
    contest_title: str
    deadline: date | None
    days_remaining: int | None
    submission_url: str
    submission_method: str
    required_documents: list[str]
    file_format: str | None
    max_file_size: str | None
    additional_notes: list[str]
    checklist: list[dict]
    artifacts: list[str]             # artifact IDs
