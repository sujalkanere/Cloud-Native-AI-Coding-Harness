"""Unit tests for S3ObjectStorage adapter."""
from unittest.mock import MagicMock

import pytest
from backend.app.domain.errors import EntityNotFoundError
from backend.app.domain.interfaces import IObjectStorage
from backend.app.infrastructure.storage.s3 import S3ObjectStorage
from botocore.exceptions import ClientError


def test_protocol_conformance():
    storage = S3ObjectStorage(
        endpoint_url="http://minio:9000",
        public_endpoint_url="http://127.0.0.1:9000",
        bucket="harness-artifacts",
    )
    assert isinstance(storage, IObjectStorage)


def test_user_namespaced_keys():
    key = S3ObjectStorage.build_artifact_key(
        user_id="user_123",
        run_id="run_abc",
        filename="patch.diff",
    )
    assert key == "artifacts/user_123/run_abc/patch.diff"
    assert S3ObjectStorage.validate_artifact_key(key, "user_123", "run_abc") is True
    assert S3ObjectStorage.validate_artifact_key(key, "user_456", "run_abc") is False
    assert S3ObjectStorage.validate_artifact_key(key, "user_123", "run_xyz") is False


@pytest.mark.asyncio
async def test_s3_put_and_get():
    mock_client = MagicMock()
    mock_presign = MagicMock()

    # Mock get_object return
    mock_body = MagicMock()
    mock_body.read.return_value = b"binary artifact content"
    mock_client.get_object.return_value = {"Body": mock_body}

    storage = S3ObjectStorage(
        endpoint_url="http://minio:9000",
        public_endpoint_url="http://127.0.0.1:9000",
        bucket="harness-artifacts",
        client=mock_client,
        presign_client=mock_presign,
    )

    # Put
    await storage.put("artifacts/user_1/run_1/test.txt", b"hello", "text/plain")
    mock_client.put_object.assert_called_once_with(
        Bucket="harness-artifacts",
        Key="artifacts/user_1/run_1/test.txt",
        Body=b"hello",
        ContentType="text/plain",
    )

    # Get
    data = await storage.get("artifacts/user_1/run_1/test.txt")
    assert data == b"binary artifact content"
    mock_client.get_object.assert_called_once_with(
        Bucket="harness-artifacts",
        Key="artifacts/user_1/run_1/test.txt",
    )


@pytest.mark.asyncio
async def test_s3_get_not_found():
    mock_client = MagicMock()
    mock_presign = MagicMock()

    mock_client.get_object.side_effect = ClientError(
        error_response={"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}},
        operation_name="GetObject",
    )

    storage = S3ObjectStorage(
        endpoint_url="http://minio:9000",
        public_endpoint_url="http://127.0.0.1:9000",
        client=mock_client,
        presign_client=mock_presign,
    )

    with pytest.raises(EntityNotFoundError, match="Artifact not found"):
        await storage.get("artifacts/user_1/run_1/missing.txt")


def test_presigned_url_generation():
    mock_client = MagicMock()
    mock_presign = MagicMock()

    mock_presign.generate_presigned_url.return_value = (
        "http://127.0.0.1:9000/harness-artifacts/artifacts/user_1/run_1/patch.diff?X-Amz-Signature=..."
    )

    storage = S3ObjectStorage(
        endpoint_url="http://minio:9000",
        public_endpoint_url="http://127.0.0.1:9000",
        bucket="harness-artifacts",
        client=mock_client,
        presign_client=mock_presign,
    )

    url = storage.presigned_url("artifacts/user_1/run_1/patch.diff", ttl=1800)
    assert "http://127.0.0.1:9000" in url
    mock_presign.generate_presigned_url.assert_called_once_with(
        ClientMethod="get_object",
        Params={"Bucket": "harness-artifacts", "Key": "artifacts/user_1/run_1/patch.diff"},
        ExpiresIn=1800,
    )


@pytest.mark.asyncio
async def test_ensure_bucket_exists():
    mock_client = MagicMock()
    # First call: head_bucket raises 404
    mock_client.head_bucket.side_effect = ClientError(
        error_response={"Error": {"Code": "404"}},
        operation_name="HeadBucket",
    )

    storage = S3ObjectStorage(
        endpoint_url="http://minio:9000",
        bucket="test-bucket",
        region="us-west-2",
        client=mock_client,
        presign_client=MagicMock(),
    )

    await storage.ensure_bucket_exists()
    mock_client.create_bucket.assert_called_once_with(
        Bucket="test-bucket",
        CreateBucketConfiguration={"LocationConstraint": "us-west-2"},
    )
