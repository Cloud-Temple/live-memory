from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
BANK_JS = ROOT / "src" / "live_mem" / "static" / "js" / "bank.js"


def _select_bank_body() -> str:
    source = BANK_JS.read_text()
    match = re.search(r"async function selectBank\(filename\) \{(?P<body>.*?)\n\}", source, re.S)
    assert match, "selectBank(filename) not found in bank.js"
    return match.group("body")


def test_select_bank_uses_captured_space_and_filename_for_load():
    body = _select_bank_body()

    assert "const requestedSpaceId = app.spaceId;" in body
    assert "const requestedFilename = filename;" in body
    assert "apiLoadBankFile(requestedSpaceId, requestedFilename)" in body


def test_select_bank_drops_stale_responses_before_rendering():
    body = _select_bank_body()
    stale_guard = (
        "app.spaceId !== requestedSpaceId "
        "|| app.currentBankFile !== requestedFilename"
    )

    assert stale_guard in body
    assert body.index(stale_guard) < body.index('el.innerHTML = `<div class="md-content">')
    assert body.rindex(stale_guard) < body.rindex('el.innerHTML = `<div class="empty-state">❌')
