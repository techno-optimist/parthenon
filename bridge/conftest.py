"""Every bridge test runs against a temporary sign-in file.

The bridge's default GROK_BRIDGE_TOKEN_FILE is the owner's real Grok sign-in
(~/.config/parthenon/grok-oauth.json). No test may read, refresh or rewrite it,
so TOKEN_FILE points at a file that does not exist yet inside each test's own
temporary folder; a test that needs a sign-in writes a fake one there.
"""

import pytest

import grok_bridge as gb


@pytest.fixture(autouse=True)
def _never_the_owners_sign_in(tmp_path_factory, monkeypatch):
    monkeypatch.setattr(gb, "TOKEN_FILE", tmp_path_factory.mktemp("sign-in") / "grok-oauth.json")
