import socket

import pytest

from app.mcp.files import AgentFile, FileTransferError, _public_addresses, _target, fetch_file


def test_file_parameter_schema_matches_official_contract():
    schema = AgentFile.model_json_schema()
    assert set(schema["properties"]) == {
        "download_url", "file_id", "mime_type", "file_name",
    }
    assert set(schema["required"]) == {"download_url", "file_id"}
    assert all(field["type"] == "string" for field in schema["properties"].values())


@pytest.mark.parametrize(
    "url",
    [
        "http://files.example.test/input.xlsx",
        "https://127.0.0.1/input.xlsx",
        "https://files.example.test:444/input.xlsx",
        "https://files.example.test:invalid/input.xlsx",
        "https://files.example.test@other.example/input.xlsx",
        "https://files.example.test/input.xlsx#fragment",
        "https://other.example/input.xlsx",
    ],
)
def test_file_source_rejects_unapproved_address(url):
    with pytest.raises(FileTransferError):
        _target(url, frozenset({"files.example.test"}))


def test_file_source_rejects_mixed_public_and_private_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(FileTransferError):
        _public_addresses("files.example.test")


def test_file_transfer_rejects_redirect_and_oversize(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
        ],
    )

    class FakeResponse:
        status = 200

        def __init__(self, payload):
            self.payload = payload

        def read(self, _size):
            payload, self.payload = self.payload, b""
            return payload

        def getheader(self, _name):
            return None

    class FakeSocket:
        timeouts = []

        def settimeout(self, value):
            self.timeouts.append(value)

        def close(self):
            pass

    class FakeConnection:
        response = FakeResponse(b"x" * (20 * 1024 * 1024 + 1))
        last_sock = None

        def __init__(self, *_args, **_kwargs):
            self.sock = FakeSocket()
            FakeConnection.last_sock = self.sock

        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            self.sock = None
            return self.response

        def close(self):
            pass

    monkeypatch.setattr("app.mcp.files._PinnedHTTPSConnection", FakeConnection)
    file = AgentFile(
        download_url="https://files.example.test/input.xlsx",
        file_id="file-1",
        file_name="input.xlsx",
    )
    with pytest.raises(FileTransferError):
        fetch_file(file, frozenset({"files.example.test"}))
    assert FakeConnection.last_sock.timeouts
    FakeConnection.response = FakeResponse(b"")
    FakeConnection.response.status = 302
    with pytest.raises(FileTransferError):
        fetch_file(file, frozenset({"files.example.test"}))
