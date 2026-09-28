from io import BytesIO

import httpx
from PIL import Image

from app.adapters.private_files import FakePrivateFileStore
from app.adapters.product import PrivateProductImageStore


def test_changed_bytes_at_the_same_source_never_overwrite_historical_objects() -> None:
    contents = []
    for color in ("blue", "red"):
        stream = BytesIO()
        Image.new("RGB", (2, 2), color).save(stream, format="PNG")
        contents.append(stream.getvalue())
    current = contents[0]

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=current, headers={"content-type": "image/png"})

    files = FakePrivateFileStore(bucket="images")
    store = PrivateProductImageStore(
        files, transport=httpx.MockTransport(respond), url_validator=lambda _: True,
    )
    first = store.cache(source_ref="https://images.example/same", object_key="same-request-key")
    current = contents[1]
    second = store.cache(source_ref="https://images.example/same", object_key="same-request-key")
    assert first.object_key != second.object_key
    assert files.get(object_key=first.object_key) == contents[0]
    assert files.get(object_key=second.object_key) == contents[1]
    assert files.object_count == 2
