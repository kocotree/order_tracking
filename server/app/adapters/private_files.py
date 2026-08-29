from typing import Protocol

from app.adapters.errors import ExternalAdapterUnavailable


class PrivateFileStoreUnavailable(ExternalAdapterUnavailable):
    pass


class PrivateFileStore(Protocol):
    @property
    def bucket(self) -> str: ...

    def put(self, *, object_key: str, content: bytes, content_type: str) -> None: ...

    def get(self, *, object_key: str) -> bytes: ...

    def delete(self, *, object_key: str) -> None: ...


class OssObject(Protocol):
    def read(self) -> bytes: ...


class OssBucketClient(Protocol):
    def put_object(
        self,
        object_key: str,
        content: bytes,
        headers: dict[str, str] | None = None,
    ) -> object: ...

    def get_object(self, object_key: str) -> OssObject: ...

    def delete_object(self, object_key: str) -> object: ...


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


class AliyunOssPrivateFileStore:
    def __init__(
        self,
        *,
        endpoint: str,
        region: str,
        access_key_id: str,
        access_key_secret: str,
        bucket: str,
        bucket_client: OssBucketClient | None = None,
    ) -> None:
        self._bucket = bucket
        if bucket_client is None:
            import oss2

            auth = oss2.AuthV4(access_key_id, access_key_secret)
            bucket_client = oss2.Bucket(auth, endpoint, bucket, region=region)
        self._client = bucket_client

    @property
    def bucket(self) -> str:
        return self._bucket

    def put(self, *, object_key: str, content: bytes, content_type: str) -> None:
        try:
            self._client.put_object(
                object_key,
                content,
                headers={"Content-Type": content_type},
            )
        except Exception as error:
            raise PrivateFileStoreUnavailable("private file upload failed") from error

    def get(self, *, object_key: str) -> bytes:
        try:
            return self._client.get_object(object_key).read()
        except Exception as error:
            raise PrivateFileStoreUnavailable("private file does not exist") from error

    def delete(self, *, object_key: str) -> None:
        try:
            self._client.delete_object(object_key)
        except Exception as error:
            raise PrivateFileStoreUnavailable("private file delete failed") from error
