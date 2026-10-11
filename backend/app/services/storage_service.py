"""
Object Storage Service.
Provides a unified storage abstraction supporting:
1. Cloud Object Storage (AWS S3, Cloudflare R2, MinIO, Backblaze B2) via S3-compatible API.
2. Local disk storage with cryptographic HMAC-SHA256 signed URLs (for development and standalone setups).
"""

import os
import io
import time
import logging
from typing import Optional, Dict, Any, List

from app.config import settings

logger = logging.getLogger("intervai.storage")


class BaseStorageProvider:
    """Interface for interview asset and recording storage."""

    def save_bytes(self, data: bytes, destination_key: str, content_type: str = "application/octet-stream") -> str:
        raise NotImplementedError

    def get_signed_url(
        self,
        destination_key: str,
        expires_in_seconds: int = 3600,
        content_type: Optional[str] = None,
        base_url: str = "",
    ) -> str:
        raise NotImplementedError

    def delete_file(self, destination_key: str) -> bool:
        raise NotImplementedError

    def delete_prefix(self, prefix: str) -> int:
        raise NotImplementedError

    def read_bytes(self, destination_key: str) -> Optional[bytes]:
        raise NotImplementedError

    def file_exists(self, destination_key: str) -> bool:
        raise NotImplementedError


class LocalStorageProvider(BaseStorageProvider):
    """Local disk storage provider with HMAC signed URLs."""

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir:
            self.base_dir = base_dir
        else:
            self.base_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "storage",
                "sessions",
            )
        os.makedirs(self.base_dir, exist_ok=True)

    def _resolve_path(self, destination_key: str) -> str:
        clean_key = destination_key.replace("/", os.sep).strip(os.sep)
        return os.path.join(self.base_dir, clean_key)

    def save_bytes(self, data: bytes, destination_key: str, content_type: str = "application/octet-stream") -> str:
        target_path = self._resolve_path(destination_key)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "wb") as f:
            f.write(data)
        logger.info(f"[Storage][Local] Saved {len(data)} bytes to {destination_key}")
        return target_path

    def get_signed_url(
        self,
        destination_key: str,
        expires_in_seconds: int = 3600,
        content_type: Optional[str] = None,
        base_url: str = "",
    ) -> str:
        # Parse session_id and file_type from key format: "sessions/{id}/{filename}"
        parts = destination_key.strip("/").split("/")
        session_id = 0
        file_type = "audio"
        if len(parts) >= 2 and parts[0] == "sessions":
            try:
                session_id = int(parts[1])
            except ValueError:
                pass
            if len(parts) >= 3:
                filename = parts[2].lower()
                if "video" in filename or "manifest" in filename:
                    file_type = "video"
                else:
                    file_type = "audio"

        from app.services.signed_url_service import generate_signed_recording_url
        res = generate_signed_recording_url(
            session_id=session_id,
            file_type=file_type,
            expires_in_seconds=expires_in_seconds,
            base_url=base_url,
        )
        return res["url"]

    def delete_file(self, destination_key: str) -> bool:
        target_path = self._resolve_path(destination_key)
        if os.path.exists(target_path):
            try:
                os.remove(target_path)
                logger.info(f"[Storage][Local] Deleted {destination_key}")
                return True
            except OSError as e:
                logger.error(f"[Storage][Local] Failed to delete {destination_key}: {e}")
                return False
        return False

    def delete_prefix(self, prefix: str) -> int:
        target_dir = self._resolve_path(prefix)
        count = 0
        if os.path.exists(target_dir):
            import shutil
            for root, dirs, files in os.walk(target_dir):
                count += len(files)
            try:
                shutil.rmtree(target_dir, ignore_errors=True)
                logger.info(f"[Storage][Local] Pruned prefix directory {prefix} ({count} files)")
            except Exception as e:
                logger.error(f"[Storage][Local] Error removing prefix {prefix}: {e}")
        return count

    def read_bytes(self, destination_key: str) -> Optional[bytes]:
        target_path = self._resolve_path(destination_key)
        if os.path.exists(target_path):
            with open(target_path, "rb") as f:
                return f.read()
        return None

    def file_exists(self, destination_key: str) -> bool:
        return os.path.exists(self._resolve_path(destination_key))


