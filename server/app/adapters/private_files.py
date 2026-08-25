from io import BytesIO
from typing import Protocol

from minio import Minio

from app.adapters.errors import ExternalAdapterUnavailable


class PrivateFileStoreUnavailable(ExternalAdapterUnavailable):
    pass


class PrivateFileStore(Protocol):
    @property
    def bucket(self) -> str: ...

    def put(self, *, object_key: str, content: bytes, content_type: str) -> None: ...

    def get(self, *, object_key: str) -> bytes: ...

    def delete(self, *, object_key: str) -> None: ...


class FakePrivateFileStore:
    def __init__(self, *, bucket: str, fail_put: bool = False) -> None:
        self._bucket = bucket
        self._fail_put = fail_put
        self._objects: dict[str, tuple[bytes, str]] = {}

    @property
    def bucket(self) -> str:
        return self._bucket

    @property
    def object_count(self) -> int:
        return len(self._objects)

    def put(self, *, object_key: str, content: bytes, content_type: str) -> None:
        if self._fail_put:
            raise PrivateFileStoreUnavailable("private file upload failed")
        self._objects[object_key] = (content, content_type)

    def get(self, *, object_key: str) -> bytes:
        try:
            return self._objects[object_key][0]
        except KeyError as error:
            raise PrivateFileStoreUnavailable("private file does not exist") from error

    def delete(self, *, object_key: str) -> None:
        self._objects.pop(object_key, None)


class DisabledPrivateFileStore:
    def __init__(self, *, bucket: str) -> None:
        self._bucket = bucket

    @property
    def bucket(self) -> str:
        return self._bucket

    def put(self, *, object_key: str, content: bytes, content_type: str) -> None:
        del object_key, content, content_type
        raise PrivateFileStoreUnavailable("private file store is not configured")

    def get(self, *, object_key: str) -> bytes:
        del object_key
        raise PrivateFileStoreUnavailable("private file store is not configured")

    def delete(self, *, object_key: str) -> None:
        del object_key


class MinioPrivateFileStore:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool,
    ) -> None:
        self._bucket = bucket
        self._client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    @property
    def bucket(self) -> str:
        return self._bucket

    def put(self, *, object_key: str, content: bytes, content_type: str) -> None:
        try:
            self._client.put_object(
                self._bucket,
                object_key,
                BytesIO(content),
                len(content),
                content_type=content_type,
            )
        except Exception as error:
            raise PrivateFileStoreUnavailable("private file upload failed") from error

    def get(self, *, object_key: str) -> bytes:
        try:
            response = self._client.get_object(self._bucket, object_key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except Exception as error:
            raise PrivateFileStoreUnavailable("private file download failed") from error

    def delete(self, *, object_key: str) -> None:
        try:
            self._client.remove_object(self._bucket, object_key)
        except Exception as error:
            raise PrivateFileStoreUnavailable("private file delete failed") from error
