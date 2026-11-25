from __future__ import annotations

from backend.app.application.multi_agent import AGENT_DEFS, _extract_files


def test_agent_defs_has_five_specialized_agents():
    ids = [a[0] for a in AGENT_DEFS]
    assert ids == ["planner", "researcher", "designer", "architect", "system_designer"]


def test_extract_files_parses_explicit_file_blocks():
    sample = """
Here is the implementation:
```file:index.html
<!doctype html><html><body>Coffee House</body></html>
```
```file:styles.css
body { color: #ededed; }
```
"""
    files = _extract_files(sample)
    assert files == [
        ("index.html", "<!doctype html><html><body>Coffee House</body></html>"),
        ("styles.css", "body { color: #ededed; }"),
    ]


def test_extract_files_falls_back_to_html_fence():
    sample = "```html\n<!DOCTYPE html><html><body><div>Roastery</div></body></html>\n```"
    files = _extract_files(sample)
    assert files == [("index.html", "<!DOCTYPE html><html><body><div>Roastery</div></body></html>")]


def test_extract_files_parses_raw_html_without_fences():
    sample = "Here is your site:\n<!DOCTYPE html><html><head></head><body><h1>Espresso</h1></body></html>"
    files = _extract_files(sample)
    assert files == [("index.html", "<!DOCTYPE html><html><head></head><body><h1>Espresso</h1></body></html>")]


def test_extract_files_parses_unclosed_file_fence():
    sample = "```file:index.html\n<!DOCTYPE html><html><body><h1>Roastery</h1>"
    files = _extract_files(sample)
    assert files[0][0] == "index.html"
    assert "Roastery" in files[0][1]
