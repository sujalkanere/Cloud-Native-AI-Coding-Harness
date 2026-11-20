"""
S3 Object Storage Adapter for Cloud-Native AI Coding Harness.
Implements IObjectStorage contract via boto3 adhering strictly to Spec §3.2, §3.5, §7.
Dual-client SigV4 architecture:
- Internal client for backend IO (put/get) via S3_ENDPOINT_URL.
- Public client for presigned URLs signed against S3_PUBLIC_ENDPOINT_URL.
- User-namespaced artifact keys: artifacts/{user_id}/{run_id}/...
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import boto3
import botocore.client
from backend.app.domain.errors import EntityNotFoundError
from backend.app.domain.interfaces import IObjectStorage
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class S3ObjectStorage(IObjectStorage):
    """
    S3 Object Storage adapter implementing IObjectStorage.
    Handles dual-client presigning and user-namespaced keys.
    """

    def __init__(
        self,
        endpoint_url: str,
        public_endpoint_url: str | None = None,
        bucket: str = "harness-artifacts",
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str = "us-east-1",
        client: Any | None = None,
        presign_client: Any | None = None,
    ) -> None:
        self.endpoint_url = endpoint_url
        self.public_endpoint_url = public_endpoint_url or endpoint_url
        self.bucket = bucket
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region

        # Internal client for backend operations (put, get, head)
        self._client = client or boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
            config=botocore.client.Config(signature_version="s3v4"),
        )

        # Public client strictly for presigned URL generation (Spec §7)
        self._presign_client = presign_client or boto3.client(
            "s3",
            endpoint_url=self.public_endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
            config=botocore.client.Config(signature_version="s3v4"),
        )

    @staticmethod
    def build_artifact_key(user_id: str, run_id: str, filename: str) -> str:
        """Constructs partitioned artifact key: artifacts/{user_id}/{run_id}/{filename} (Spec §3.5)."""
        clean_file = filename.lstrip("/")
        return f"artifacts/{user_id}/{run_id}/{clean_file}"

    @staticmethod
    def validate_artifact_key(key: str, user_id: str, run_id: str) -> bool:
        """Validates that key belongs to the specified user and run namespace."""
        expected_prefix = f"artifacts/{user_id}/{run_id}/"
        return key.startswith(expected_prefix)

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        """Stores binary object data at the specified key non-blockingly."""
        def _put() -> None:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )

        await asyncio.to_thread(_put)

    async def get(self, key: str) -> bytes:
        """Retrieves binary object data from key, mapping 404/NoSuchKey to EntityNotFoundError."""
        def _get() -> bytes:
            try:
                response = self._client.get_object(Bucket=self.bucket, Key=key)
                return response["Body"].read()
            except ClientError as exc:
                error_code = exc.response.get("Error", {}).get("Code", "")
                if error_code in ("NoSuchKey", "404", "NotFound"):
                    raise EntityNotFoundError(f"Artifact not found: {key}") from exc
                raise

        return await asyncio.to_thread(_get)

    def presigned_url(self, key: str, ttl: int = 3600) -> str:
        """
        Generates a public presigned GET URL signed against S3_PUBLIC_ENDPOINT_URL.
        Synchronous method because SigV4 computation is purely local CPU HMAC-SHA256.
        """
        return self._presign_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=ttl,
        )

    async def ensure_bucket_exists(self) -> None:
        """Ensures the configured bucket exists, creating it if necessary."""
        def _ensure() -> None:
            try:
                self._client.head_bucket(Bucket=self.bucket)
            except ClientError as exc:
                error_code = exc.response.get("Error", {}).get("Code", "")
                if error_code in ("404", "NoSuchBucket", "NotFound"):
                    if self.region == "us-east-1":
                        self._client.create_bucket(Bucket=self.bucket)
                    else:
                        self._client.create_bucket(
                            Bucket=self.bucket,
                            CreateBucketConfiguration={"LocationConstraint": self.region},
                        )
                else:
                    raise

        await asyncio.to_thread(_ensure)
