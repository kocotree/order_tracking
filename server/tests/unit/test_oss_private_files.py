import pytest

from app.adapters.private_files import AliyunOssPrivateFileStore, PrivateFileStoreUnavailable


class FakeOssObject:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def read(self) -> bytes:
        return self._content


class FakeOssBucket:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put_object(
        self,
        object_key: str,
        content: bytes,
        headers: dict[str, str] | None = None,
    ) -> None:
        del headers
        self._objects[object_key] = content

    def get_object(self, object_key: str) -> FakeOssObject:
        return FakeOssObject(self._objects[object_key])

    def delete_object(self, object_key: str) -> None:
        self._objects.pop(object_key, None)


def test_oss_private_store_round_trips_uploaded_content() -> None:
    store = AliyunOssPrivateFileStore(
        endpoint="https://oss-cn-example-internal.aliyuncs.com",
        region="cn-example",
        access_key_id="test-access-key-id",
        access_key_secret="test-access-key-secret",
        bucket="order-tracking-test",
        bucket_client=FakeOssBucket(),
    )

    store.put(
        object_key="contracts/2026/08/export.xlsx",
        content=b"PK\x03\x04contract",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    assert store.get(object_key="contracts/2026/08/export.xlsx") == b"PK\x03\x04contract"


def test_oss_private_store_deletes_content() -> None:
    store = AliyunOssPrivateFileStore(
        endpoint="https://oss-cn-example-internal.aliyuncs.com",
        region="cn-example",
        access_key_id="test-access-key-id",
        access_key_secret="test-access-key-secret",
        bucket="order-tracking-test",
        bucket_client=FakeOssBucket(),
    )
    store.put(
        object_key="avatars/avatar.png",
        content=b"avatar",
        content_type="image/png",
    )

    store.delete(object_key="avatars/avatar.png")

    with pytest.raises(PrivateFileStoreUnavailable, match="private file does not exist"):
        store.get(object_key="avatars/avatar.png")
