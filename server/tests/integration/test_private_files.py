import hashlib
import os
from uuid import uuid4

import oss2
import pytest

from app.adapters.private_files import AliyunOssPrivateFileStore


def test_oss_private_store_round_trip_and_delete() -> None:
    region = os.getenv("S12_OSS_REGION")
    endpoint = os.getenv("S12_OSS_ENDPOINT")
    access_key_id = os.getenv("S12_OSS_ACCESS_KEY_ID")
    access_key_secret = os.getenv("S12_OSS_ACCESS_KEY_SECRET")
    bucket = os.getenv("S12_OSS_BUCKET")
    if not all((region, endpoint, access_key_id, access_key_secret, bucket)):
        pytest.skip("isolated S12 OSS test bucket is not configured")
    assert region is not None and endpoint is not None
    assert access_key_id is not None and access_key_secret is not None
    assert bucket is not None

    client = oss2.Bucket(
        oss2.AuthV4(access_key_id, access_key_secret),
        endpoint,
        bucket,
        region=region,
    )
    object_key = f"contract-test/{uuid4()}.xlsx"
    content = b"PK\x03\x04isolated-oss-contract-test"
    store = AliyunOssPrivateFileStore(
        endpoint=endpoint,
        region=region,
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        bucket=bucket,
    )

    try:
        store.put(
            object_key=object_key,
            content=content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        downloaded = store.get(object_key=object_key)
        assert hashlib.sha256(downloaded).digest() == hashlib.sha256(content).digest()
        assert client.head_object(object_key).content_type == (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    finally:
        store.delete(object_key=object_key)

    assert list(oss2.ObjectIterator(client, prefix=object_key)) == []
