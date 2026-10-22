
import http.client
import ipaddress
import socket
import ssl
import threading
import time
from collections import deque
from html import escape
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

APP_NAME = "EAQ SEO Audit"
APP_VERSION = "1.4.0"

MAX_URL_LENGTH = 2048
MAX_HTML_BYTES = 1_000_000
REQUEST_TIMEOUT = 8
MAX_REDIRECTS = 3

RATE_LIMIT = 5
RATE_WINDOW = 60
MAX_RATE_KEYS = 5000

app = FastAPI(
    title=APP_NAME,
    docs_url=None,
    redoc_url=None,
)

rate_history = {}
rate_lock = threading.Lock()

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EAQ.io SEO Audit — Free Website SEO Checker</title>
<meta name="description" content="Check essential on-page SEO elements with EAQ SEO Audit. Free website SEO analysis without registration.">
<style>
*{box-sizing:border-box}
body{margin:0;background:#f3f7fb;color:#182b43;font-family:Arial,Helvetica,sans-serif;line-height:1.65}
header{background:#10243e;color:white;padding:25px 18px}
.wrap{max-width:920px;margin:auto;padding:0 18px}
.brand{font-size:25px;font-weight:800}
.brand span{color:#48d4c2}
header p{margin:5px 0 0;color:#d2deeb}
main{padding:34px 0}
.card{background:white;border:1px solid #e0e8f0;border-radius:15px;padding:24px;margin-bottom:20px;box-shadow:0 5px 22px #142a4310}
h1{font-size:30px;line-height:1.25;margin:0 0 12px}
h2{font-size:21px;margin:0 0 14px}
.muted{color:#617187}
label{display:block;font-weight:700;margin:18px 0 7px}
input{width:100%;padding:14px;border:1px solid #cbd7e4;border-radius:9px;font-size:16px}
button{margin-top:14px;background:#087e8b;color:white;border:0;padding:13px 21px;border-radius:9px;font-size:16px;font-weight:700;cursor:pointer}
button:focus-visible,input:focus-visible{outline:3px solid #48d4c2;outline-offset:2px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:13px}
.metric{padding:15px;border-radius:10px;background:#f5f8fb;border:1px solid #e5ebf2;overflow-wrap:anywhere}
.metric strong{display:block;margin-bottom:5px}
.status{font-weight:700}
.pass{color:#087a53}
.fail{color:#b45309}
.score{font-size:38px;font-weight:800;color:#087e8b}
.notice{background:#edf8f7;padding:13px;border-radius:9px}
footer{text-align:center;padding:25px;color:#617187;font-size:13px}
</style>
</head>
<body>
<header>
<div class="wrap">
<div class="brand">EAQ<span>.io</span> SEO Audit</div>
<p>Analyze. Optimize. Grow.</p>
</div>
</header>
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
<p class="muted">Basic checks are rate-limited to help prevent abuse. This is not a Google ranking score.</p>
</section>
__RESULT__
</main>
<footer>EAQ SEO Audit · Basic on-page analysis</footer>
</body>
</html>"""


def render_page(result_html=""):
    return HTMLResponse(PAGE.replace("__RESULT__", result_html))


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; "
        "style-src 'unsafe-inline'; "
        "form-action 'self'; "
        "base-uri 'none'; "
        "frame-ancestors 'none'"
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def check_rate_limit(client_ip):
    """Bounded in-process limit; shared storage is needed when scaling."""
    now = time.monotonic()

    with rate_lock:
        history = rate_history.get(client_ip)

        if history is None:
            if len(rate_history) >= MAX_RATE_KEYS:
                stale_keys = [
                    key for key, entries in rate_history.items()
                    if not entries or now - entries[-1] >= RATE_WINDOW
                ]
                for key in stale_keys:
                    rate_history.pop(key, None)

                if len(rate_history) >= MAX_RATE_KEYS:
                    return False

            history = deque()
            rate_history[client_ip] = history

        while history and now - history[0] >= RATE_WINDOW:
            history.popleft()

        if len(history) >= RATE_LIMIT:
            return False

        history.append(now)
        return True


def normalize_url(raw_url):
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
    except ValueError as exc:
        raise ValueError("The URL format is invalid.") from exc

    if scheme not in ("http", "https"):
        raise ValueError("Only HTTP and HTTPS websites are supported.")

    if not hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("Enter a public website URL without credentials.")

    expected_port = 443 if scheme == "https" else 80
    if port is not None and port != expected_port:
        raise ValueError("Only standard HTTP and HTTPS ports are allowed.")

    hostname = hostname.rstrip(".").lower()

    if not hostname or "%" in hostname:
        raise ValueError("The hostname is invalid.")

    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("The hostname is invalid.") from exc

    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("Enter a public domain name, not an IP address.")

    blocked_names = {
        "localhost",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
        "kubernetes.default",
    }

    blocked_suffixes = (
        ".localhost",
        ".local",
        ".internal",
        ".localdomain",
        ".home.arpa",
        ".cluster.local",
        ".svc",
    )

    if (
        "." not in hostname
        or hostname in blocked_names
        or any(hostname.endswith(s) for s in blocked_suffixes)
    ):
        raise ValueError("Local and private hostnames are not allowed.")

    path = parsed.path or "/"
    query = parsed.query

    if any(ord(ch) < 32 or ord(ch) == 127 for ch in path + query):
        raise ValueError("The URL contains invalid characters.")

    normalized = urlunsplit((scheme, hostname, path, query, ""))

    if len(normalized) > MAX_URL_LENGTH:
        raise ValueError("The URL is too long.")

    return normalized


def is_public_ip(address):
    """Accept only globally routable IP addresses."""
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return is_public_ip(address.ipv4_mapped)

        if address.sixtofour is not None or address.teredo is not None:
            return False

        if address in ipaddress.ip_network("64:ff9b::/96"):
            return False

        if address in ipaddress.ip_network("64:ff9b:1::/48"):
            return False

        if address in ipaddress.ip_network("2002::/16"):
            return False

        return (
            address.is_global
            and not address.is_multicast
            and not address.is_unspecified
            and not address.is_loopback
            and not address.is_link_local
        )

    blocked_v4 = (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
    )

    return (
        address.is_global
        and not address.is_multicast
        and not address.is_unspecified
        and not address.is_loopback
        and not address.is_link_local
        and not any(
            address in ipaddress.ip_network(network)
            for network in blocked_v4
        )
    )


def resolve_public_addresses(hostname, port):
    try:
        records = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except (socket.gaierror, OSError) as exc:
        raise ValueError("The website hostname could not be resolved.") from exc

    addresses = []

    for record in records:
        ip_text = record[4][0]

        if "%" in ip_text:
            raise ValueError("Scoped IP addresses are not allowed.")

        try:
            address = ipaddress.ip_address(ip_text)
        except ValueError as exc:
            raise ValueError("The website resolved to an invalid address.") from exc

        # Reject the hostname if any returned address is non-public.
        if not is_public_ip(address):
            raise ValueError(
                "The website resolves to a non-public or reserved IP address."
            )

        if address not in addresses:
            addresses.append(address)

    if not addresses:
        raise ValueError("No public IP address was found for this website.")

    return addresses


def open_pinned_connection(hostname, scheme, port):
    """Connect directly to a validated IP; verify TLS using the hostname."""
    last_error = None
    addresses = resolve_public_addresses(hostname, port)

    for address in addresses:
        sock = None

        try:
            family = socket.AF_INET if address.version == 4 else socket.AF_INET6
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(REQUEST_TIMEOUT)

            if address.version == 4:
                sock.connect((str(address), port))
            else:
                sock.connect((str(address), port, 0, 0))

            if scheme == "https":
                context = ssl.create_default_context()
                sock = context.wrap_socket(
                    sock,
                    server_hostname=hostname,
                )
                sock.settimeout(REQUEST_TIMEOUT)

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


def fetch_public_page(raw_url):
    current_url = normalize_url(raw_url)

    for redirect_number in range(MAX_REDIRECTS + 1):
        current_url = normalize_url(current_url)
        parsed = urlsplit(current_url)

        scheme = parsed.scheme
        hostname = parsed.hostname
        port = 443 if scheme == "https" else 80

        path = quote(
            parsed.path or "/",
            safe="/%:@!$&'()*+,;=-._~",
        )
        query = quote(
            parsed.query,
            safe="=&;%:@!$'()*+,-._~/?",
        )
        target = path + (("?" + query) if query else "")

        sock = open_pinned_connection(hostname, scheme, port)
        response = None

        try:
            request_bytes = (
                f"GET {target} HTTP/1.1\r\n"
                f"Host: {hostname}\r\n"
                f"User-Agent: EAQSEOAudit/{APP_VERSION}\r\n"
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

            mime_type = (
                response.getheader("Content-Type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )

            if mime_type not in ("text/html", "application/xhtml+xml"):
                raise ValueError("The URL did not return an HTML page.")

            content_encoding = (
                response.getheader("Content-Encoding", "identity")
                .strip()
                .lower()
            )

            if content_encoding not in ("", "identity"):
                raise ValueError(
                    "The website returned compressed content that "
                    "this basic audit cannot process."
                )

            content_length = response.getheader("Content-Length")

            if content_length is not None:
                try:
                    size = int(content_length)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        "The website returned an invalid response length."
                    ) from exc

                if size < 0:
                    raise ValueError(
                        "The website returned an invalid response length."
                    )

                if size > MAX_HTML_BYTES:
                    raise ValueError("The webpage is too large to analyze.")

            body = response.read(MAX_HTML_BYTES + 1)

            if len(body) > MAX_HTML_BYTES:
                raise ValueError("The webpage exceeds the 1 MB analysis limit.")

            charset = response.headers.get_content_charset() or "utf-8"

            try:
                html = body.decode(charset, errors="replace")
            except LookupError:
                html = body.decode("utf-8", errors="replace")

            return current_url, html, response.status

        except (
            OSError,
            ssl.SSLError,
            socket.timeout,
            http.client.HTTPException,
        ) as exc:
            raise ValueError(
                "The website could not be fetched safely or timed out."
            ) from exc

        finally:
            if response is not None:
                try:
                    response.close()
                except OSError:
                    pass

            try:
                sock.close()
            except OSError:
                pass

    raise ValueError("The website could not be reached.")


def analyze_page(url, html, status_code):
    soup = BeautifulSoup(html, "html.parser")

    for element in soup(
        ["script", "style", "noscript", "svg", "template"]
    ):
        element.decompose()

    checks = []

    def add(name, passed, detail, recommendation=""):
        checks.append({
            "name": name,
            "passed": bool(passed),
            "detail": detail,
            "recommendation": recommendation,
        })

    add(
        "HTTP response",
        status_code == 200,
        f"HTTP status: {status_code}",
        "Check the page response and server configuration."
        if status_code != 200 else "",
    )

    secure = urlsplit(url).scheme == "https"

    add(
        "HTTPS",
        secure,
        "The page uses HTTPS." if secure else "The page uses HTTP.",
        "Use a valid HTTPS certificate and redirect HTTP to HTTPS."
        if not secure else "",
    )

    title_tag = soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else ""

    title_recommendation = ""
    if not title:
        title_recommendation = (
            "Add a unique, descriptive title, typically around 30–60 characters."
        )
    elif not 30 <= len(title) <= 60:
        title_recommendation = (
            "Review title length; 30–60 characters is a common guideline."
        )

    add(
        "Page title",
        bool(title),
        title or "No title tag found.",
        title_recommendation,
    )

    desc_tag = soup.find(
        "meta",
        attrs={"name": lambda value: value and value.lower() == "description"},
    )
    description = desc_tag.get("content", "").strip() if desc_tag else ""

    desc_recommendation = ""
    if not description:
        desc_recommendation = (
            "Add a useful, unique meta description; "
            "120–160 characters is a common guideline."
        )
    elif not 120 <= len(description) <= 160:
        desc_recommendation = (
            "Review description length; 120–160 characters is a common guideline."
        )

    add(
        "Meta description",
        bool(description),
        description or "No meta description found.",
        desc_recommendation,
    )

    h1_count = len(soup.find_all("h1"))

    add(
        "H1 heading",
        h1_count == 1,
        f"Found {h1_count} H1 heading(s).",
        "Use one clear primary H1 heading." if h1_count != 1 else "",
    )

    images = soup.find_all("img")
    missing_alt = sum(
        1 for image in images
        if not image.has_attr("alt")
    )

    add(
        "Image alt attributes",
        missing_alt == 0,
        f"{missing_alt} of {len(images)} images lack an alt attribute.",
        'Add meaningful alt text to informative images; use alt="" for decorative images.'
        if missing_alt else "",
    )

    canonical_tag = soup.find(
        "link",
        attrs={
            "rel": lambda value: value and "canonical" in (
                value if isinstance(value, list) else [value]
            )
        },
    )
    canonical = canonical_tag.get("href", "").strip() if canonical_tag else ""

    add(
        "Canonical URL",
        bool(canonical),
        canonical or "No canonical link found.",
        "Add a canonical URL when appropriate." if not canonical else "",
    )

    viewport = soup.find(
        "meta",
        attrs={"name": lambda value: value and value.lower() == "viewport"},
    )

    add(
        "Mobile viewport",
        viewport is not None,
        "Viewport meta tag found." if viewport else "Viewport meta tag missing.",
        "Add a responsive viewport meta tag." if viewport is None else "",
    )

    robots_tag = soup.find(
        "meta",
        attrs={"name": lambda value: value and value.lower() == "robots"},
    )
    robots = robots_tag.get("content", "").lower() if robots_tag else ""
    noindex = "noindex" in robots

    add(
        "Robots directive",
        not noindex,
        "A noindex directive was found."
        if noindex else "No meta robots noindex directive detected.",
        "Remove noindex if this page should appear in search results."
        if noindex else "",
    )

    words = soup.get_text(" ", strip=True).split()

    add(
        "Text content",
        len(words) >= 300,
        f"Approximately {len(words)} words detected.",
        "Review whether the page has enough useful content for its purpose."
        if len(words) < 300 else "",
    )

    internal = 0
    external = 0
    site_host = (urlsplit(url).hostname or "").lower()

    for link in soup.find_all("a", href=True):
        href = link.get("href", "").strip()

        if not href or href.startswith(
            ("#", "mailto:", "tel:", "javascript:")
        ):
            continue

        target_host = (
            urlsplit(urljoin(url, href)).hostname or ""
        ).lower()

        if not target_host:
            continue

        if target_host == site_host:
            internal += 1
        else:
            external += 1

    add(
        "Internal links",
        internal > 0,
        f"{internal} internal link(s) detected.",
        "Add useful internal links where appropriate."
        if internal == 0 else "",
    )

    passed = sum(1 for item in checks if item["passed"])

    return {
        "url": url,
        "status_code": status_code,
        "title": title,
        "description": description,
        "word_count": len(words),
        "internal_links": internal,
        "external_links": external,
        "passed": passed,
        "total": len(checks),
        "score": round(passed * 100 / len(checks)) if checks else 0,
        "checks": checks,
    }


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
            PAGE.replace(
                "__RESULT__",
                '<section class="card"><h2>Rate limit reached</h2>'
                '<p>Please wait one minute before trying again.</p></section>',
            ),
            status_code=429,
        )

    try:
        final_url, html, status = fetch_public_page(url)
        report = analyze_page(final_url, html, status)

        cards = []

        for item in report["checks"]:
            css_class = "pass" if item["passed"] else "fail"
            label = "PASS" if item["passed"] else "REVIEW"

            recommendation = (
                f'<p class="muted">{escape(item["recommendation"])}</p>'
                if item["recommendation"] else ""
            )

            cards.append(
                '<div class="metric">'
                f'<strong>{escape(item["name"])}</strong>'
                f'<span class="status {css_class}">{label}</span>'
                f'<p>{escape(item["detail"])}</p>'
                f'{recommendation}'
                '</div>'
            )

        result = (
            '<section class="card"><h2>SEO Audit Report</h2>'
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
            f'<div class="grid">{"".join(cards)}</div></section>'
            '<section class="card"><p class="notice">'
            'This basic report checks selected on-page elements only. '
            'It does not measure actual page speed, backlinks, search traffic, '
            'keyword rankings, or Google rankings.'
            '</p></section>'
        )

        return render_page(result)

    except ValueError as exc:
        return render_page(
            '<section class="card"><h2>Unable to analyze this URL</h2>'
            f'<p>{escape(str(exc))}</p>'
            '<p class="muted">Check the address and try again with a public webpage.</p>'
            '</section>'
        )

    except Exception:
        return render_page(
            '<section class="card"><h2>Something went wrong</h2>'
            '<p>The audit could not be completed. Please try again later.</p>'
            '</section>'
        )
