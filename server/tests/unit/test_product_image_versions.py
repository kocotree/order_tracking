from io import BytesIO

import httpx
import pytest
from PIL import Image

from app.adapters.private_files import FakePrivateFileStore
from app.adapters.product import PrivateProductImageStore, ProductImageCacheError


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


def test_generic_binary_response_caches_verified_image_with_actual_media_type() -> None:
    stream = BytesIO()
    Image.new("RGB", (2, 2), "blue").save(stream, format="JPEG")
    content = stream.getvalue()
    files = FakePrivateFileStore(bucket="images")
    store = PrivateProductImageStore(
        files,
        transport=httpx.MockTransport(lambda _: httpx.Response(
            200, content=content, headers={"content-type": "application/octet-stream"},
        )),
        url_validator=lambda _: True,
    )
    cached = store.cache(source_ref="https://images.example/photo", object_key="unused")
    assert files.get(object_key=cached.object_key) == content
    assert files._objects[cached.object_key][1] == "image/jpeg"


def test_generic_binary_response_rejects_non_image_without_upload() -> None:
    files = FakePrivateFileStore(bucket="images")
    store = PrivateProductImageStore(
        files,
        transport=httpx.MockTransport(lambda _: httpx.Response(
            200, content=b"<html>not an image</html>",
            headers={"content-type": "application/octet-stream"},
        )),
        url_validator=lambda _: True,
    )
    with pytest.raises(ProductImageCacheError):
        store.cache(source_ref="https://images.example/photo", object_key="unused")
    assert files.object_count == 0
