"""Markdown → HTML → PDF 변환 엔진."""
from pathlib import Path

import markdown as md_lib

# Workaround: wqy-zenhei.ttc contains Unicode range bit 123 which exceeds
# fontTools' O_S_2f_2 validator range of 0-122. Patch setUnicodeRanges to
# silently drop out-of-range bits instead of raising ValueError.
try:
    from fontTools.ttLib.tables import O_S_2f_2 as _os2_mod

    _orig_set_unicode_ranges = _os2_mod.table_O_S_2f_2.setUnicodeRanges

    def _patched_set_unicode_ranges(self, value):
        _orig_set_unicode_ranges(self, {b for b in value if 0 <= b <= 122})

    _os2_mod.table_O_S_2f_2.setUnicodeRanges = _patched_set_unicode_ranges
except Exception:
    pass


class PDFEngine:
    """Markdown → HTML → PDF 변환"""

    def convert(
        self,
        markdown_path: Path,
        output_path: Path,
        title: str,
        images: list[Path] | None = None,
    ) -> Path:
        """
        1. Markdown → HTML (markdown 라이브러리)
        2. HTML에 CSS 스타일 적용 (A4, 여백, 한글 폰트, 페이지번호)
        3. 이미지 삽입 (시각화 차트)
        4. weasyprint로 PDF 생성
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        markdown_text = markdown_path.read_text(encoding="utf-8")
        body_html = md_lib.markdown(
            markdown_text,
            extensions=["tables", "fenced_code", "nl2br"],
        )

        # 이미지 블록을 HTML에 추가 (이미 마크다운에 없는 경우를 위한 보조)
        extra_images_html = ""
        if images:
            for img_path in images:
                extra_images_html += (
                    f'<p><img src="{img_path.resolve().as_uri()}" '
                    f'alt="{img_path.stem}"></p>\n'
                )

        html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
{self._get_css()}
</style>
</head>
<body>
{body_html}
{extra_images_html}
</body>
</html>"""

        html_path = output_path.with_suffix(".html")
        html_path.write_text(html, encoding="utf-8")

        from weasyprint import HTML as WeasyprintHTML

        WeasyprintHTML(string=html, base_url=str(markdown_path.parent)).write_pdf(
            str(output_path)
        )

        return output_path

    def _get_css(self) -> str:
        """보고서용 CSS 스타일"""
        return (
            '@page { size: A4; margin: 2.5cm; @bottom-center { content: counter(page); } }\n'
            'body { font-family: "WenQuanYi Zen Hei", sans-serif; font-size: 11pt; '
            "line-height: 1.8; color: #333; }\n"
            "h1 { font-size: 20pt; color: #1a1a2e; border-bottom: 2px solid #1a1a2e; "
            "padding-bottom: 8px; }\n"
            "h2 { font-size: 15pt; color: #16213e; margin-top: 24px; }\n"
            "h3 { font-size: 13pt; color: #0f3460; }\n"
            "table { border-collapse: collapse; width: 100%; margin: 12px 0; }\n"
            "th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }\n"
            "th { background-color: #f0f0f0; }\n"
            "img { max-width: 100%; margin: 12px 0; }\n"
            ".insight { background: #f8f9fa; border-left: 4px solid #1a1a2e; "
            "padding: 12px; margin: 12px 0; }"
        )
