"""S3-compatible object storage, as the narrow slice images.py needs.

Points at whatever endpoint is configured -- MinIO on the local node today, any
S3 tomorrow -- so the mirror logic never learns which.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Anonymous read on this one bucket. The contents are public team logos and
# player headshots served straight to browsers; putting the API in front of them
# would add a Python hop to every image on every page for no privacy gain.
PUBLIC_READ_POLICY = """{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"AWS": ["*"]},
    "Action": ["s3:GetObject"],
    "Resource": ["arn:aws:s3:::%s/*"]
  }]
}"""


@dataclass(frozen=True, slots=True)
class S3Settings:
    endpoint_url: str
    access_key: str
    secret_key: str

    @classmethod
    def from_environment(cls) -> S3Settings:
        missing = [
            name
            for name in ("WNBA_S3_ENDPOINT", "WNBA_S3_ACCESS_KEY", "WNBA_S3_SECRET_KEY")
            if not os.environ.get(name)
        ]
        if missing:
            raise ValueError(f"object storage is not configured: {', '.join(missing)} unset")
        return cls(
            endpoint_url=os.environ["WNBA_S3_ENDPOINT"],
            access_key=os.environ["WNBA_S3_ACCESS_KEY"],
            secret_key=os.environ["WNBA_S3_SECRET_KEY"],
        )


class S3ObjectStore:
    """Implements the ObjectStore protocol in wnba_engine/assets/images.py."""

    def __init__(self, settings: S3Settings) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.endpoint_url,
            aws_access_key_id=settings.access_key,
            aws_secret_access_key=settings.secret_key,
            # MinIO wants path-style addressing; virtual-host style would
            # resolve bucket.host, which does not exist on a private endpoint.
            config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
            region_name="us-east-1",
        )

    def ensure_bucket(self, bucket: str, *, public: bool = True) -> None:
        """Create the bucket if absent and make it readable. Idempotent."""
        try:
            self._client.head_bucket(Bucket=bucket)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket"):
                raise
            self._client.create_bucket(Bucket=bucket)
            logger.info("created bucket %s", bucket)
        if public:
            self._client.put_bucket_policy(Bucket=bucket, Policy=PUBLIC_READ_POLICY % bucket)

    def exists(self, bucket: str, key: str) -> bool:
        try:
            self._client.head_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "403"):
                return False
            raise
        return True

    def put(self, bucket: str, key: str, body: bytes, content_type: str) -> None:
        self._client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            # Immutable by construction: a key is derived from our own entity id,
            # and a re-sync overwrites in place. A year of browser caching is
            # safe and keeps these off the origin entirely.
            CacheControl="public, max-age=31536000, immutable",
        )
