"""Local development and S3-compatible object storage behind one interface."""
import os
from pathlib import Path
from urllib.parse import quote

class StorageService:
    def __init__(self):
        self.endpoint = os.getenv("STORAGE_ENDPOINT")
        self.bucket = os.getenv("STORAGE_BUCKET", "ai-measurer")
        self.local_root = Path(os.getenv("LOCAL_STORAGE_PATH", "./uploads"))
        self.local_root.mkdir(parents=True, exist_ok=True)
        self.client = None
        if self.endpoint:
            import boto3
            self.client = boto3.client("s3", endpoint_url=self.endpoint,
                aws_access_key_id=os.getenv("STORAGE_ACCESS_KEY"),
                aws_secret_access_key=os.getenv("STORAGE_SECRET_KEY"),
                region_name=os.getenv("STORAGE_REGION", "ru-1"))

    def save(self, key: str, content: bytes, mime_type: str) -> None:
        if self.client:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=content, ContentType=mime_type)
        else:
            path = self.local_root / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def get(self, key: str) -> bytes:
        if self.client:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        return (self.local_root / key).read_bytes()

    def delete(self, key: str) -> None:
        if self.client:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        else:
            (self.local_root / key).unlink(missing_ok=True)

    def signed_url(self, key: str, expires_seconds: int = 900) -> str:
        if not self.client:
            return f"/admin/api/photos/{quote(key, safe='/')}"
        return self.client.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_seconds)