class S3StorageProvider(BaseStorageProvider):
    """
    S3-Compatible Object Storage Provider.
    Works seamlessly with AWS S3, Cloudflare R2, MinIO, and Backblaze B2.
    """

    def __init__(self):
        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            raise RuntimeError(
                "boto3 is required for S3 object storage. Run: pip install boto3"
            )

        self.bucket = settings.S3_BUCKET_NAME
        client_kwargs = {
            "service_name": "s3",
            "aws_access_key_id": settings.S3_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.S3_SECRET_ACCESS_KEY,
            "config": Config(signature_version="s3v4"),
        }
        if settings.S3_ENDPOINT_URL:
            client_kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
        if settings.S3_REGION_NAME and settings.S3_REGION_NAME != "auto":
            client_kwargs["region_name"] = settings.S3_REGION_NAME

        self.s3_client = boto3.client(**client_kwargs)
        logger.info(
            f"[Storage][S3] Initialized S3 client for bucket '{self.bucket}' "
            f"(endpoint: {settings.S3_ENDPOINT_URL or 'AWS Default'})"
        )

    def save_bytes(self, data: bytes, destination_key: str, content_type: str = "application/octet-stream") -> str:
        key = destination_key.lstrip("/")
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        logger.info(f"[Storage][S3] Uploaded {len(data)} bytes to s3://{self.bucket}/{key}")
        return f"s3://{self.bucket}/{key}"

    def get_signed_url(
        self,
        destination_key: str,
        expires_in_seconds: int = 3600,
        content_type: Optional[str] = None,
        base_url: str = "",
    ) -> str:
        key = destination_key.lstrip("/")
        params: Dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if content_type:
            params["ResponseContentType"] = content_type

        presigned_url = self.s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params=params,
            ExpiresIn=expires_in_seconds,
        )
        logger.info(f"[Storage][S3] Generated presigned URL for key {key} (expires {expires_in_seconds}s)")
        return presigned_url

    def delete_file(self, destination_key: str) -> bool:
        key = destination_key.lstrip("/")
        try:
            self.s3_client.delete_object(Bucket=self.bucket, Key=key)
            logger.info(f"[Storage][S3] Deleted object s3://{self.bucket}/{key}")
            return True
        except Exception as e:
            logger.error(f"[Storage][S3] Failed to delete s3://{self.bucket}/{key}: {e}")
            return False

    def delete_prefix(self, prefix: str) -> int:
        clean_prefix = prefix.strip("/") + "/"
        deleted_count = 0
        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=clean_prefix):
                items = page.get("Contents", [])
                if items:
                    delete_keys = [{"Key": obj["Key"]} for obj in items]
                    self.s3_client.delete_objects(
                        Bucket=self.bucket,
                        Delete={"Objects": delete_keys},
                    )
                    deleted_count += len(delete_keys)
            logger.info(f"[Storage][S3] Deleted {deleted_count} objects under prefix '{clean_prefix}'")
        except Exception as e:
            logger.error(f"[Storage][S3] Error deleting prefix '{clean_prefix}': {e}")
        return deleted_count

    def read_bytes(self, destination_key: str) -> Optional[bytes]:
        key = destination_key.lstrip("/")
        try:
            resp = self.s3_client.get_object(Bucket=self.bucket, Key=key)
            return resp["Body"].read()
        except Exception as e:
            logger.error(f"[Storage][S3] Failed to read s3://{self.bucket}/{key}: {e}")
            return None

    def file_exists(self, destination_key: str) -> bool:
        key = destination_key.lstrip("/")
        try:
            self.s3_client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False


def get_storage_provider() -> BaseStorageProvider:
    """Factory creating the configured storage provider (S3 or local fallback)."""
    if settings.STORAGE_BACKEND.lower() == "s3" and settings.S3_ACCESS_KEY_ID:
        try:
            return S3StorageProvider()
        except Exception as e:
            logger.warning(f"[Storage] S3 initialization failed ({e}), falling back to LocalStorageProvider.")
            return LocalStorageProvider()
    return LocalStorageProvider()


# Global storage singleton
default_storage_provider: BaseStorageProvider = get_storage_provider()
