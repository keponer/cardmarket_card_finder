from typing import Dict, Iterable, List, Optional, Tuple
from html.parser import HTMLParser
import base64
import re


class HiddenInputParser(HTMLParser):
    """HTML parser that collects values for specific hidden input names."""

    def __init__(self, target_names: Iterable[str]):
        super().__init__()
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
    return {k: v or "" for k, v in values.items()}


class SellerItemParser(HTMLParser):
    """Collect seller profile hrefs and prices.

    Strategies:
      - Legacy: span.seller-name.d-flex → span.d-flex.has-content-centered.me-1 → a[href]
      - Preferred: within div.col-sellerProductInfo.col, capture descendant a[href] and
        sibling/descendant span with classes including color-primary and fw-bold (price)
    """

    def __init__(self):
        super().__init__()
        self.stack: List[Tuple[str, List[str]]] = []
        self.items: List[Tuple[str, Optional[str]]] = []  # (href, price)
        self.in_seller_block_depth: int = 0
        self.seller_block_nesting: int = 0
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
            self.seller_block_nesting += 1

        # Capture href inside seller block or legacy path
        if tag.lower() == "a":
            if self.in_seller_block_depth > 0:
                for k, v in attrs:
                    if k.lower() == "href" and v and not self.current_href:
                        self.current_href = v
                        break
            else:
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
                self.price_span_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if self.in_seller_block_depth > 0:
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

        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag_lower:
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
    result: List[Tuple[str, Optional[str]]] = []
    for href, price in parser.items:
        norm_price = price.strip() if isinstance(price, str) else price
        result.append((href, norm_price))
    return result


def parse_ajax_response(text: str) -> Tuple[str, str]:
    """Extract <rows> (base64) and <newPage> from an <ajaxResponse> payload."""
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

    decoded = base64.b64decode(rows_b64, validate=False)
    rows_html = decoded.decode("utf-8", errors="replace")
    return rows_html, new_page.strip()
