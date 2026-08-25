import hashlib
import os
from uuid import uuid4

import pytest
from minio import Minio
from minio.error import S3Error

from app.adapters.private_files import MinioPrivateFileStore


def test_minio_private_store_round_trip_and_delete() -> None:
    endpoint = os.getenv("S06_MINIO_ENDPOINT")
    access_key = os.getenv("S06_MINIO_ACCESS_KEY")
    secret_key = os.getenv("S06_MINIO_SECRET_KEY")
    bucket = os.getenv("S06_MINIO_BUCKET")
    if not all((endpoint, access_key, secret_key, bucket)):
        pytest.skip("isolated S06 MinIO test bucket is not configured")
    assert endpoint is not None and access_key is not None
    assert secret_key is not None and bucket is not None

    client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=False)
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    object_key = f"contract-test/{uuid4()}.xlsx"
    content = b"PK\x03\x04isolated-minio-contract-test"
    store = MinioPrivateFileStore(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        bucket=bucket,
        secure=False,
    )

    try:
        store.put(
            object_key=object_key,
            content=content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        downloaded = store.get(object_key=object_key)
        assert hashlib.sha256(downloaded).digest() == hashlib.sha256(content).digest()
        assert client.stat_object(bucket, object_key).content_type == (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        with pytest.raises(S3Error) as policy_error:
            client.get_bucket_policy(bucket)
        assert policy_error.value.code == "NoSuchBucketPolicy"
    finally:
        store.delete(object_key=object_key)

    assert list(client.list_objects(bucket, prefix=object_key)) == []
