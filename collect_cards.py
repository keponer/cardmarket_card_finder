import argparse
import sys
import urllib.request
import urllib.parse
import mimetypes
import os
import uuid
import re
import base64
from typing import Optional, Dict, Iterable, List, Tuple
from html.parser import HTMLParser


def fetch_with_cookie(
    url: str,
    cookie_header_value: str,
    timeout_seconds: float = 30.0,
    extra_headers: Optional[Dict[str, str]] = None,
) -> str:
    """
    Perform a GET request to the given URL including a Cookie header and
    return the response body as text. Tries to respect the response charset
    when available; falls back to UTF-8.
    """
    headers = {
        "User-Agent": "card-market-finder/1.0 (+https://localhost) Python-urllib",
        "Accept": "*/*",
    }
    if cookie_header_value:
        headers["Cookie"] = cookie_header_value
    if extra_headers:
        headers.update(extra_headers)

    request = urllib.request.Request(url=url, headers=headers, method="GET")

    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw_bytes: bytes = response.read()
        content_type: Optional[str] = response.headers.get("Content-Type")

        # Try to extract charset from Content-Type header
        encoding: str = "utf-8"
        if content_type and "charset=" in content_type:
            try:
                encoding = content_type.split("charset=")[-1].split(";")[0].strip()
            except Exception:
                # Keep default utf-8 if parsing fails
                encoding = "utf-8"

        return raw_bytes.decode(encoding, errors="replace")


