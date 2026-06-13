"""
pdf_export.py — turn the app's print-ready HTML sheets into real PDFs.

Engine ladder: WeasyPrint when installed (best CSS, but needs GTK/Pango on
Windows so it's strictly optional), else xhtml2pdf (pure pip — the default
engine on this laptop), else None and callers fall back to the HTML download.
The HTML builders (helpers/scout.py, helpers/reports.py,
helpers/matchup_sheet.py) are written table-based specifically so xhtml2pdf
renders them faithfully — it ignores flexbox. Streamlit-free.
"""
from __future__ import annotations

import io


def html_to_pdf(html: str) -> bytes | None:
    """Render an HTML document to PDF bytes, or None when no engine works."""
    try:
        from weasyprint import HTML
        return HTML(string=html).write_pdf()
    except Exception:
        pass
    try:
        from xhtml2pdf import pisa
        buf = io.BytesIO()
        result = pisa.CreatePDF(html, dest=buf, encoding="utf-8")
        if not result.err:
            return buf.getvalue()
    except Exception:
        pass
    return None
