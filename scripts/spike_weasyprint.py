#!/usr/bin/env python3
"""
Spike: weasyprint PDF 생성 테스트
- weasyprint 설치 확인 (없으면 pip install)
- 한글 포함 Markdown -> HTML -> PDF 변환
- 한글 폰트(NanumGothic 등) 렌더링 확인
- 결과 PDF를 data/spike_report.pdf 에 저장
"""

import subprocess
import sys
import os

OUTPUT_PDF = "/home/jun99/claude/infoke/data/spike_report.pdf"
OUTPUT_HTML = "/home/jun99/claude/infoke/data/spike_report.html"


def ensure_weasyprint():
    """weasyprint 가 설치되어 있는지 확인하고 없으면 설치."""
    try:
        import weasyprint
        print(f"weasyprint already installed: {weasyprint.__version__}")
        return True, weasyprint.__version__
    except ImportError:
        print("weasyprint not found. Installing via pip...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "weasyprint"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print("weasyprint installed successfully.")
            try:
                import weasyprint
                return True, weasyprint.__version__
            except ImportError as e:
                return False, f"Import failed after install: {e}"
        else:
            print(f"pip install failed:\n{result.stderr[:500]}")
            return False, result.stderr


def find_korean_font() -> str | None:
    """시스템에서 한글 폰트 경로를 찾는다.
    unifont_jp.otf 는 fontTools Unicode range 버그(bit 123)가 있어 제외.
    """
    # 알려진 안전한 후보 (우선순위 순)
    candidates = [
        # NanumGothic
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
        # Noto CJK
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJKkr-Regular.otf",
        # UnBatang (Ubuntu)
        "/usr/share/fonts/truetype/unfonts-core/UnBatang.ttf",
        "/usr/share/fonts/truetype/unfonts-core/UnDotum.ttf",
        # WenQuanYi (CJK, Korean 포함)
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            print(f"Korean font found: {path}")
            return path
    # fc-list 로 검색 (unifont 제외)
    try:
        result = subprocess.run(
            ["fc-list", ":lang=ko"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().split("\n")
        for line in lines:
            parts = line.split(":")
            if parts:
                font_path = parts[0].strip()
                # unifont_jp 는 fontTools 버그로 제외
                if "unifont" in font_path.lower():
                    continue
                if os.path.exists(font_path):
                    print(f"Korean font found via fc-list: {font_path}")
                    return font_path
    except Exception:
        pass
    print("No Korean font found on system (unifont excluded). Using system default.")
    return None


def build_html(font_path: str | None) -> str:
    """한글 포함 HTML 문서를 생성."""
    if font_path:
        font_face = f"""
        @font-face {{
            font-family: 'KoreanFont';
            src: url('file://{font_path}');
        }}
        body {{ font-family: 'KoreanFont', 'Nanum Gothic', 'NanumGothic', sans-serif; }}
        """
        font_note = f"폰트 경로: {font_path}"
    else:
        font_face = "body { font-family: sans-serif; }"
        font_note = "시스템 한글 폰트 없음 - 기본 폰트 사용"

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <title>infoke 스파이크 보고서</title>
  <style>
    {font_face}
    body {{
      margin: 40px;
      line-height: 1.8;
      color: #333;
    }}
    h1 {{ color: #1a1a2e; border-bottom: 2px solid #e94560; padding-bottom: 8px; }}
    h2 {{ color: #16213e; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 16px 0;
    }}
    th, td {{
      border: 1px solid #ccc;
      padding: 8px 12px;
      text-align: left;
    }}
    th {{ background: #f0f0f0; }}
    .badge-pass {{ color: green; font-weight: bold; }}
    .badge-fail {{ color: red; font-weight: bold; }}
    .meta {{ font-size: 0.85em; color: #888; }}
  </style>
</head>
<body>
  <h1>infoke Phase 0 스파이크 보고서</h1>
  <p class="meta">생성일: 2026-03-30 &nbsp;|&nbsp; {font_note}</p>

  <h2>1. 개요</h2>
  <p>
    이 문서는 infoke 프로젝트의 Phase 0 스파이크 결과를 요약합니다.
    한글 렌더링 및 weasyprint PDF 생성 가능 여부를 검증합니다.
  </p>

  <h2>2. 테스트 항목</h2>
  <table>
    <thead>
      <tr><th>항목</th><th>도구</th><th>결과</th></tr>
    </thead>
    <tbody>
      <tr>
        <td>Claude CLI subprocess 호출</td>
        <td>Python subprocess</td>
        <td class="badge-pass">검증 중</td>
      </tr>
      <tr>
        <td>JSON 응답 파싱</td>
        <td>json.loads()</td>
        <td class="badge-pass">검증 중</td>
      </tr>
      <tr>
        <td>weasyprint PDF 생성</td>
        <td>weasyprint</td>
        <td class="badge-pass">성공</td>
      </tr>
      <tr>
        <td>한글 폰트 렌더링</td>
        <td>@font-face / fc-list</td>
        <td>{'폰트 로드됨' if font_path else '기본 폰트'}</td>
      </tr>
    </tbody>
  </table>

  <h2>3. 한글 샘플 텍스트</h2>
  <p>
    가나다라마바사아자차카타파하 — 한글 자음/모음 전체 테스트<br>
    대한민국 서울특별시 강남구 테헤란로 123<br>
    안녕하세요! infoke 프로젝트에 오신 것을 환영합니다.<br>
    이 PDF는 weasyprint로 생성되었습니다.
  </p>

  <h2>4. 숫자 및 혼합 텍스트</h2>
  <p>
    점수: 8.5 / 10.0 &nbsp;|&nbsp; 정확도: 95.3% &nbsp;|&nbsp; 평균: 7.82<br>
    키워드: AI 분석, 문서 생성, 자동화 파이프라인, 품질 검수
  </p>

  <h2>5. 결론</h2>
  <p>
    weasyprint를 사용하여 한글을 포함한 PDF 보고서 생성이 <strong>가능</strong>합니다.
    Claude CLI subprocess 호출 결과는 <code>spike_claude_cli.json</code>을 참조하세요.
  </p>

  <p class="meta">— 자동 생성된 스파이크 보고서 —</p>
</body>
</html>
"""
    return html


def main():
    print("=== weasyprint PDF Spike ===")

    # 1. weasyprint 설치 확인
    installed, version_or_err = ensure_weasyprint()
    if not installed:
        print(f"FAILED to install weasyprint: {version_or_err}")
        sys.exit(1)

    # 2. 한글 폰트 탐색
    font_path = find_korean_font()

    # 3. HTML 생성
    html_content = build_html(font_path)
    os.makedirs(os.path.dirname(OUTPUT_PDF), exist_ok=True)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"HTML written to: {OUTPUT_HTML}")

    # 4. weasyprint로 PDF 생성
    print("Generating PDF with weasyprint...")
    try:
        import weasyprint
        doc = weasyprint.HTML(filename=OUTPUT_HTML)
        doc.write_pdf(OUTPUT_PDF)

        size_kb = os.path.getsize(OUTPUT_PDF) / 1024
        print(f"PDF generated successfully: {OUTPUT_PDF}")
        print(f"PDF size: {size_kb:.1f} KB")
        print(f"Korean font used: {font_path or 'system default'}")
        print("RESULT: PASS")
    except Exception as e:
        print(f"weasyprint PDF generation failed: {e}")
        import traceback
        traceback.print_exc()
        print("RESULT: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
