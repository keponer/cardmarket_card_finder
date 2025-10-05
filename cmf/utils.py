from typing import Dict, Iterable


def parse_headers(pairs: Iterable[str]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for raw in pairs:
        if ":" not in raw:
            raise ValueError(f"expected 'Name: value', got: {raw}")
        name, value = raw.split(":", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            raise ValueError(f"empty header name in: {raw}")
        headers[name] = value
    return headers


def sanitize_cookie_header(raw: str) -> str:
    """Convert pasted cookies or Set-Cookie content into a Cookie header value."""
    if not raw:
        return ""
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    kept = []
    skip = {"path", "domain", "expires", "max-age", "secure", "httponly", "samesite", "priority"}
    for part in parts:
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        if name.strip().lower() in skip:
            continue
        kept.append(f"{name.strip()}={value.strip()}")
    return "; ".join(kept)
