from typing import Dict, List, Optional, Tuple

from .multipart import build_multipart_body, http_post_multipart
from .parsers import parse_ajax_response, extract_seller_href_prices


def paginate_load_more_collect(
    post_url: str,
    cmtkn: str,
    id_product: str,
    cookie: Optional[str],
    extra_headers: Optional[Dict[str, str]] = None,
) -> List[Tuple[str, Optional[str]]]:
    """Collect seller items across all pages until newPage == -1, preserving duplicates."""
    collected: List[Tuple[str, Optional[str]]] = []
    page: str = "1"
    while True:
        fields = {"__cmtkn": cmtkn, "idProduct": id_product, "page": page, "filterSettings": "[]"}
        body, ctype = build_multipart_body(fields, [])
        text = http_post_multipart(post_url, body, ctype, cookie=cookie, extra_headers=extra_headers)
        rows_html, new_page = parse_ajax_response(text)
        collected.extend(extract_seller_href_prices(rows_html))
        if new_page.strip() == "-1":
            break
        page = new_page.strip()
    return collected
