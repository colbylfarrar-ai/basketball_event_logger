"""A report nobody clicked must not be built.

Six printable exports are constructed as ARGUMENTS to
`ui.pdf_or_html_download`, so the report is built on every render whether or not
anyone downloads it. Python evaluates the argument before the function is
entered, so no amount of laziness inside the function can help — the call site
has already paid.

The cost is not theoretical. `court_png._light_court` takes ~43 s the first time
it is touched in a process (matplotlib import, backend init, font cache), and
four of the six paths reach it. That is 43 of the Players page's 56.6 s cold,
for a figure nobody looked at, on a page that already draws an interactive
Plotly court.

The fix is to let `html_doc` be a zero-arg CALLABLE. When it is, the function
renders a "Prepare" button and builds nothing until a coach asks for it. A
string still works exactly as before — five of the six call sites are inside
paid or expander-gated blocks and the sixth is a hot page, so the migration is
per-site, not a flag day.

`fp` is the staleness guard. A prepared document is held in session state so the
download buttons survive the rerun that a download click causes; without a
fingerprint, changing the recap's section multiselect would hand the coach the
document they prepared before the change.

Run: python -m pytest tracker/test_download_builder.py
"""
import sys
import types
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

import pytest                                          # noqa: E402


# ── a Streamlit stand-in that records what got rendered ──────────────────────
# helpers/ui.py imports streamlit at module level, so the seam is the module
# attribute. This records the calls the assertions care about and no more —
# a fuller fake would be testing Streamlit, not this function.
class _Col:
    def __init__(self, sink):
        self._sink = sink

    def download_button(self, label, data, **kw):
        self._sink.append(("download", label))


class _FakeST:
    def __init__(self, click=False):
        self.session_state = {}
        self.calls = []
        self._click = click

    def button(self, label, **kw):
        self.calls.append(("button", label))
        return self._click

    def download_button(self, label, data, **kw):
        self.calls.append(("download", label))

    def caption(self, text, **kw):
        self.calls.append(("caption", text))

    def columns(self, n):
        return [_Col(self.calls) for _ in range(n)]

    def spinner(self, *a, **kw):
        class _N:
            def __enter__(self_inner):
                return None

            def __exit__(self_inner, *exc):
                return False
        return _N()

    def labels(self, kind):
        return [t for k, t in self.calls if k == kind]


@pytest.fixture
def UI(monkeypatch):
    import helpers.ui as _UI
    # a PDF engine is not the subject here; force the HTML-only branch so the
    # assertions read the same on a box with and without xhtml2pdf installed.
    monkeypatch.setattr(_UI, "_pdf_bytes", lambda _doc: None)
    return _UI


def _fake(UI, monkeypatch, click=False):
    st = _FakeST(click=click)
    monkeypatch.setattr(UI, "st", st)
    return st


# ── the finding ──────────────────────────────────────────────────────────────

def test_a_builder_is_not_called_until_the_coach_asks(UI, monkeypatch):
    """The whole point: no click, no build."""
    st = _fake(UI, monkeypatch, click=False)
    built = []

    UI.pdf_or_html_download("Player card", lambda: built.append(1) or "<html>",
                            "card", key="k")

    assert built == [], "the builder ran without anyone clicking Prepare"
    assert st.labels("download") == [], "a download button offered an unbuilt doc"
    assert any("Prepare" in t for t in st.labels("button")), \
        "no Prepare button was rendered"


def test_b_clicking_prepare_builds_and_offers_the_download(UI, monkeypatch):
    """One click builds it once and the download buttons appear in the SAME
    run — no rerun, because `st.rerun` is scope-sensitive and half these call
    sites are inside fragments."""
    st = _fake(UI, monkeypatch, click=True)
    built = []

    UI.pdf_or_html_download("Player card", lambda: built.append(1) or "<html>",
                            "card", key="k")

    assert len(built) == 1, f"builder ran {len(built)} times, expected once"
    assert st.labels("download"), "prepared, but offered no download"


def test_c_a_prepared_doc_survives_the_next_run(UI, monkeypatch):
    """A download click reruns the script. The prepared document has to still
    be there or the coach clicks Prepare, gets a button, clicks it, and lands
    back on Prepare."""
    st = _fake(UI, monkeypatch, click=True)
    built = []

    def _b():
        built.append(1)
        return "<html>"

    UI.pdf_or_html_download("Player card", _b, "card", key="k")
    st._click = False                       # the rerun: nobody clicked anything
    st.calls.clear()
    UI.pdf_or_html_download("Player card", _b, "card", key="k")

    assert len(built) == 1, "rebuilt a document it had already prepared"
    assert st.labels("download"), "lost the prepared document on rerun"


def test_d_a_changed_fingerprint_reprepares(UI, monkeypatch):
    """The staleness guard. Change the recap's sections and the held document
    is the wrong document — it must not be handed over."""
    st = _fake(UI, monkeypatch, click=True)
    built = []

    def _b():
        built.append(1)
        return "<html>"

    UI.pdf_or_html_download("Game recap", _b, "recap", key="k", fp=("a",))
    UI.pdf_or_html_download("Game recap", _b, "recap", key="k", fp=("b",))

    assert len(built) == 2, "served a stale document after its inputs changed"


def test_e_a_plain_string_still_works(UI, monkeypatch):
    """Back-compat. A caller that already has the document in hand should not
    be made to click Prepare for something that cost nothing."""
    st = _fake(UI, monkeypatch, click=False)

    UI.pdf_or_html_download("Scout sheet", "<html>", "scout", key="k")

    assert st.labels("download"), "a ready string was hidden behind Prepare"
    assert not any("Prepare" in t for t in st.labels("button"))
