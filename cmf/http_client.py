from typing import Dict, Optional
import urllib.request

DEFAULT_UA = "card-market-finder/1.0 (+https://localhost) Python-urllib"


def http_get(url: str, cookie: str = "", extra_headers: Optional[Dict[str, str]] = None, timeout_seconds: float = 30.0) -> str:
    """Perform an HTTP GET and return response text.

    Args:
        url: Target URL.
        cookie: Raw Cookie header value (e.g., "name=value; name2=value2").
        extra_headers: Additional headers to include.
        timeout_seconds: Socket timeout.
    """
    headers: Dict[str, str] = {"User-Agent": DEFAULT_UA, "Accept": "*/*"}
    if cookie:
        headers["Cookie"] = cookie
    if extra_headers:
        headers.update(extra_headers)

    req = urllib.request.Request(url=url, headers=headers, method="GET")
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
