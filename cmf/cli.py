import argparse
import sys
from typing import Dict, List, Optional, Tuple

from .collector import collect_seller_items_for_url
from .http_client import http_get
from .multipart import build_multipart_body, http_post_multipart
from .parsers import extract_hidden_input_values, extract_seller_href_prices, parse_ajax_response
from .utils import parse_headers, sanitize_cookie_header


def run_cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Card Market Finder CLI")
    parser.add_argument("--url", help="URL to GET when provided with --cookie")
    parser.add_argument("--cookie", help="Cookie header value to include in the request")
    parser.add_argument("--header", action="append", help="Extra header as 'Name: value'. Repeatable; applies to GET/POST.")

    parser.add_argument("--post-url", help="URL to POST multipart/form-data to")
    parser.add_argument("--form", action="append", help="Form field as key=value. May be repeated.")
    parser.add_argument("--file", action="append", help="File field as fieldName=path/to/file. May be repeated.")

    args = parser.parse_args(argv)

    try:
        cli_headers: Dict[str, str] = parse_headers(args.header or [])
    except ValueError as exc:
        print(f"Invalid --header: {exc}", file=sys.stderr)
        return 2

    # Multipart POST path
    if args.post_url or args.form or args.file:
        if not args.post_url:
            print("Error: --post-url is required when using --form/--file.", file=sys.stderr)
            return 2
        fields: Dict[str, str] = {}
        if args.form:
            for item in args.form:
                if "=" not in item:
                    print(f"Invalid --form: {item}", file=sys.stderr)
                    return 2
                k, v = item.split("=", 1)
                fields[k] = v
        files: List[Tuple[str, str]] = []
        if args.file:
            for item in args.file:
                if "=" not in item:
                    print(f"Invalid --file: {item}", file=sys.stderr)
                    return 2
                k, v = item.split("=", 1)
                files.append((k, v))
        body, ctype = build_multipart_body(fields, files)
        text = http_post_multipart(args.post_url, body, ctype, cookie=args.cookie, extra_headers=cli_headers)
        rows_html, new_page = parse_ajax_response(text)
        seller_items = extract_seller_href_prices(rows_html)
        for href, price in seller_items:
            suffix = f" | price={price}" if price else ""
            print(f"sellerHref={href}{suffix}")
        print(f"newPage={new_page}")
        return 0

    # GET path
    if args.url or args.cookie:
        if not args.url or not args.cookie:
            print("Error: both --url and --cookie must be provided.", file=sys.stderr)
            return 2
        html = http_get(args.url, args.cookie, cli_headers)
        values = extract_hidden_input_values(html, ["__cmtkn", "idProduct", "isSingle"])
        for k in ["__cmtkn", "idProduct", "isSingle"]:
            print(f"{k}={values[k]}")
        for href, price in extract_seller_href_prices(html):
            suffix = f" | price={price}" if price else ""
            print(f"sellerHref={href}{suffix}")
        return 0

    # Interactive multi-URL with loop; reuse same cookie
    print("Step 1: Provide request details")
    cookie_raw = input(
        "Enter Cookie header value(s). Paste only cookie pairs (e.g., name=value; name2=value2).\n"
        "If you pasted a Set-Cookie string with attributes, they will be ignored.\n> "
    ).strip()
    cookie = sanitize_cookie_header(cookie_raw)

    while True:
        urls_raw = input("Enter one or more URLs to GET (comma-separated), or press Enter to quit: ").strip()
        if not urls_raw:
            break
        url_list = [u.strip() for u in urls_raw.split(",") if u.strip()]
        if not url_list:
            print("Error: no valid URLs provided.", file=sys.stderr)
            continue

        per_url_lists: List[List[Tuple[str, Optional[str]]]] = []
        for u in url_list:
            try:
                per_url_lists.append(collect_seller_items_for_url(u, cookie))
            except Exception as exc:
                print(f"Error processing {u}: {exc}", file=sys.stderr)
                per_url_lists = []
                break
        if not per_url_lists:
            continue

        href_sets = [set(h for (h, _p) in lst) for lst in per_url_lists]
        common_hrefs = set.intersection(*href_sets) if len(href_sets) > 1 else href_sets[0]
        if not common_hrefs:
            print("Error: no common seller profiles found across provided URLs", file=sys.stderr)
            continue

        for href in sorted(common_hrefs):
            prices: List[str] = []
            for lst in per_url_lists:
                for (h, p) in lst:
                    if h == href and p:
                        prices.append(p)
            print(f"sellerHref={href} | prices=[{', '.join(prices)}]")

    return 0
