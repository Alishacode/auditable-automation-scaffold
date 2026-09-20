import boto3
from app.core.config import settings

s3 = boto3.client(
    "s3",
    endpoint_url=settings.object_storage_endpoint,
    aws_access_key_id="minio",
    aws_secret_access_key="minio12345",
)

def upload_document(file_bytes: bytes, key: str) -> None:
    s3.put_object(Bucket=settings.object_storage_bucket, Key=key, Body=file_bytes)

def fetch_document(key: str) -> bytes:
    return s3.get_object(Bucket=settings.object_storage_bucket, Key=key)["Body"].read()