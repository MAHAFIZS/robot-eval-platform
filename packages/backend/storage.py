import os
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import urlparse

@dataclass(frozen=True)
class ArtifactRef:
    uri: str                 # s3://bucket/key OR file:///abs/path OR relative path
    name: str                # e.g., report.html
    content_type: Optional[str] = None

def parse_s3_uri(uri: str) -> Tuple[str, str]:
    # uri: s3://bucket/key
    if not uri.startswith("s3://"):
        raise ValueError(f"Not an s3 uri: {uri}")
    path = uri[len("s3://"):]
    bucket, key = path.split("/", 1)
    return bucket, key

def is_file_uri(uri: str) -> bool:
    return uri.startswith("file://")

def file_uri_to_path(uri: str) -> str:
    return uri.replace("file://", "", 1)

def safe_join(base_dir: str, rel: str) -> str:
    # prevent path traversal when serving local artifacts
    base = os.path.abspath(base_dir)
    target = os.path.abspath(os.path.join(base, rel))
    if not target.startswith(base + os.sep) and target != base:
        raise ValueError("Invalid artifact path")
    return target
