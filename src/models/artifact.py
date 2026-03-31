from pydantic import BaseModel
from datetime import datetime
from pathlib import Path


class ReportArtifact(BaseModel):
    contest_id: str
    report_type: str                 # "analysis_report" | "idea_proposal"
    file_path: Path
    markdown_path: Path
    title: str
    sections: list[str]
    data_sources: list[str]
    visualizations: list[Path]
    word_count: int
    generated_at: datetime
    generation_duration_sec: float
