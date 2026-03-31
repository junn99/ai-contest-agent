"""Submission guide generator using Claude CLI."""
from datetime import date

import structlog
from pydantic import BaseModel

from src.core.claude_cli import ClaudeCLI
from src.models.artifact import ReportArtifact
from src.models.contest import ContestInfo
from src.models.guide import SubmissionGuide

logger = structlog.get_logger(__name__)


class _GuideResponse(BaseModel):
    submission_method: str
    required_documents: list[str]
    file_format: str | None
    max_file_size: str | None
    additional_notes: list[str]
    checklist: list[dict]


class SubmissionGuideGenerator:
    """공모전별 제출 가이드 자동 생성"""

    def __init__(self, claude_cli: ClaudeCLI) -> None:
        self.claude = claude_cli

    async def generate(
        self, contest: ContestInfo, artifacts: list[ReportArtifact]
    ) -> SubmissionGuide:
        """Claude 1회 호출로 제출 가이드 생성."""
        log = logger.bind(contest_id=contest.id, title=contest.title)
        log.info("generating_submission_guide")

        prompt = f"""다음 공모전의 제출 가이드를 작성하세요.

제목: {contest.title}
설명: {contest.description or ""}
URL: {contest.url}
제출형식: {contest.submission_format or ""}

JSON으로 응답:
{{
  "submission_method": "온라인|이메일|우편|기타",
  "required_documents": ["보고서", "참가신청서", ...],
  "file_format": "PDF|HWP|PPT|자유",
  "max_file_size": "10MB" or null,
  "additional_notes": ["...", "..."],
  "checklist": [
    {{"item": "보고서 PDF 변환 완료", "done": false}},
    {{"item": "참가신청서 작성", "done": false}}
  ]
}}"""

        response = await self.claude.call_json(prompt, _GuideResponse)

        days_remaining: int | None = None
        if contest.deadline is not None:
            days_remaining = (contest.deadline - date.today()).days

        artifact_ids = [str(a.file_path) for a in artifacts]

        log.info("submission_guide_generated", method=response.submission_method)

        return SubmissionGuide(
            contest_id=contest.id,
            contest_title=contest.title,
            deadline=contest.deadline,
            days_remaining=days_remaining,
            submission_url=contest.url,
            submission_method=response.submission_method,
            required_documents=response.required_documents,
            file_format=response.file_format,
            max_file_size=response.max_file_size,
            additional_notes=response.additional_notes,
            checklist=response.checklist,
            artifacts=artifact_ids,
        )
