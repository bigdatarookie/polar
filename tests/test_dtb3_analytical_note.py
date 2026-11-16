"""Static assessed note uses no strategy/grid/ledger or database record."""
import hashlib
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient
from polar.api import create_app


class NoteText(HTMLParser):
    def __init__(self):
        super().__init__(); self.text = []; self.tags = []; self.attributes = []
    def handle_starttag(self, tag, attrs):
        self.tags.append(tag); self.attributes.append(dict(attrs))
    def handle_data(self, value):
        self.text.append(value)


def test_existing_static_report_route_preserves_assessed_scope_without_service():
    class NoServiceCalls:
        def __getattr__(self, name):
            raise AssertionError('Analytical note must not create/read a strategy record: '+name)
    with TestClient(create_app(NoServiceCalls())) as client:
        page = client.get('/ui/notes/dtb3.html')
        assert page.status_code == 200
        raw = client.get('/ui/notes/dtb3.md')
        assert raw.status_code == 200
        assert hashlib.sha256(raw.content).hexdigest() == 'aaddc2152b05fb30b5ee90947e69e1a1dd7f62fc8cea17e2872d734f52ebe1bb'
        parsed = NoteText(); parsed.feed(page.text)
        text = ' '.join(' '.join(parsed.text).split())
        for saved in ('QB-CASH-CARRY-MATERIALITY-20261116-V1',
                      'PASS_CURRENT_VINTAGE_DESCRIPTIVE_SYNTHETIC_REFERENCE',
                      'Strategy profitability, investable cash earnings and historical point-in-time availability are UNKNOWN.',
                      'Actual B11 execution: NOT RUN.', '157663/35175 percent; displayed 4.482246%',
                      'USD 157663/18; displayed USD 8,759.06',
                      '360-day annual discount basis on constant face notional',
                      'Strict prior-date joining does not establish observed publication-known-by timestamps.',
                      'No strategy NAV, order, fill, annualized portfolio return or cash-earnings series exists'):
            assert saved in text
        assert 'canvas' not in parsed.tags
        assert any(a.get('href') == '/ui/?workspace=research#dtb3-note-link' for a in parsed.attributes)
        assert any(a.get('data-source-result-sha256') == 'fe81bb31c76faf11c8ffccd67c40f734d00b765d47c89432d1d61b49a4ddf241' and
                   a.get('data-review-sha256') == '9dacd84d5121f7cc794715f86f084d173b1591703382ad8ba56a1a264d6074ba' for a in parsed.attributes)
    # A fresh application instance serves the same immutable note, with no DB.
    with TestClient(create_app(NoServiceCalls())) as client:
        assert client.get('/ui/notes/dtb3.html').content == page.content
