
import http.client
import ipaddress
import socket
import ssl
import threading
import time
from collections import defaultdict, deque
from html import escape
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

APP_NAME = "EAQ SEO Audit"
APP_VERSION = "1.2.0"

MAX_URL_LENGTH = 2048
MAX_HTML_BYTES = 1_000_000
REQUEST_TIMEOUT = 10
MAX_REDIRECTS = 3

RATE_LIMIT = 5
RATE_WINDOW = 60

app = FastAPI(
    title=APP_NAME,
    docs_url=None,
    redoc_url=None,
)

request_history = defaultdict(deque)
rate_lock = threading.Lock()

HTML_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EAQ SEO Audit — Free Website SEO Checker</title>
<meta name="description" content="Check essential on-page SEO elements with EAQ SEO Audit. Free website SEO analysis without registration.">
<style>
*{box-sizing:border-box}
body{margin:0;background:#f3f7fb;color:#182b43;
font-family:Arial,Helvetica,sans-serif;line-height:1.65}
header{background:#10243e;color:white;padding:26px 18px}
.wrap{max-width:920px;margin:auto;padding:0 18px}
.brand{font-size:25px;font-weight:800;letter-spacing:.3px}
.brand span{color:#48d4c2}
header p{margin:5px 0 0;color:#d2deeb}
main{padding:38px 0}
.card{background:white;border:1px solid #e0e8f0;border-radius:16px;
padding:25px;margin-bottom:22px;box-shadow:0 5px 22px #142a4310}
h1{font-size:30px;line-height:1.25;margin:0 0 12px}
h2{font-size:21px;margin:0 0 14px}
.muted{color:#617187}
label{display:block;font-weight:700;margin:18px 0 7px}
input{width:100%;padding:14px;border:1px solid #cbd7e4;
border-radius:9px;font-size:16px}
button{margin-top:14px;background:#087e8b;color:white;border:0;
padding:13px 21px;border-radius:9px;font-size:16px;
font-weight:700;cursor:pointer}
button:hover{background:#066b76}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
gap:13px}
.metric{padding:15px;border-radius:10px;background:#f5f8fb;
border:1px solid #e5ebf2;overflow-wrap:anywhere}
.metric strong{display:block;margin-bottom:5px}
.status{font-weight:700}
.pass{color:#087a53}.fail{color:#b45309}.info{color:#52677d}
.score{font-size:38px;font-weight:800;color:#087e8b}
ul{padding-left:22px}
li{margin:8px 0}
footer{text-align:center;padding:25px;color:#617187;font-size:13px}
a{color:#087e8b}
.notice{background:#edf8f7;padding:13px;border-radius:9px}
</style>
</head>
<body>
<header><div class="wrap">
<div class="brand">EAQ<span>.io</span> SEO Audit</div>
<p>Analyze. Optimize. Grow.</p>
</div></header>
<main class="wrap">
<section class="card">
<h1>Free Website SEO Checker</h1>
<p class="muted">Check essential on-page SEO elements without creating an account.</p>
<form method="post" action="/audit">
<label for="url">Website URL</label>
<input id="url" name="url" type="text" maxlength="2048"
placeholder="https://example.com" required autocomplete="url">
<button type="submit">Analyze Website</button>
</form>
<p class="muted">Free basic checks are limited to help prevent abuse.
This report is an automated technical review, not a Google ranking score.</p>
</section>
__RESULT__
</main>
<footer>EAQ SEO Audit · Basic on-page analysis</footer>
</body>
</html>
"""


def check_rate_limit(client_ip: str) -> bool:
    now = time.monotonic()

    with rate_lock:
        history = request_history[client_ip]

        while history and now - history[0] >= RATE_WINDOW:
            history.popleft()

        if len(history) >= RATE_LIMIT:
            return False

        history.append(now)
        return True


def normalize_and_validate_url(raw_url: str) -> str:
    if not raw_url or len(raw_url) > MAX_URL_LENGTH:
        raise ValueError("Please enter a valid website URL.")

    raw_url = raw_url.strip()

    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw_url):
        raise ValueError("The URL contains invalid characters.")

    if "://" not in raw_url:
        raw_url = "https://" + raw_url

    try:
        parsed = urlsplit(raw_url)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("The URL format is invalid.")

    if scheme not in ("http", "https"):
        raise ValueError("Only HTTP and HTTPS websites are supported.")

    if not hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("Please enter a public website URL without credentials.")

    if port is not None and port != (443 if scheme == "https" else 80):
        raise ValueError("Only standard HTTP and HTTPS ports are allowed.")

    hostname = hostname.rstrip(".").lower()

    if not hostname or "%" in hostname:
        raise ValueError("The hostname is invalid.")

    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError("The hostname is invalid.")

    try:
        ipaddress.ip_address(hostname)
        raise ValueError("Please enter a public domain name, not an IP address.")
    except ValueError as exc:
        if str(exc).startswith("Please enter"):
            raise
        # A normal DNS hostname is expected here.

    if (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname.endswith(".local")
        or hostname.endswith(".internal")
        or "." not in hostname
    ):
        raise ValueError("Local and private hostnames are not allowed.")

    path = parsed.path or "/"
    query = parsed.query

    if any(ord(ch) < 32 or ord(ch) == 127 for ch in path + query):
        raise ValueError("The URL contains invalid characters.")

    netloc = hostname
    normalized = urlunsplit((scheme, netloc, path, query, ""))

    if len(normalized) > MAX_URL_LENGTH:
        raise ValueError("The URL is too long.")

    return normalized


def resolve_public_addresses(hostname: str, port: int):
    try:
        records = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror:
        raise ValueError("The website hostname could not be resolved.")

    addresses = []

    for record in records:
        sockaddr = record[4]
        address_text = sockaddr[0]

        try:
            address = ipaddress.ip_address(address_text)
        except ValueError:
            raise ValueError("The website resolved to an invalid address.")

        if not address.is_global:
            raise ValueError(
                "The website resolves to a non-public IP address. "
                "For safety, this request was blocked."
            )

        if address not in addresses:
            addresses.append(address)

    if not addresses:
        raise ValueError("No public IP address was found for this website.")

    return addresses


def open_pinned_connection(hostname: str, scheme: str, port: int):
    addresses = resolve_public_addresses(hostname, port)
    last_error = None

    for address in addresses:
        sock = None

        try:
            # Connect directly to the IP that was validated above.
            # Do not ask the networking stack to resolve the hostname again.
            sock = socket.create_connection(
                (str(address), port),
                timeout=REQUEST_TIMEOUT,
            )
            sock.settimeout(REQUEST_TIMEOUT)

            if scheme == "https":
                context = ssl.create_default_context()
                # Keep TLS certificate validation and hostname verification.
                sock = context.wrap_socket(
                    sock,
                    server_hostname=hostname,
                )

            return sock

        except (OSError, ssl.SSLError, socket.timeout) as exc:
            last_error = exc
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    raise ValueError(
        "Could not establish a secure connection to the website."
    ) from last_error


def fetch_public_page(raw_url: str):
    current_url = normalize_and_validate_url(raw_url)

    for redirect_number in range(MAX_REDIRECTS + 1):
        current_url = normalize_and_validate_url(current_url)
        parsed = urlsplit(current_url)

        scheme = parsed.scheme
        hostname = parsed.hostname
        port = 443 if scheme == "https" else 80

        path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
        query = quote(parsed.query, safe="=&;%:@!$'()*+,-._~/?")
        request_target = path + (("?" + query) if query else "")

        sock = open_pinned_connection(hostname, scheme, port)
        response = None

        try:
            host_header = hostname
            request_bytes = (
                f"GET {request_target} HTTP/1.1\r\n"
                f"Host: {host_header}\r\n"
                "User-Agent: EAQSEOAudit/1.2\r\n"
                "Accept: text/html,application/xhtml+xml\r\n"
                "Accept-Encoding: identity\r\n"
                "Connection: close\r\n"
                "\r\n"
            ).encode("ascii")

            sock.sendall(request_bytes)

            response = http.client.HTTPResponse(sock)
            response.begin()

            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")

                if not location:
                    raise ValueError("The website returned an invalid redirect.")

                if redirect_number >= MAX_REDIRECTS:
                    raise ValueError("Too many website redirects.")

                current_url = urljoin(current_url, location)
                continue

            content_type = response.getheader("Content-Type", "").lower()

            if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                raise ValueError(
                    "The URL did not return an HTML page. "
                    "Please enter a normal webpage URL."
                )

            content_length = response.getheader("Content-Length")

            if content_length:
                try:
                    if int(content_length) > MAX_HTML_BYTES:
                        raise ValueError(
                            "The webpage is too large to analyze."
                        )
                except ValueError as exc:
                    if "too large" in str(exc):
                        raise

            body = response.read(MAX_HTML_BYTES + 1)

            if len(body) > MAX_HTML_BYTES:
                raise ValueError("The webpage exceeds the 1 MB analysis limit.")

            charset = response.headers.get_content_charset() or "utf-8"

            try:
                html = body.decode(charset, errors="replace")
            except LookupError:
                html = body.decode("utf-8", errors="replace")

            return current_url, html, response.status

        except (OSError, ssl.SSLError, socket.timeout, http.client.HTTPException) as exc:
            raise ValueError(
                "The website could not be fetched safely. "
                "It may be unavailable or may have closed the connection."
            ) from exc

        finally:
            if response is not None:
                response.close()
            else:
                try:
                    sock.close()
                except OSError:
                    pass

    raise ValueError("The website could not be reached.")


def analyze_page(url: str, html: str, status_code: int):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    for element in soup(["script", "style", "noscript", "svg", "template"]):
        element.decompose()

    checks = []

    def add_check(name, passed, detail, recommendation=""):
        checks.append({
            "name": name,
            "passed": bool(passed),
            "detail": detail,
            "recommendation": recommendation,
        })

    add_check(
        "HTTP response",
        status_code == 200,
        f"HTTP status: {status_code}",
        "Check the page response and server configuration."
        if status_code != 200 else "",
    )

    add_check(
        "HTTPS",
        urlsplit(url).scheme == "https",
        "The page uses HTTPS." if urlsplit(url).scheme == "https"
        else "The page uses HTTP.",
        "Use a valid HTTPS certificate and redirect HTTP to HTTPS."
        if urlsplit(url).scheme != "https" else "",
    )

    title_tag = soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else ""
    title_length = len(title)

    add_check(
        "Page title",
        bool(title),
        title if title else "No title tag found.",
        "Add a unique, descriptive title, typically around 30–60 characters."
        if not title else (
            "Review title length; a common guideline is 30–60 characters."
            if not 30 <= title_length <= 60 else ""
        ),
    )

    description_tag = soup.find(
        "meta",
        attrs={"name": lambda value: value and value.lower() == "description"},
    )
    description = (
        description_tag.get("content", "").strip()
        if description_tag else ""
    )

    add_check(
        "Meta description",
        bool(description),
        description if description else "No meta description found.",
        "Add a useful, unique meta description, often around 120–160 characters."
        if not description else (
            "Review description length; 120–160 characters is a common guideline."
            if not 120 <= len(description) <= 160 else ""
        ),
    )

    headings = soup.find_all("h1")

    add_check(
        "H1 heading",
        len(headings) == 1,
        f"Found {len(headings)} H1 heading(s).",
        "Use one clear primary H1 heading that describes the page."
        if len(headings) != 1 else "",
    )

    images = soup.find_all("img")
    missing_alt = sum(
        1 for image in images
        if not image.has_attr("alt")
    )

    add_check(
        "Image alt attributes",
        missing_alt == 0,
        f"{missing_alt} of {len(images)} images lack an alt attribute.",
        "Add meaningful alt text to informative images; use alt=\"\" for decorative images."
        if missing_alt else "",
    )

    canonical_tag = soup.find(
        "link",
        attrs={"rel": lambda value: value and "canonical" in (
            value if isinstance(value, list) else [value]
        )},
    )
    canonical = canonical_tag.get("href", "").strip() if canonical_tag else ""

    add_check(
        "Canonical URL",
        bool(canonical),
        canonical if canonical else "No canonical link found.",
        "Add a canonical URL when appropriate to identify the preferred page."
        if not canonical else "",
    )

    viewport = soup.find(
        "meta",
        attrs={"name": lambda value: value and value.lower() == "viewport"},
    )

    add_check(
        "Mobile viewport",
        viewport is not None,
        "Viewport meta tag found." if viewport else "Viewport meta tag missing.",
        "Add a responsive viewport meta tag."
        if not viewport else "",
    )

    robots_tag = soup.find(
        "meta",
        attrs={"name": lambda value: value and value.lower() == "robots"},
    )
    robots_content = (
        robots_tag.get("content", "").lower()
        if robots_tag else ""
    )
    noindex = "noindex" in robots_content

    add_check(
        "Robots meta directive",
        not noindex,
        "A noindex directive was found."
        if noindex else "No meta robots noindex directive detected.",
        "Remove noindex if this page should appear in search results."
        if noindex else "",
    )

    text_content = soup.get_text(" ", strip=True)
    words = text_content.split()

    add_check(
        "Text content",
        len(words) >= 300,
        f"Approximately {len(words)} words detected.",
        "Review whether the page provides enough useful content for its purpose."
        if len(words) < 300 else "",
    )

    links = soup.find_all("a", href=True)
    internal_links = 0
    external_links = 0
    site_host = urlsplit(url).hostname

    for link in links:
        href = link.get("href", "").strip()

        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        absolute = urljoin(url, href)
        target_host = urlsplit(absolute).hostname

        if not target_host:
            continue

        if target_host.lower() == site_host.lower():
            internal_links += 1
        else:
            external_links += 1

    add_check(
        "Internal links",
        internal_links > 0,
        f"{internal_links} internal link(s) detected.",
        "Add useful internal links to related pages where appropriate."
        if internal_links == 0 else "",
    )

    passed = sum(1 for check in checks if check["passed"])
    total = len(checks)
    score = round((passed / total) * 100) if total else 0

    return {
        "url": url,
        "status_code": status_code,
        "title": title,
        "description": description,
        "word_count": len(words),
        "internal_links": internal_links,
        "external_links": external_links,
        "passed": passed,
        "total": total,
        "score": score,
        "checks": checks,
    }


def render_page(result_html: str = ""):
    return HTMLResponse(HTML_TEMPLATE.replace("__RESULT__", result_html))


@app.get("/", response_class=HTMLResponse)
def home():
    return render_page()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
    }


@app.post("/audit", response_class=HTMLResponse)
def audit(request: Request, url: str = Form(...)):
    client_ip = (
        request.client.host
        if request.client and request.client.host
        else "unknown"
    )

    if not check_rate_limit(client_ip):
        return HTMLResponse(
            HTML_TEMPLATE.replace(
                "__RESULT__",
                '<section class="card"><h2>Rate limit reached</h2>'
                '<p>Please wait one minute before trying again.</p></section>',
            ),
            status_code=429,
        )

    try:
        final_url, html, status_code = fetch_public_page(url)
        report = analyze_page(final_url, html, status_code)

        check_cards = []

        for check in report["checks"]:
            status_class = "pass" if check["passed"] else "fail"
            status_text = "PASS" if check["passed"] else "REVIEW"

            recommendation = (
                f'<p class="muted">{escape(check["recommendation"])}</p>'
                if check["recommendation"] else ""
            )

            check_cards.append(
                '<div class="metric">'
                f'<strong>{escape(check["name"])}</strong>'
                f'<span class="status {status_class}">{status_text}</span>'
                f'<p>{escape(check["detail"])}</p>'
                f'{recommendation}'
                '</div>'
            )

        result_html = (
            '<section class="card">'
            '<h2>SEO Audit Report</h2>'
            f'<p><strong>Website:</strong> {escape(report["url"])}</p>'
            f'<div class="score">{report["score"]}/100</div>'
            '<p class="muted">EAQ on-page checklist score — not a Google ranking score.</p>'
            f'<p>{report["passed"]} of {report["total"]} checks passed.</p>'
            '<div class="grid">'
            f'<div class="metric"><strong>Page title</strong>{escape(report["title"] or "Missing")}</div>'
            f'<div class="metric"><strong>Word count</strong>{report["word_count"]}</div>'
            f'<div class="metric"><strong>Internal links</strong>{report["internal_links"]}</div>'
            f'<div class="metric"><strong>External links</strong>{report["external_links"]}</div>'
            '</div></section>'
            '<section class="card"><h2>Detailed Checks</h2>'
            f'<div class="grid">{"".join(check_cards)}</div></section>'
            '<section class="card"><p class="notice">This basic report checks selected on-page elements only. It does not measure actual page speed, backlinks, search traffic, keyword rankings, or Google rankings.</p></section>'
        )

        return render_page(result_html)

    except ValueError as exc:
        message = escape(str(exc))
        result_html = (
            '<section class="card"><h2>Unable to analyze this URL</h2>'
            f'<p>{message}</p>'
            '<p class="muted">Check the address and try again with a public webpage.</p>'
            '</section>'
        )
        return render_page(result_html)

    except Exception:
        result_html = (
            '<section class="card"><h2>Something went wrong</h2>'
            '<p>The audit could not be completed. Please try again later.</p>'
            '</section>'
        )
        return render_page(result_html)
