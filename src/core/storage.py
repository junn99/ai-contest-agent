"""JSON 파일 기반 저장소 (PostgreSQL 대안 — DB 없이 바로 실행 가능)."""
import json
from datetime import date, datetime
from pathlib import Path

import structlog

from src.models.analysis import ContestAnalysis
from src.models.artifact import ReportArtifact
from src.models.contest import ContestInfo

logger = structlog.get_logger(__name__)


def _default_serializer(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class JSONStorage:
    """JSON 파일 기반 간단한 저장소 (PostgreSQL 대안)"""

    def __init__(self, base_dir: Path = Path("data")) -> None:
        self.base_dir = Path(base_dir)
        self.contests_file = self.base_dir / "contests.json"
        self.analyses_file = self.base_dir / "analyses.json"
        self.artifacts_file = self.base_dir / "artifacts.json"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _read_json(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("json_read_error", path=str(path), error=str(exc))
            return []

    def _write_json(self, path: Path, data: list[dict]) -> None:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=_default_serializer),
            encoding="utf-8",
        )

    # ── Contests ───────────────────────────────────────────────────────────────

    def save_contests(self, contests: list[ContestInfo]) -> int:
        """공모전 저장 (upsert by id). 저장된 신규 건수 반환."""
        existing = self._read_json(self.contests_file)
        existing_map: dict[str, dict] = {item["id"]: item for item in existing}

        new_count = 0
        for contest in contests:
            data = json.loads(
                contest.model_dump_json()
            )
            if data["id"] not in existing_map:
                new_count += 1
            existing_map[data["id"]] = data

        self._write_json(self.contests_file, list(existing_map.values()))
        logger.info("contests_saved", total=len(existing_map), new=new_count)
        return new_count

    def load_contests(self, state: str | None = None) -> list[ContestInfo]:
        """공모전 로드 (상태 필터 가능)."""
        raw = self._read_json(self.contests_file)
        contests = []
        for item in raw:
            try:
                c = ContestInfo.model_validate(item)
                if state is None or c.status == state:
                    contests.append(c)
            except Exception as exc:
                logger.warning("contest_parse_error", error=str(exc))
        return contests

    # ── Analyses ───────────────────────────────────────────────────────────────

    def save_analysis(self, analysis: ContestAnalysis) -> None:
        """분석 결과 저장 (upsert by contest_id)."""
        existing = self._read_json(self.analyses_file)
        existing_map: dict[str, dict] = {item["contest_id"]: item for item in existing}
        existing_map[analysis.contest_id] = json.loads(analysis.model_dump_json())
        self._write_json(self.analyses_file, list(existing_map.values()))
        logger.info("analysis_saved", contest_id=analysis.contest_id)

    def load_analyses(self) -> list[ContestAnalysis]:
        """모든 분석 결과 로드."""
        raw = self._read_json(self.analyses_file)
        analyses = []
        for item in raw:
            try:
                analyses.append(ContestAnalysis.model_validate(item))
            except Exception as exc:
                logger.warning("analysis_parse_error", error=str(exc))
        return analyses

    # ── Artifacts ──────────────────────────────────────────────────────────────

    def save_artifact(self, artifact: ReportArtifact) -> None:
        """보고서 아티팩트 저장 (upsert by contest_id)."""
        existing = self._read_json(self.artifacts_file)
        existing_map: dict[str, dict] = {item["contest_id"]: item for item in existing}
        existing_map[artifact.contest_id] = json.loads(artifact.model_dump_json())
        self._write_json(self.artifacts_file, list(existing_map.values()))
        logger.info("artifact_saved", contest_id=artifact.contest_id)

    def load_artifacts(self) -> list[ReportArtifact]:
        """모든 보고서 아티팩트 로드."""
        raw = self._read_json(self.artifacts_file)
        artifacts = []
        for item in raw:
            try:
                artifacts.append(ReportArtifact.model_validate(item))
            except Exception as exc:
                logger.warning("artifact_parse_error", error=str(exc))
        return artifacts

    # ── State update ───────────────────────────────────────────────────────────

    def update_state(self, contest_id: str, state: str) -> bool:
        """공모전 상태 업데이트. 해당 id가 없으면 False 반환."""
        existing = self._read_json(self.contests_file)
        updated = False
        for item in existing:
            if item.get("id") == contest_id:
                item["status"] = state
                updated = True
                break
        if updated:
            self._write_json(self.contests_file, existing)
            logger.info("contest_state_updated", contest_id=contest_id, state=state)
        else:
            logger.warning("contest_not_found_for_update", contest_id=contest_id)
        return updated
