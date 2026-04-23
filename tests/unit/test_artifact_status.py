"""Unit tests for ReportArtifact.status field."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from src.models.artifact import ReportArtifact


def make_artifact(**overrides) -> ReportArtifact:
    defaults = dict(
        contest_id="ck_test_001",
        report_type="analysis_report",
        file_path=Path("/tmp/report.pdf"),
        markdown_path=Path("/tmp/report.md"),
        title="테스트 보고서",
        sections=["요약", "분석"],
        data_sources=["국가통계포털"],
        visualizations=[],
        word_count=1000,
        generated_at=datetime(2026, 4, 20),
        generation_duration_sec=30.0,
    )
    defaults.update(overrides)
    return ReportArtifact(**defaults)


class TestReportArtifactStatus:
    def test_default_status_is_done(self):
        artifact = make_artifact()
        assert artifact.status == "done"

    def test_explicit_status_pending(self):
        artifact = make_artifact(status="pending")
        assert artifact.status == "pending"

    def test_explicit_status_running(self):
        artifact = make_artifact(status="running")
        assert artifact.status == "running"

    def test_explicit_status_failed(self):
        artifact = make_artifact(status="failed")
        assert artifact.status == "failed"

    def test_invalid_status_raises(self):
        with pytest.raises(Exception):
            make_artifact(status="unknown")

    def test_json_roundtrip_with_status(self):
        artifact = make_artifact(status="running")
        restored = ReportArtifact.model_validate_json(artifact.model_dump_json())
        assert restored.status == "running"

    def test_existing_record_without_status_defaults_to_done(self):
        """Records loaded from JSON without a status field should default to 'done'."""
        data = {
            "contest_id": "ck_test_001",
            "report_type": "analysis_report",
            "file_path": "/tmp/report.pdf",
            "markdown_path": "/tmp/report.md",
            "title": "테스트 보고서",
            "sections": ["요약"],
            "data_sources": [],
            "visualizations": [],
            "word_count": 500,
            "generated_at": "2026-04-20T00:00:00",
            "generation_duration_sec": 10.0,
        }
        artifact = ReportArtifact.model_validate(data)
        assert artifact.status == "done"
