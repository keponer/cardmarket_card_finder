## Card Market Finder

This project contains a Python CLI, `collect_cards.py`, which delegates to the `cmf/` package and:

- Prints "Hello, World!" when run with no arguments.
- Optionally performs an HTTP GET request to a provided URL with a specified `Cookie` header and prints the response body.
- Optionally performs a multipart/form-data POST to a provided URL with form fields and file uploads.
- From GET responses that return HTML, extracts hidden inputs `__cmtkn`, `idProduct`, and `isSingle` (or errors if missing).
- Collects seller profile links and prices from `div.col-sellerProductInfo.col` (and legacy seller-name spans) and prints each as `sellerHref=... | price=...` (or an error if none found).
- Interactive mode supports multiple product URLs at once and prints only the seller profiles common to all provided URLs (intersection), paging via AJAX (`newPage`) through all result pages per URL. Prices list shows all occurrences across inputs.

The project uses only the Python standard library.

### Requirements

- Python 3.8+ (tested on Windows with PowerShell)

### Setup (recommended)

Create and use a virtual environment to isolate dependencies (even though this script uses only the standard library):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python -m pip install --upgrade pip
```

Deactivate when done:

```powershell
deactivate
```

### Usage

Run the CLI with no flags for an interactive multi-URL flow:

```powershell
.\.venv\Scripts\python collect_cards.py
# Step 1: you will be prompted for one or more URLs (comma-separated) and a Cookie header
# For each URL, tokens are extracted and AJAX pagination loads seller rows until newPage == -1
# Output prints only sellers common to ALL URLs, with prices aggregated per seller as a list
```

Fetch a URL with a Cookie header and print the response body:

```powershell
.\.venv\Scripts\python collect_cards.py --url "https://httpbin.org/get" --cookie "sessionid=abc123"
```

### Command-line arguments

- `--url` (optional): The URL to perform a GET request against. Required if `--cookie` is provided (non-interactive mode).
- `--cookie` (optional): The value for the `Cookie` header to include in the request. Required if `--url` is provided (non-interactive mode). May also be used with `--post-url` to include a Cookie header in the POST.
- `--header` (repeatable): Extra header as `Name: value`. Applies to both GET and POST.
- `--post-url` (optional): The URL to POST a multipart/form-data request to. Required when using `--form` and/or `--file`.
- `--form` (repeatable): Form field as `key=value`. May be repeated multiple times.
- `--file` (repeatable): File field as `fieldName=path/to/file`. May be repeated multiple times.

Behavior:
- If both `--url` and `--cookie` are provided, the script performs a GET request to `--url` with the `Cookie` header set to `--cookie`, and prints the response body using the declared response charset (or UTF-8 by default).
- If neither is provided, the CLI enters the interactive flow (prompt for URLs and a Cookie). For each URL, it extracts the required hidden inputs and seller links/prices from the initial page, then paginates POSTs to load additional rows until `newPage == -1`. It prints the intersection of seller profiles across all provided URLs, with all price occurrences listed per seller.
- If only one of the two flags is provided, the script prints an error and exits with code 2.
- If `--post-url` is provided (optionally with `--cookie`), the script sends a multipart/form-data POST request to that URL, including any `--form` fields and `--file` uploads; the response body is printed.

Exit codes:

- `0`: Success
- `1`: Request failed (network/HTTP/decoding error)
- `2`: Invalid arguments (e.g., only one of `--url`/`--cookie`, or using `--form`/`--file` without `--post-url`)

### Examples

```powershell
# Default behavior
.\.venv\Scripts\python collect_cards.py

# Perform a GET with a cookie (will attempt to extract hidden inputs from HTML)
.\.venv\Scripts\python collect_cards.py --url "https://example.com/page" --cookie "foo=bar"

# Perform a GET with extra headers (e.g., spoof User-Agent)
.\.venv\Scripts\python collect_cards.py --url "https://httpbin.org/headers" --cookie "foo=bar" --header "User-Agent: Mozilla/5.0"

# Multipart/form-data POST with form fields (echo service)
.\.venv\Scripts\python collect_cards.py --post-url https://postman-echo.com/post --form a=1 --form b=2

# Multipart/form-data POST with a file upload (PowerShell example)
$tmp = New-Item -ItemType File -Path "$env:TEMP\cmf_sample.txt" -Force; Set-Content -Path $tmp -Value "sample text"; \
.\.venv\Scripts\python collect_cards.py --post-url https://postman-echo.com/post --form note=hello --file upload=$tmp
```

### Notes

- Interactive cookie input: if you paste a full `Set-Cookie` line (with attributes like `path`, `expires`, `HttpOnly`, etc.), the CLI keeps only cookie `name=value` pairs and discards attributes to form a valid `Cookie` header.
- The script sets a simple `User-Agent` to avoid some servers rejecting requests with the default user agent.
- Response bodies are decoded using the charset declared in the `Content-Type` header if present; otherwise UTF-8 is used with replacement for undecodable bytes.
- No third-party dependencies are required.

### Updating this documentation

If new flags or behaviors are added, update these sections (Usage, Command-line arguments, Exit codes, and Examples).


