from __future__ import annotations

from pathlib import Path

from alberto.research.delivery import html_digest, plain_text_digest


def test_plain_text_digest_removes_markdown_heading_marks() -> None:
    text = plain_text_digest("# Title\n\n## Section\n- `ref` Item\n  - Detail")

    assert "# Title" not in text
    assert "Title" in text
    assert "SECTION" in text
    assert "* `ref` Item" in text


def test_html_digest_renders_markdown_as_html() -> None:
    html = html_digest(
        "# Title\n\n## Synthesized Readings\n### Paper\n- Ref: `di_123`\n- Central argument: Useful claim",
        local_path=Path("data/digests/example.md"),
    )

    assert "<h1>Title</h1>" in html
    assert "<h2>Synthesized Readings</h2>" in html
    assert "<h3>Paper</h3>" in html
    assert "<code>di_123</code>" in html
    assert "Local copy: data/digests/example.md" in html
    assert "# Title" not in html
