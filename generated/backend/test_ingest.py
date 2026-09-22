"""Manual test: upload a local file to MinIO, then hit the ingest endpoint
to push it through the full pipeline (classify -> extract -> rules -> score)."""
import sys

import httpx

from app.services.storage import upload_document

def main(file_path: str):
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    key = f"test-uploads/{file_path.split(chr(92))[-1]}"  # handles Windows backslash paths
    upload_document(file_bytes, key)
    print(f"Uploaded to storage as key: {key}")

    response = httpx.post(
        "http://localhost:8000/api/v1/documents/ingest",
        params={"object_storage_key": key},
    )
    print("Ingest response:", response.status_code, response.json())


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python test_ingest.py <path-to-pdf>")
        sys.exit(1)
    main(sys.argv[1])