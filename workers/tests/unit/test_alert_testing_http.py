import pytest

from quakestrike.alert_testing.interface.http import validate_origin


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:4341",
        "https://tool.example.ts.net",
        "https://tool.example.ts.net:443",
        "https://quakestrike-vps.tailf8b2fd.ts.net:8443",
    ],
)
def test_control_origin_is_loopback_or_tailnet(origin):
    assert validate_origin(origin) == origin


@pytest.mark.parametrize(
    "origin",
    [
        "https://quakestrikeph.com",
        "https://quakestrikeph.qzz.io",
        "http://0.0.0.0:4341",
        "http://tool.example.ts.net",
        "https://tool.example.ts.net/",
        "https://tool.example.ts.net?override=1",
        "https://tool.example.ts.net#fragment",
        "https://secret@tool.example.ts.net",
        "https://tool.example.ts.net:444",
        "https://tool.example.ts.net:4341",
        "https://tool.example.ts.net:8444",
        "https://tool.example.ts.net:8443/",
        "http://tool.example.ts.net:8443",
        "https://tool.example.ts.net.evil.invalid:8443",
        "https://*.example.ts.net:8443",
    ],
)
def test_control_origin_rejects_public_or_ambiguous_origins(origin):
    with pytest.raises(ValueError):
        validate_origin(origin)