def parse_key_value_list(pairs: Iterable[str]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for item in pairs:
        if "=" not in item:
            raise ValueError(f"expected key=value, got: {item}")
        key, value = item.split("=", 1)
        if not key:
            raise ValueError(f"empty key in: {item}")
        result[key] = value
    return result


class HiddenInputParser(HTMLParser):
    def __init__(self, target_names: Iterable[str]):
        super().__init__()
        # Normalize target names to lowercase for case-insensitive match
        self.target_names = {name.lower() for name in target_names}
        self.found_values: Dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "input":
            return
        attrs_dict: Dict[str, Optional[str]] = {k.lower(): v for k, v in attrs}
        input_type = (attrs_dict.get("type") or "").lower()
        if input_type and input_type != "hidden":
            return
        name = attrs_dict.get("name")
        if not name:
            return
        lname = name.lower()
        if lname not in self.target_names:
            return
        value = attrs_dict.get("value") or ""
        self.found_values[name] = value


def extract_hidden_input_values(html_text: str, required_names: List[str]) -> Dict[str, str]:
    parser = HiddenInputParser(required_names)
    parser.feed(html_text)
    values = {name: parser.found_values.get(name) for name in required_names}
    missing = [k for k, v in values.items() if v is None]
    if missing:
        raise ValueError(f"Missing required hidden inputs: {', '.join(missing)}")
    # Cast None away for mypy; guaranteed present here
    return {k: v or "" for k, v in values.items()}


class SellerItemParser(HTMLParser):
    """Collect seller profile hrefs and prices.

    Two strategies:
    1) Legacy: span.seller-name.d-flex → span.d-flex.has-content-centered.me-1 → a[href]
    2) Preferred: within div.col-sellerProductInfo.col, capture descendant a[href] and
       sibling/descendant span with classes including color-primary and fw-bold (price)
    """

    def __init__(self):
        super().__init__()
        self.stack: List[Tuple[str, List[str]]] = []
        self.items: List[Tuple[str, Optional[str]]] = []  # (href, price)

        # State for current seller block (div.col-sellerProductInfo.col)
        self.in_seller_block_depth: int = 0
        self.seller_block_nesting: int = 0  # counts all tags inside the seller block
        self.current_href: Optional[str] = None
        self.capture_price_text: bool = False
        self.price_span_depth: int = 0
        self.current_price_parts: List[str] = []

    @staticmethod
    def _classes(attrs: List[Tuple[str, Optional[str]]]) -> List[str]:
        for k, v in attrs:
            if k.lower() == "class" and v:
                return [c for c in v.split() if c]
        return []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        classes = self._classes(attrs)
        self.stack.append((tag.lower(), classes))

        # Detect start of seller block
        if tag.lower() == "div" and ("col-sellerProductInfo" in classes and "col" in classes):
            self.in_seller_block_depth += 1
            self.seller_block_nesting = 1
            self.current_href = None
            self.capture_price_text = False
            self.price_span_depth = 0
            self.current_price_parts = []
        elif self.in_seller_block_depth > 0:
            # Any tag inside the seller block increases nesting
            self.seller_block_nesting += 1

        # Capture href inside seller block
        if tag.lower() == "a":
            if self.in_seller_block_depth > 0:
                for k, v in attrs:
                    if k.lower() == "href" and v:
                        if not self.current_href:
                            self.current_href = v
                        break
            else:
                # Legacy path: under seller-name area
                has_seller_root = any(
                    t == "span" and ("seller-name" in cls and "d-flex" in cls)
                    for t, cls in self.stack[:-1]
                )
                has_inner = any(
                    t == "span" and all(c in cls for c in ["d-flex", "has-content-centered", "me-1"])
                    for t, cls in self.stack[:-1]
                )
                if has_seller_root and has_inner:
                    for k, v in attrs:
                        if k.lower() == "href" and v:
                            self.items.append((v, None))
                            break

        # Capture price span within seller block
        if self.in_seller_block_depth > 0 and tag.lower() == "span":
            if ("color-primary" in classes) and ("fw-bold" in classes):
                self.capture_price_text = True
                self.price_span_depth = 1
            elif self.capture_price_text:
                # Nested span within price span
                self.price_span_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        # Close seller block: flush item
        if self.in_seller_block_depth > 0:
            # Any end tag reduces nesting; if we close the outermost, finalize item
            self.seller_block_nesting -= 1
            if self.seller_block_nesting == 0:
                price_text = "".join(self.current_price_parts).strip()
                if self.current_href:
                    self.items.append((self.current_href, price_text or None))
                self.current_href = None
                self.capture_price_text = False
                self.price_span_depth = 0
                self.current_price_parts = []
                self.in_seller_block_depth = 0

        # Manage generic stack and price capture ending
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag_lower:
                # If we are closing a span, adjust price capture depth
                if tag_lower == "span" and self.capture_price_text:
                    if self.price_span_depth > 0:
                        self.price_span_depth -= 1
                    if self.price_span_depth == 0:
                        self.capture_price_text = False
                del self.stack[i:]
                break

    def handle_data(self, data: str) -> None:
        if self.capture_price_text and self.in_seller_block_depth > 0:
            self.current_price_parts.append(data)


def extract_seller_href_prices(html_text: str) -> List[Tuple[str, Optional[str]]]:
    parser = SellerItemParser()
    parser.feed(html_text)
    # Return all occurrences; normalize whitespace in price
    result: List[Tuple[str, Optional[str]]] = []
    for href, price in parser.items:
        norm_price = price.strip() if isinstance(price, str) else price
        result.append((href, norm_price))
    return result

def parse_key_value_pairs(pairs: Iterable[str]) -> List[Tuple[str, str]]:
    result: List[Tuple[str, str]] = []
    for item in pairs:
        if "=" not in item:
            raise ValueError(f"expected field=path, got: {item}")
        field, path = item.split("=", 1)
        if not field:
            raise ValueError(f"empty field in: {item}")
        if not path:
            raise ValueError(f"empty path in: {item}")
        result.append((field, path))
    return result


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
    """
    Convert pasted cookies into a valid Cookie header value.
    - Accepts either a ready-to-use 'name=value; name2=value2' string
    - Or a pasted Set-Cookie string and strips attributes like path, domain, expires, Secure, HttpOnly, SameSite
    Keeps only semicolon-separated key=value pairs that look like cookies.
    """
    if not raw:
        return ""

    parts = [p.strip() for p in raw.split(";") if p.strip()]
    kept: List[str] = []
    skip_names = {"path", "domain", "expires", "max-age", "secure", "httponly", "samesite", "priority"}
    for part in parts:
        if "=" not in part:
            # attribute without value like "Secure" or "HttpOnly"
            continue
        name, value = part.split("=", 1)
        lname = name.strip().lower()
        if lname in skip_names:
            continue
        kept.append(f"{name.strip()}={value.strip()}")
    return "; ".join(kept)

def build_multipart_body(fields: Dict[str, str], files: List[Tuple[str, str]]) -> Tuple[bytes, str]:
    boundary: str = "----cmf-" + uuid.uuid4().hex
    crlf = "\r\n"
    body_parts: List[bytes] = []

    def add(text: str) -> None:
        body_parts.append(text.encode("utf-8"))

    # Text fields
    for name, value in fields.items():
        add(f"--{boundary}{crlf}")
        add(f"Content-Disposition: form-data; name=\"{name}\"{crlf}{crlf}")
        add(f"{value}{crlf}")

    # File fields
    for field_name, file_path in files:
        filename = os.path.basename(file_path)
        guessed_type, _ = mimetypes.guess_type(filename)
        content_type = guessed_type or "application/octet-stream"

        add(f"--{boundary}{crlf}")
        add(
            f"Content-Disposition: form-data; name=\"{field_name}\"; filename=\"{filename}\"{crlf}"
        )
        add(f"Content-Type: {content_type}{crlf}{crlf}")
        with open(file_path, "rb") as f:
            body_parts.append(f.read())
        add(crlf)

    add(f"--{boundary}--{crlf}")

    body_bytes = b"".join(body_parts)
    content_type_header = f"multipart/form-data; boundary={boundary}"
    return body_bytes, content_type_header


def post_multipart(
    url: str,
    body_bytes: bytes,
    content_type_header: str,
    cookie_header_value: Optional[str] = None,
    extra_headers: Optional[Dict[str, str]] = None,
    timeout_seconds: float = 60.0,
) -> str:
    headers = {
        "User-Agent": "card-market-finder/1.0 (+https://localhost) Python-urllib",
        "Accept": "*/*",
        "Content-Type": content_type_header,
        "Content-Length": str(len(body_bytes)),
    }
    if cookie_header_value:
        headers["Cookie"] = cookie_header_value
    if extra_headers:
        headers.update(extra_headers)

    req = urllib.request.Request(url=url, data=body_bytes, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
        raw_bytes: bytes = response.read()
        content_type: Optional[str] = response.headers.get("Content-Type")
        encoding: str = "utf-8"
        if content_type and "charset=" in content_type:
            try:
                encoding = content_type.split("charset=")[-1].split(";")[0].strip()
            except Exception:
                encoding = "utf-8"
        return raw_bytes.decode(encoding, errors="replace")


def parse_ajax_response(text: str) -> Tuple[str, str]:
    """
    Extract <rows> (base64 payload) and <newPage> from an <ajaxResponse> payload.
    Returns tuple (decoded_rows_html, new_page_value).
    Raises ValueError if required tags are missing or rows cannot be decoded.
    """
    def extract_tag(tag: str) -> Optional[str]:
        pattern = rf"<\s*{tag}[^>]*>([\s\S]*?)<\s*/\s*{tag}\s*>"
        m = re.search(pattern, text, flags=re.IGNORECASE)
        return m.group(1) if m else None

    rows_b64 = extract_tag("rows")
    new_page = extract_tag("newPage")
    if rows_b64 is None or new_page is None:
        missing = []
        if rows_b64 is None:
            missing.append("rows")
        if new_page is None:
            missing.append("newPage")
        raise ValueError(f"Missing tags: {', '.join(missing)}")

    try:
        decoded_bytes = base64.b64decode(rows_b64, validate=False)
        decoded_rows = decoded_bytes.decode("utf-8", errors="replace")
    except Exception as exc:
        raise ValueError(f"Failed to decode rows base64: {exc}")

    return decoded_rows, new_page.strip()


def paginate_load_more(
    post_url: str,
    cmtkn: str,
    id_product: str,
    cookie_header_value: Optional[str],
    extra_headers: Optional[Dict[str, str]] = None,
) -> None:
    """Loop POSTing page requests until newPage == -1; prints sellerHref entries and newPage per page."""
    current_page: str = "1"
    while True:
        fields = {
            "__cmtkn": cmtkn,
            "idProduct": id_product,
            "page": current_page,
            "filterSettings": "[]",
        }
        body_bytes, content_type_header = build_multipart_body(fields, [])
        response_text = post_multipart(
            post_url,
            body_bytes,
            content_type_header,
            cookie_header_value=cookie_header_value,
            extra_headers=extra_headers,
        )
        decoded_rows, new_page = parse_ajax_response(response_text)
        seller_items = extract_seller_href_prices(decoded_rows)
        if seller_items:
            for href, price in seller_items:
                suffix = f" | price={price}" if price else ""
                print(f"sellerHref={href}{suffix}")
        else:
            # Keep going even if a page returns no hrefs
            print("Error: no seller hrefs found", file=sys.stderr)
        print(f"newPage={new_page}")
        if new_page.strip() == "-1":
            break
        current_page = new_page.strip()


def paginate_load_more_collect(
    post_url: str,
    cmtkn: str,
    id_product: str,
    cookie_header_value: Optional[str],
    extra_headers: Optional[Dict[str, str]] = None,
) -> List[Tuple[str, Optional[str]]]:
    """Same as paginate_load_more, but returns a list of (href, price) allowing duplicates."""
    collected: List[Tuple[str, Optional[str]]] = []
    current_page: str = "1"
    while True:
        fields = {
            "__cmtkn": cmtkn,
            "idProduct": id_product,
            "page": current_page,
            "filterSettings": "[]",
        }
        body_bytes, content_type_header = build_multipart_body(fields, [])
        response_text = post_multipart(
            post_url,
            body_bytes,
            content_type_header,
            cookie_header_value=cookie_header_value,
            extra_headers=extra_headers,
        )
        decoded_rows, new_page = parse_ajax_response(response_text)
        for href, price in extract_seller_href_prices(decoded_rows):
            collected.append((href, price))
        if new_page.strip() == "-1":
            break
        current_page = new_page.strip()
    return collected


def collect_seller_hrefs_for_url(url: str, cookie: str) -> List[Tuple[str, Optional[str]]]:
    """Fetch product page, extract token and id, collect seller (href, price) pairs from initial and paginated results, keeping duplicates."""
    body_text: str = fetch_with_cookie(url, cookie, extra_headers=None) if cookie else fetch_with_cookie(url, "", extra_headers=None)
    targets = ["__cmtkn", "idProduct", "isSingle"]
    values = extract_hidden_input_values(body_text, targets)
    items: List[Tuple[str, Optional[str]]] = list(extract_seller_href_prices(body_text))
    post_url = "https://www.cardmarket.com/en/Pokemon/AjaxAction/Product_LoadMoreArticles"
    items.extend(
        paginate_load_more_collect(post_url, values["__cmtkn"], values["idProduct"], cookie if cookie else None, None)
    )
    return items

def main() -> int:
    parser = argparse.ArgumentParser(description="Hello World, GET with Cookie, or multipart/form-data POST.")
    # GET options
    parser.add_argument("--url", help="URL to GET when provided with --cookie")
    parser.add_argument("--cookie", help="Cookie header value to include in the request")
    parser.add_argument(
        "--header",
        action="append",
        help="Extra header as 'Name: value'. Repeatable; applies to GET/POST.",
    )
    # POST options
    parser.add_argument("--post-url", help="URL to POST multipart/form-data to")
    parser.add_argument(
        "--form",
        action="append",
        help="Form field as key=value. May be repeated.",
    )
    parser.add_argument(
        "--file",
        action="append",
        help="File field as fieldName=path/to/file. May be repeated.",
    )
    args = parser.parse_args()

    # Normalize extra headers from CLI
    try:
        cli_headers: Dict[str, str] = parse_headers(args.header or [])
    except ValueError as exc:
        print(f"Invalid --header: {exc}", file=sys.stderr)
        return 2

    # Multipart/form-data POST flow
    if args.post_url or args.form or args.file:
        if not args.post_url:
            print("Error: --post-url is required when using --form/--file.", file=sys.stderr)
            return 2
        try:
            fields: Dict[str, str] = parse_key_value_list(args.form or [])
        except ValueError as exc:
            print(f"Invalid --form: {exc}", file=sys.stderr)
            return 2
        try:
            file_specs: List[Tuple[str, str]] = parse_key_value_pairs(args.file or [])
        except ValueError as exc:
            print(f"Invalid --file: {exc}", file=sys.stderr)
            return 2
        try:
            body_bytes, content_type_header = build_multipart_body(fields, file_specs)
            text = post_multipart(
                args.post_url,
                body_bytes,
                content_type_header,
                cookie_header_value=args.cookie,
                extra_headers=cli_headers,
            )
            try:
                decoded_rows, new_page = parse_ajax_response(text)
                # Extract seller hrefs and prices from decoded rows HTML
                seller_items = extract_seller_href_prices(decoded_rows)
                if seller_items:
                    for href, price in seller_items:
                        suffix = f" | price={price}" if price else ""
                        print(f"sellerHref={href}{suffix}")
                else:
                    print("Error: no seller hrefs found", file=sys.stderr)
                print(f"newPage={new_page}")
            except ValueError as parse_err:
                print(f"Error: {parse_err}", file=sys.stderr)
                return 1
            return 0
        except Exception as exc:
            print(f"Request failed: {exc}", file=sys.stderr)
            return 1

    # GET with Cookie flow
    if args.url or args.cookie:
        if not args.url or not args.cookie:
            print("Error: both --url and --cookie must be provided.", file=sys.stderr)
            return 2
        try:
            body_text: str = fetch_with_cookie(args.url, args.cookie, extra_headers=cli_headers)
            targets = ["__cmtkn", "idProduct", "isSingle"]
            try:
                values = extract_hidden_input_values(body_text, targets)
                for k in targets:
                    print(f"{k}={values[k]}")
            except ValueError as parse_err:
                print(f"Error: {parse_err}", file=sys.stderr)
                return 1

            seller_items = extract_seller_href_prices(body_text)
            if seller_items:
                for href, price in seller_items:
                    suffix = f" | price={price}" if price else ""
                    print(f"sellerHref={href}{suffix}")
            else:
                print("Error: no seller hrefs found", file=sys.stderr)
                return 1
            return 0
        except Exception as exc:
            print(f"Request failed: {exc}", file=sys.stderr)
            return 1

    # Default interactive two-step flow when no flags are provided
    try:
        print("Step 1: Provide request details")
        urls_raw = input("Enter one or more URLs to GET (comma-separated): ").strip()
        cookie_raw = input(
            "Enter Cookie header value(s). Paste only cookie pairs (e.g., name=value; name2=value2).\n"
            "If you pasted a Set-Cookie string with attributes, they will be ignored.\n> "
        ).strip()
        cookie = sanitize_cookie_header(cookie_raw)
        if not urls_raw:
            print("Error: at least one URL is required for the interactive flow.", file=sys.stderr)
            return 2
        # Split URLs
        url_list = [u.strip() for u in urls_raw.split(",") if u.strip()]
        if not url_list:
            print("Error: no valid URLs provided.", file=sys.stderr)
            return 2

        # For each URL, collect the full list of seller items (initial + paginated)
        all_lists: List[List[Tuple[str, Optional[str]]]] = []
        for u in url_list:
            try:
                items_list = collect_seller_hrefs_for_url(u, cookie)  # list of (href, price), may contain duplicates
                all_lists.append(items_list)
            except Exception as exc:
                print(f"Error processing {u}: {exc}", file=sys.stderr)
                return 1

        # Compute intersection across all URLs by href only, but keep duplicate prices per URL
        if not all_lists:
            print("Error: no results collected.", file=sys.stderr)
            return 1
        href_sets = [set(h for (h, _p) in lst) for lst in all_lists]
        common_hrefs = set.intersection(*href_sets) if len(href_sets) > 1 else href_sets[0]
        if common_hrefs:
            # For deterministic output, sort by href
            for href in sorted(common_hrefs):
                # Collect all prices across all URL results for this href, preserving duplicates and order within each URL
                all_prices: List[str] = []
                for lst in all_lists:
                    for (h, p) in lst:
                        if h == href and p:
                            all_prices.append(p)
                prices_repr = "[" + ", ".join(all_prices) + "]"
                print(f"sellerHref={href} | prices={prices_repr}")
        else:
            print("Error: no common seller profiles found across provided URLs", file=sys.stderr)
            return 1
        return 0
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130


if __name__ == "__main__":
    sys.exit(main())


