from typing import Protocol

from app.adapters.errors import ExternalAdapterUnavailable


class AvatarStoreUnavailable(ExternalAdapterUnavailable):
    pass

class AvatarStore(Protocol):
    @property
    def bucket(self) -> str: ...

    def put(self, *, object_key: str, content: bytes, content_type: str) -> None: ...

    def get(self, *, object_key: str) -> bytes: ...

    def delete(self, *, object_key: str) -> None: ...


class FakeAvatarStore:
    def __init__(self, *, bucket: str) -> None:
        self._bucket = bucket
        self._objects: dict[str, tuple[bytes, str]] = {}

    @property
    def bucket(self) -> str:
        return self._bucket

    @property
    def object_count(self) -> int:
        return len(self._objects)

    def put(self, *, object_key: str, content: bytes, content_type: str) -> None:
        self._objects[object_key] = (content, content_type)

    def get(self, *, object_key: str) -> bytes:
        return self._objects[object_key][0]

    def delete(self, *, object_key: str) -> None:
        self._objects.pop(object_key, None)


class DisabledAvatarStore:
    def __init__(self, *, bucket: str) -> None:
        self._bucket = bucket

    @property
    def bucket(self) -> str:
        return self._bucket

    def put(self, *, object_key: str, content: bytes, content_type: str) -> None:
        del object_key, content, content_type
        raise AvatarStoreUnavailable("avatar store is not configured")

    def get(self, *, object_key: str) -> bytes:
        del object_key
        raise AvatarStoreUnavailable("avatar store is not configured")

    def delete(self, *, object_key: str) -> None:
        del object_key
