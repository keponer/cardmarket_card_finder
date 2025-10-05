from typing import Dict, List, Optional, Tuple
import mimetypes
import os
import urllib.request
import uuid

from .http_client import DEFAULT_UA


def build_multipart_body(fields: Dict[str, str], files: List[Tuple[str, str]]) -> Tuple[bytes, str]:
    """Build a multipart/form-data body and return (body_bytes, content_type)."""
    boundary = "----cmf-" + uuid.uuid4().hex
    crlf = "\r\n"
    parts: List[bytes] = []

    def add(text: str) -> None:
        parts.append(text.encode("utf-8"))

    for name, value in fields.items():
        add(f"--{boundary}{crlf}")
        add(f"Content-Disposition: form-data; name=\"{name}\"{crlf}{crlf}")
        add(f"{value}{crlf}")

    for field_name, file_path in files:
        filename = os.path.basename(file_path)
        guessed_type, _ = mimetypes.guess_type(filename)
        content_type = guessed_type or "application/octet-stream"
        add(f"--{boundary}{crlf}")
        add(f"Content-Disposition: form-data; name=\"{field_name}\"; filename=\"{filename}\"{crlf}")
        add(f"Content-Type: {content_type}{crlf}{crlf}")
        with open(file_path, "rb") as f:
            parts.append(f.read())
        add(crlf)

    add(f"--{boundary}--{crlf}")
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def http_post_multipart(url: str, body_bytes: bytes, content_type_header: str, cookie: Optional[str] = None, extra_headers: Optional[Dict[str, str]] = None, timeout_seconds: float = 60.0) -> str:
    """POST a multipart/form-data request and return response text."""
    headers: Dict[str, str] = {
        "User-Agent": DEFAULT_UA,
        "Accept": "*/*",
        "Content-Type": content_type_header,
        "Content-Length": str(len(body_bytes)),
    }
    if cookie:
        headers["Cookie"] = cookie
    if extra_headers:
        headers.update(extra_headers)

    req = urllib.request.Request(url=url, data=body_bytes, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        raw = resp.read()
        content_type = resp.headers.get("Content-Type") or ""
        encoding = "utf-8"
        if "charset=" in content_type:
            try:
                encoding = content_type.split("charset=")[-1].split(";")[0].strip()
            except Exception:
                encoding = "utf-8"
        return raw.decode(encoding, errors="replace")
