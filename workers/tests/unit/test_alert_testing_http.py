from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from quakestrike.alert_testing.interface.http import PrivateServer, validate_origin


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


def test_places_asset_preserves_private_host_and_static_file_boundaries(tmp_path):
    asset = tmp_path / "assets/accounts/philippine-places.json"
    asset.parent.mkdir(parents=True)
    asset.write_text('[{"name":"Fixture place"}]')
    (tmp_path / "private.json").write_text('"private"')
    server = PrivateServer(None, tmp_path, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        request = Request(base + "/assets/accounts/philippine-places.json")
        with urlopen(request, timeout=3) as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "application/json"
            assert response.headers["Cache-Control"] == "no-store"
            assert response.read() == asset.read_bytes()
        for path, host, expected in (
            ("/assets/accounts/philippine-places.json", "public.invalid", 403),
            ("/assets/accounts/../../private.json", server.authority, 404),
            ("/private.json", server.authority, 404),
        ):
            with pytest.raises(HTTPError) as caught:
                urlopen(Request(base + path, headers={"Host": host}), timeout=3)
            assert caught.value.code == expected
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
