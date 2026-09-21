import http.client
import ipaddress
import socket
import ssl
from time import monotonic
from typing import cast
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

from app.modules.repairs.workflow import XLSX_MIME

MAX_FILE_BYTES = 20 * 1024 * 1024
TRANSFER_TIMEOUT_SECONDS = 30


class FileTransferError(ValueError):
    pass


class AgentFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    download_url: str
    file_id: str
    mime_type: str = ""
    file_name: str = ""


def _target(url: str, allowed_hosts: frozenset[str]) -> tuple[str, str]:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise FileTransferError("文件来源地址不受信任") from error
    if (
        parsed.scheme != "https"
        or not host
        or host.lower() not in allowed_hosts
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not parsed.path.startswith("/")
    ):
        raise FileTransferError("文件来源地址不受信任")
    path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    return host, path


def _public_addresses(host: str) -> tuple[str, ...]:
    try:
        records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except socket.gaierror as error:
        raise FileTransferError("文件来源无法解析") from error
    addresses = tuple(dict.fromkeys(cast(str, record[4][0]) for record in records))
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise FileTransferError("文件来源解析到受限地址")
    return addresses


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str, *, timeout: int) -> None:
        self._tls_context = ssl.create_default_context()
        super().__init__(host, timeout=timeout, context=self._tls_context)
        self._address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self._address, 443), self.timeout)
        self.sock = self._tls_context.wrap_socket(self.sock, server_hostname=self.host)


def fetch_file(file: AgentFile, allowed_hosts: frozenset[str]) -> bytes:
    if not file.file_id or not file.file_name or not file.file_name.lower().endswith(".xlsx"):
        raise FileTransferError("缺少可验证的 .xlsx 文件元数据")
    if file.mime_type and file.mime_type not in {XLSX_MIME, "application/octet-stream"}:
        raise FileTransferError("文件类型不支持")
    host, path = _target(file.download_url, allowed_hosts)
    address = _public_addresses(host)[0]
    connection = _PinnedHTTPSConnection(host, address, timeout=TRANSFER_TIMEOUT_SECONDS)
    try:
        connection.request("GET", path, headers={"Accept": XLSX_MIME})
        response = connection.getresponse()
        if response.status != 200:
            raise FileTransferError("文件获取失败或下载链接已失效")
        length = response.getheader("Content-Length")
        if length is not None:
            try:
                declared_size = int(length)
            except ValueError as error:
                raise FileTransferError("文件响应长度无效") from error
            if declared_size < 0 or declared_size > MAX_FILE_BYTES:
                raise FileTransferError("质检 Excel 超过文件大小上限")
        chunks: list[bytes] = []
        size = 0
        deadline = monotonic() + TRANSFER_TIMEOUT_SECONDS
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise FileTransferError("文件获取超时")
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            chunk = response.read(65536)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                raise FileTransferError("质检 Excel 超过文件大小上限")
            chunks.append(chunk)
        return b"".join(chunks)
    except (OSError, ssl.SSLError, http.client.HTTPException) as error:
        raise FileTransferError("文件获取失败或下载链接已失效") from error
    finally:
        connection.close()


def download_descriptor(
    *, origin: str, path: str, filename: str, size_bytes: int, sha256: str
) -> dict[str, str | int]:
    if not path.startswith("/api/v1/") or "?" in path or "#" in path:
        raise ValueError("下载路径必须是固定的业务 API 路径")
    return {
        "downloadUrl": f"{origin}{path}",
        "filename": filename,
        "mimeType": XLSX_MIME,
        "sizeBytes": size_bytes,
        "sha256": sha256,
    }
