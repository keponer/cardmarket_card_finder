from typing import List, Optional, Tuple

from .http_client import http_get
from .parsers import extract_hidden_input_values, extract_seller_href_prices
from .pagination import paginate_load_more_collect

POST_URL = "https://www.cardmarket.com/en/Pokemon/AjaxAction/Product_LoadMoreArticles"


def collect_seller_items_for_url(url: str, cookie: str) -> List[Tuple[str, Optional[str]]]:
    """Collect (href, price) pairs from the product page and all paginated results, preserving duplicates."""
    html = http_get(url, cookie)
    values = extract_hidden_input_values(html, ["__cmtkn", "idProduct", "isSingle"])  # isSingle kept for parity
    items = list(extract_seller_href_prices(html))
    items.extend(paginate_load_more_collect(POST_URL, values["__cmtkn"], values["idProduct"], cookie or None, None))
    return items
