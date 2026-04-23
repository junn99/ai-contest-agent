"""tests/unit/test_views.py — views.py 포맷터 단위 테스트."""
import pytest
from datetime import date, datetime
from pathlib import Path

from src.models.contest import ContestInfo
from src.models.analysis import ContestAnalysis
from src.models.artifact import ReportArtifact
from src.notifiers.views import (
    MAX_CAPTION_LEN,
    MAX_MESSAGE_LEN,
    WEBAPP_URL,
    build_navigation_keyboard,
    build_webapp_keyboard,
    format_contest_card,
    format_deadline_pin,
    format_digest_header,
    format_done,
    format_failed,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _contest(d_day: int | None = 10, contest_id: str = "ck_test001", url: str = "https://example.com") -> ContestInfo:
    return ContestInfo(
        id=contest_id,
        platform="contestkorea",
        title="테스트 공모전 <특수문자>",
        url=url,
        organizer="주최사 & Co",
        deadline=date(2026, 5, 1),
        start_date=None,
        prize="100만원",
        prize_amount=1_000_000,
        eligibility_raw="대학생",
        eligibility_tags=["대학생"],
        submission_format=None,
        category="아이디어",
        description=None,
        status="접수중",
        d_day=d_day,
        scraped_at=datetime(2026, 4, 20),
    )


def _analysis(contest_id: str = "ck_test001", required_deliverables: list[str] | None = None) -> ContestAnalysis:
    return ContestAnalysis(
        contest_id=contest_id,
        contest_type="아이디어",
        difficulty="MEDIUM",
        is_eligible=True,
        eligibility_reason="대학생 자격 충족",
        roi_score=7.5,
        roi_breakdown={"prize": 3.5, "difficulty": 2.0, "relevance": 2.0},
        required_deliverables=required_deliverables if required_deliverables is not None else ["기획서"],
        suggested_approach="AI 기반 아이디어 도출",
        relevant_public_data=[],
        keywords=["AI", "공모전"],
        ai_restriction=None,
        analyzed_at=datetime(2026, 4, 20),
    )


def _artifact(
    contest_id: str = "ck_test001",
    status: str = "done",
) -> ReportArtifact:
    return ReportArtifact(
        contest_id=contest_id,
        report_type="analysis_report",
        file_path=Path("/tmp/report.pdf"),
        markdown_path=Path("/tmp/report.md"),
        title="테스트 보고서",
        sections=["요약", "분석"],
        data_sources=[],
        visualizations=[],
        word_count=1500,
        generated_at=datetime(2026, 4, 20),
        generation_duration_sec=30.0,
        status=status,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# build_navigation_keyboard
# ---------------------------------------------------------------------------

class TestBuildNavigationKeyboard:
    def test_done_artifact_returns_pdf_and_guide(self):
        kb = build_navigation_keyboard("ck_001", "https://example.com", _artifact(status="done"), d_day=10)
        assert kb is not None
        # 첫 행: PDF + 가이드
        row = kb[0]
        data = {btn["callback_data"] for btn in row}
        assert "pdf:ck_001" in data
        assert "gd:ck_001" in data

    def test_url_button_present_when_url_given(self):
        kb = build_navigation_keyboard("ck_001", "https://example.com", None, d_day=10)
        assert kb is not None
        flat = [btn for row in kb for btn in row]
        url_btns = [btn for btn in flat if btn.get("url") == "https://example.com"]
        assert len(url_btns) == 1
        assert url_btns[0]["text"] == "🔗 원문 보기"

    def test_url_button_absent_when_url_none(self):
        kb = build_navigation_keyboard("ck_001", None, None, d_day=10)
        assert kb is None

    def test_url_button_always_present_with_done_artifact(self):
        kb = build_navigation_keyboard("ck_001", "https://example.com", _artifact(status="done"), d_day=10)
        assert kb is not None
        flat = [btn for row in kb for btn in row]
        url_btns = [btn for btn in flat if "url" in btn]
        assert len(url_btns) == 1

    def test_no_gen_callback_button_dday_3_no_artifact(self):
        # Fix 3: D-3 미생성은 [⚡ 지금 생성] callback_data 버튼 없어야 함
        kb = build_navigation_keyboard("ck_001", "https://example.com", None, d_day=3)
        flat = [btn for row in kb for btn in row] if kb else []
        gen_btns = [btn for btn in flat if btn.get("callback_data", "").startswith("gen:")]
        assert len(gen_btns) == 0

    def test_no_gen_callback_button_dday_2_no_artifact(self):
        kb = build_navigation_keyboard("ck_001", "https://example.com", None, d_day=2)
        flat = [btn for row in kb for btn in row] if kb else []
        gen_btns = [btn for btn in flat if btn.get("callback_data", "").startswith("gen:")]
        assert len(gen_btns) == 0

    def test_failed_artifact_dday_2_no_gen_button(self):
        # Fix 3: failed artifact + D-2도 gen callback_data 없음
        kb = build_navigation_keyboard("ck_001", "https://example.com", _artifact(status="failed"), d_day=2)
        flat = [btn for row in kb for btn in row] if kb else []
        gen_btns = [btn for btn in flat if btn.get("callback_data", "").startswith("gen:")]
        assert len(gen_btns) == 0

    def test_running_artifact_no_gen_button(self):
        # running 상태: done 아니므로 PDF/가이드 없음. url만 있으면 됨
        kb = build_navigation_keyboard("ck_001", "https://example.com", _artifact(status="running"), d_day=4)
        flat = [btn for row in kb for btn in row] if kb else []
        gen_btns = [btn for btn in flat if btn.get("callback_data", "").startswith("gen:")]
        assert len(gen_btns) == 0

    def test_done_artifact_overrides_dday_check(self):
        # done이면 D-1이어도 PDF/가이드 + url (gen 없음)
        kb = build_navigation_keyboard("ck_001", "https://example.com", _artifact(status="done"), d_day=1)
        assert kb is not None
        flat = [btn for row in kb for btn in row]
        data = {btn.get("callback_data", "") for btn in flat}
        assert "pdf:ck_001" in data
        assert "gen:ck_001" not in data

    def test_no_artifact_no_dday_no_url_returns_none(self):
        kb = build_navigation_keyboard("ck_001", None, None, d_day=None)
        assert kb is None

    def test_no_artifact_no_dday_with_url_returns_url_button(self):
        kb = build_navigation_keyboard("ck_001", "https://example.com", None, d_day=None)
        assert kb is not None
        flat = [btn for row in kb for btn in row]
        assert any(btn.get("url") == "https://example.com" for btn in flat)


# ---------------------------------------------------------------------------
# format_contest_card
# ---------------------------------------------------------------------------

class TestFormatContestCard:
    def test_html_escape_title_and_organizer(self):
        c = _contest()
        text, _ = format_contest_card(c, _analysis(), None)
        assert "&lt;특수문자&gt;" in text
        assert "&amp;" in text

    def test_text_within_max_length(self):
        c = _contest()
        text, _ = format_contest_card(c, _analysis(), None)
        assert len(text) <= MAX_MESSAGE_LEN

    def test_reply_markup_present_when_url_given(self):
        # Fix 1: url이 있으면 markup 항상 존재 (D-10, no artifact)
        c = _contest(d_day=10, url="https://example.com")
        _, markup = format_contest_card(c, _analysis(), None)
        assert markup is not None
        assert "inline_keyboard" in markup

    def test_reply_markup_present_when_done(self):
        c = _contest(d_day=10)
        _, markup = format_contest_card(c, _analysis(), _artifact(status="done"))
        assert markup is not None
        assert "inline_keyboard" in markup

    def test_url_button_in_card(self):
        # Fix 1: 원문 버튼 항상 포함
        c = _contest(d_day=10, url="https://contest.example.com")
        _, markup = format_contest_card(c, _analysis(), None)
        assert markup is not None
        flat = [btn for row in markup["inline_keyboard"] for btn in row]
        url_btns = [btn for btn in flat if btn.get("url") == "https://contest.example.com"]
        assert len(url_btns) == 1

    def test_no_gen_callback_button_dday_2_no_artifact(self):
        # Fix 3: D-2 미생성 → callback_data gen: 버튼 없음
        c = _contest(d_day=2)
        text, markup = format_contest_card(c, _analysis(), None)
        flat = [btn for row in markup["inline_keyboard"] for btn in markup["inline_keyboard"]] if markup else []
        # 카드 텍스트에 안내 텍스트 포함 여부 확인
        assert "마감 임박" in text or "⚡" in text
        # gen: callback_data 버튼 없음
        if markup:
            all_btns = [btn for row in markup["inline_keyboard"] for btn in row]
            gen_btns = [btn for btn in all_btns if btn.get("callback_data", "").startswith("gen:")]
            assert len(gen_btns) == 0

    def test_dday_2_no_artifact_urgency_text_in_card(self):
        # Fix 3: D-2 미생성이면 카드 본문에 안내 텍스트
        c = _contest(d_day=2)
        text, _ = format_contest_card(c, _analysis(), None)
        assert "⚡" in text
        assert "generate" in text

    def test_dday_4_no_artifact_no_urgency_text(self):
        # D-4는 안내 텍스트 없음
        c = _contest(d_day=4)
        text, _ = format_contest_card(c, _analysis(), None)
        assert "generate" not in text

    def test_required_deliverables_in_card(self):
        # Fix 2: required_deliverables 카드에 표시
        c = _contest()
        a = _analysis(required_deliverables=["기획서", "PPT", "데모영상"])
        text, _ = format_contest_card(c, a, None)
        assert "📦 제출물:" in text
        assert "기획서" in text
        assert "PPT" in text

    def test_required_deliverables_max_5(self):
        # Fix 2: 최대 5개만 표시
        c = _contest()
        a = _analysis(required_deliverables=["A", "B", "C", "D", "E", "F", "G"])
        text, _ = format_contest_card(c, a, None)
        assert "📦 제출물:" in text
        assert "F" not in text
        assert "G" not in text

    def test_required_deliverables_empty_not_shown(self):
        # Fix 2: 비어있으면 제출물 라인 없음
        c = _contest()
        a = _analysis(required_deliverables=[])
        text, _ = format_contest_card(c, a, None)
        assert "📦 제출물:" not in text

    def test_deadline_single_line(self):
        # Fix 4: 마감 한 줄 통합 (📅 마감: D-10 (2026-05-01))
        c = _contest(d_day=10)
        text, _ = format_contest_card(c, _analysis(), None)
        assert "📅 마감:" in text
        # 두 줄로 분리된 "📆" 없어야 함
        assert "📆" not in text

    def test_deadline_contains_date_and_dlabel(self):
        # Fix 4: d_label과 날짜가 같은 줄에
        c = _contest(d_day=10)
        text, _ = format_contest_card(c, _analysis(), None)
        # "D-10"과 날짜가 동일 줄에 있는지 확인
        for line in text.splitlines():
            if "📅 마감:" in line:
                assert "D-10" in line
                assert "2026-05-01" in line
                break
        else:
            pytest.fail("📅 마감: 라인 없음")

    def test_organizer_truncated_at_40(self):
        # Fix 5: organizer 40자 제한
        long_org = "가" * 50
        c = _contest()
        c = c.model_copy(update={"organizer": long_org})
        text, _ = format_contest_card(c, _analysis(), None)
        # 40자 초과 organizer는 truncate됨
        assert "가" * 41 not in text

    def test_roi_score_11_clamped_to_10_stars(self):
        # Fix 6: roi_score 11.0 → 별 10개
        c = _contest()
        a = _analysis()
        a = a.model_copy(update={"roi_score": 11.0})
        text, _ = format_contest_card(c, a, None)
        assert "★" * 10 in text
        assert "★" * 11 not in text

    def test_roi_score_negative_clamped_to_0_stars(self):
        # Fix 6: roi_score -1.0 → 별 0개
        c = _contest()
        a = _analysis()
        a = a.model_copy(update={"roi_score": -1.0})
        text, _ = format_contest_card(c, a, None)
        assert "★" not in text
        assert "☆" * 10 in text

    def test_urgency_badge_in_header_for_critical(self):
        c = _contest(d_day=1)
        text, _ = format_contest_card(c, _analysis(), None)
        assert "🚨" in text

    def test_no_urgency_badge_for_dday_15(self):
        c = _contest(d_day=15)
        text, _ = format_contest_card(c, _analysis(), None)
        assert "🚨" not in text
        assert "⚠️" not in text
        assert "ℹ️" not in text

    def test_roi_score_present(self):
        text, _ = format_contest_card(_contest(), _analysis(), None)
        assert "7.5" in text

    def test_long_text_truncated(self):
        long_title = "가" * 5000
        c = _contest()
        c = c.model_copy(update={"title": long_title})
        text, _ = format_contest_card(c, _analysis(), None)
        assert len(text) <= MAX_MESSAGE_LEN


# ---------------------------------------------------------------------------
# format_digest_header
# ---------------------------------------------------------------------------

class TestFormatDigestHeader:
    def test_contains_counts(self):
        text = format_digest_header(total=10, imminent=3, done_reports=7, total_reports=10)
        assert "10" in text
        assert "3" in text
        assert "7" in text

    def test_within_max_length(self):
        text = format_digest_header(100, 50, 80, 100)
        assert len(text) <= MAX_MESSAGE_LEN


# ---------------------------------------------------------------------------
# format_deadline_pin
# ---------------------------------------------------------------------------

class TestFormatDeadlinePin:
    def test_imminent_contests_listed(self):
        c1 = _contest(d_day=1, contest_id="ck_a")
        c2 = _contest(d_day=5, contest_id="ck_b")
        c3 = _contest(d_day=15, contest_id="ck_c")  # excluded
        text = format_deadline_pin([c1, c2, c3], [_analysis("ck_a"), _analysis("ck_b"), _analysis("ck_c")])
        assert "D-1" in text
        assert "D-5" in text
        # D-15 is beyond D-7 threshold
        assert "D-15" not in text

    def test_empty_imminent(self):
        c = _contest(d_day=20)
        text = format_deadline_pin([c], [])
        assert "없음" in text

    def test_html_escape_in_pin(self):
        c = _contest(d_day=3)
        c = c.model_copy(update={"title": "<script>xss</script>"})
        text = format_deadline_pin([c], [])
        assert "<script>" not in text
        assert "&lt;script&gt;" in text

    def test_within_max_length(self):
        contests = [_contest(d_day=i % 7 + 1, contest_id=f"ck_{i:03d}") for i in range(50)]
        text = format_deadline_pin(contests, [])
        assert len(text) <= MAX_MESSAGE_LEN


# ---------------------------------------------------------------------------
# format_done
# ---------------------------------------------------------------------------

class TestFormatDone:
    def test_contains_title_and_word_count(self):
        text = format_done(_artifact())
        assert "테스트 보고서" in text
        assert "1,500" in text

    def test_within_caption_limit(self):
        text = format_done(_artifact())
        assert len(text) <= MAX_CAPTION_LEN


# ---------------------------------------------------------------------------
# format_failed
# ---------------------------------------------------------------------------

class TestFormatFailed:
    def test_contains_contest_id_and_error(self):
        text = format_failed("ck_001", "Claude CLI 오류")
        assert "ck_001" in text
        assert "Claude CLI 오류" in text

    def test_html_escape_error(self):
        text = format_failed("ck_001", "<error> & fail")
        assert "<error>" not in text
        assert "&lt;error&gt;" in text

    def test_within_max_length(self):
        text = format_failed("ck_001", "x" * 5000)
        assert len(text) <= MAX_MESSAGE_LEN


# ---------------------------------------------------------------------------
# build_webapp_keyboard
# ---------------------------------------------------------------------------

class TestBuildWebappKeyboard:
    def test_default_url_matches_webapp_url_constant(self):
        markup = build_webapp_keyboard()
        assert "inline_keyboard" in markup
        flat = [btn for row in markup["inline_keyboard"] for btn in row]
        assert len(flat) == 1
        btn = flat[0]
        assert btn["text"] == "📊 대시보드 열기"
        assert "web_app" in btn
        assert btn["web_app"]["url"] == WEBAPP_URL

    def test_custom_url_override(self):
        custom = "https://custom.example.com/"
        markup = build_webapp_keyboard(webapp_url=custom)
        flat = [btn for row in markup["inline_keyboard"] for btn in row]
        assert flat[0]["web_app"]["url"] == custom

    def test_markup_structure_valid(self):
        markup = build_webapp_keyboard()
        assert isinstance(markup["inline_keyboard"], list)
        assert isinstance(markup["inline_keyboard"][0], list)

    def test_webapp_url_constant_is_nonempty(self):
        assert WEBAPP_URL and WEBAPP_URL.startswith("http")
