
import ipaddress
import socket
import time
from collections import defaultdict, deque
from html import escape
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

APP_NAME = "EAQ SEO Audit"
APP_VERSION = "1.1.0"
MAX_URL_LENGTH = 2048
MAX_HTML_BYTES = 1_000_000
REQUEST_TIMEOUT = 10
MAX_REDIRECTS = 3
RATE_LIMIT = 5
RATE_WINDOW = 60

app = FastAPI(
    title=APP_NAME,
    description="Website SEO audit and actionable recommendations.",
    version=APP_VERSION,
)

# Basic in-memory rate limiting for the initial single-instance deployment.
# A production multi-instance service needs shared rate limiting.
request_history = defaultdict(deque)


def check_rate_limit(client_ip: str) -> bool:
    now = time.monotonic()
    history = request_history[client_ip]

    while history and now - history[0] > RATE_WINDOW:
        history.popleft()

    if len(history) >= RATE_LIMIT:
        return False

    history.append(now)
    return True


def resolve_public_hostname(hostname: str) -> bool:
    if not hostname or len(hostname) > 253:
        return False

    hostname = hostname.rstrip(".").lower()

    if hostname in {"localhost", "localhost.localdomain"}:
        return False

    # Do not allow IP literals in this initial public scanner.
    try:
        ipaddress.ip_address(hostname)
        return False
    except ValueError:
        pass

    try:
        records = socket.getaddrinfo(
            hostname,
            None,
            type=socket.SOCK_STREAM,
        )
    except (socket.gaierror, OSError, ValueError):
        return False

    addresses = set()

    for record in records:
        try:
            addresses.add(ipaddress.ip_address(record[4][0]))
        except ValueError:
            return False

    if not addresses:
        return False

    return all(
        address.is_global
        and not address.is_multicast
        and not address.is_unspecified
        for address in addresses
    )


def validate_url(raw_url: str) -> str:
    raw_url = (raw_url or "").strip()

    if not raw_url or len(raw_url) > MAX_URL_LENGTH:
        raise ValueError("Enter a valid website URL.")

    if "://" not in raw_url:
        raw_url = "https://" + raw_url

    try:
        parts = urlsplit(raw_url)
        hostname = parts.hostname
        port = parts.port
    except ValueError:
        raise ValueError("The URL format is invalid.")

    if parts.scheme.lower() not in {"http", "https"}:
        raise ValueError("Only HTTP and HTTPS websites are supported.")

    if not hostname or parts.username or parts.password:
        raise ValueError("Enter a valid public website URL.")

    expected_port = 443 if parts.scheme.lower() == "https" else 80

    if port is not None and port != expected_port:
        raise ValueError("Custom ports are not supported.")

    if not resolve_public_hostname(hostname):
        raise ValueError(
            "This hostname could not be verified as a public website."
        )

    # Remove fragments; browsers do not send them to the server.
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc,
        parts.path or "/",
        parts.query,
        "",
    ))


def fetch_public_page(raw_url: str):
    current_url = validate_url(raw_url)

    session = requests.Session()
    # Do not inherit proxy settings from the environment.
    session.trust_env = False

    try:
        for _ in range(MAX_REDIRECTS + 1):
            # Revalidate every destination before following a redirect.
            current_url = validate_url(current_url)

            response = session.get(
                current_url,
                headers={
                    "User-Agent": "EAQSEOAudit/1.1",
                    "Accept": "text/html,application/xhtml+xml",
                },
                timeout=(4, REQUEST_TIMEOUT),
                allow_redirects=False,
                stream=True,
            )

            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                response.close()

                if not location:
                    raise ValueError("The redirect destination is missing.")

                current_url = urljoin(current_url, location)
                continue

            try:
                response.raise_for_status()

                content_type = response.headers.get(
                    "Content-Type", ""
                ).lower()

                if (
                    "text/html" not in content_type
                    and "application/xhtml+xml" not in content_type
                ):
                    raise ValueError(
                        "This URL does not return an HTML page."
                    )

                chunks = []
                total_bytes = 0

                for chunk in response.iter_content(chunk_size=16384):
                    if not chunk:
                        continue

                    total_bytes += len(chunk)

                    if total_bytes > MAX_HTML_BYTES:
                        raise ValueError(
                            "The page exceeds the 1 MB analysis limit."
                        )

                    chunks.append(chunk)

                encoding = response.encoding or "utf-8"
                html = b"".join(chunks).decode(
                    encoding, errors="replace"
                )

                return current_url, html, response.status_code

            finally:
                response.close()

        raise ValueError("The website redirected too many times.")

    finally:
        session.close()


def analyze_page(url: str, html: str, status_code: int) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    for element in soup(["script", "style", "noscript", "svg"]):
        element.decompose()

    title_tag = soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else ""

    description_tag = soup.find(
        "meta",
        attrs={
            "name": lambda value: (
                isinstance(value, str)
                and value.lower() == "description"
            )
        },
    )
    description = (
        description_tag.get("content", "").strip()
        if description_tag else ""
    )

    h1_tags = soup.find_all("h1")
    h2_tags = soup.find_all("h2")

    images = soup.find_all("img")
    missing_alt = [
        image for image in images
        if image.get("alt") is None
        or not image.get("alt", "").strip()
    ]

    canonical_tag = soup.find(
        "link",
        rel=lambda value: (
            "canonical" in [
                item.lower()
                for item in (
                    value if isinstance(value, list)
                    else (value or "").split()
                )
            ]
        ),
    )
    canonical = (
        canonical_tag.get("href", "").strip()
        if canonical_tag else ""
    )

    robots_tag = soup.find(
        "meta",
        attrs={
            "name": lambda value: (
                isinstance(value, str)
                and value.lower() == "robots"
            )
        },
    )
    robots_content = (
        robots_tag.get("content", "").lower()
        if robots_tag else ""
    )

    viewport = soup.find(
        "meta",
        attrs={
            "name": lambda value: (
                isinstance(value, str)
                and value.lower() == "viewport"
            )
        },
    )

    base_host = (urlsplit(url).hostname or "").lower()
    internal_links = 0
    external_links = 0

    for link in soup.find_all("a", href=True):
        href = link.get("href", "").strip()

        if not href or href.startswith(
            ("#", "mailto:", "tel:", "javascript:", "data:")
        ):
            continue

        absolute = urljoin(url, href)
        parsed = urlsplit(absolute)

        if parsed.scheme not in {"http", "https"}:
            continue

        if (parsed.hostname or "").lower() == base_host:
            internal_links += 1
        else:
            external_links += 1

    text_content = soup.get_text(" ", strip=True)
    word_count = len(text_content.split())

    checks = [
        (
            "HTTP response",
            status_code < 400,
            f"Received HTTP {status_code}.",
        ),
        (
            "HTTPS",
            urlsplit(url).scheme == "https",
            "Use HTTPS to protect connections."
            if urlsplit(url).scheme != "https"
            else "HTTPS is enabled.",
        ),
        (
            "Title tag",
            bool(title),
            "Add a descriptive title to the page.",
        ),
        (
            "Title length",
            30 <= len(title) <= 60,
            f"Title length: {len(title)} characters. "
            "Around 30–60 characters is a practical guideline.",
        ),
        (
            "Meta description",
            bool(description),
            "Add a useful, unique meta description.",
        ),
        (
            "Description length",
            120 <= len(description) <= 160,
            f"Description length: {len(description)} characters. "
            "Around 120–160 characters is a practical guideline.",
        ),
        (
            "H1 heading",
            len(h1_tags) == 1,
            f"Found {len(h1_tags)} H1 headings. "
            "Review whether one clear main heading is appropriate.",
        ),
        (
            "Image alternative text",
            not missing_alt,
            f"{len(missing_alt)} of {len(images)} images have "
            "missing or empty alt attributes.",
        ),
        (
            "Canonical",
            bool(canonical),
            "No canonical link was detected. "
            "Add one when appropriate for this page.",
        ),
        (
            "Mobile viewport",
            viewport is not None,
            "Add a responsive viewport meta tag.",
        ),
        (
            "Content",
            word_count >= 300,
            f"Approximately {word_count} words were found. "
            "Review whether the content satisfies visitor intent.",
        ),
        (
            "Robots directive",
            "noindex" not in robots_content,
            "A noindex directive was detected; verify that it is intentional.",
        ),
    ]

    passed = sum(1 for _, ok, _ in checks if ok)
    score = round(100 * passed / len(checks))

    findings = [
        {
            "name": name,
            "status": "PASS" if passed_check else "REVIEW",
            "detail": (
                "Check passed." if passed_check else detail
            ),
        }
        for name, passed_check, detail in checks
    ]

    return {
        "url": url,
        "status_code": status_code,
        "score": score,
        "title": title or "Missing",
        "description": description or "Missing",
        "title_length": len(title),
        "description_length": len(description),
        "h1_count": len(h1_tags),
        "h2_count": len(h2_tags),
        "image_count": len(images),
        "missing_alt_count": len(missing_alt),
        "internal_links": internal_links,
        "external_links": external_links,
        "word_count": word_count,
        "canonical": canonical or "Not detected",
        "findings": findings,
    }


def render_page(content: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Analyze website SEO, identify technical issues, and get practical recommendations with EAQ SEO Audit.">
<meta name="theme-color" content="#10243a">
<title>EAQ SEO Audit — Website SEO Analysis</title>
<style>
:root {{
  --navy:#10243a; --teal:#087f8c; --bg:#f3f6fa;
  --text:#1c2938; --muted:#64748b; --line:#dce5ef;
  --white:#fff; --green:#137448; --amber:#9a5b00;
}}
* {{box-sizing:border-box}}
body {{margin:0;background:var(--bg);color:var(--text);
font-family:Arial,Helvetica,sans-serif;line-height:1.65}}
header {{background:var(--navy);color:white;padding:17px 20px}}
.nav {{max-width:1080px;margin:auto;display:flex;align-items:center;
justify-content:space-between;gap:15px}}
.brand {{font-size:25px;font-weight:800;letter-spacing:1px}}
.brand span {{color:#5dd5d0}}
.nav small {{color:#d9e5ef}}
main {{max-width:1000px;margin:auto;padding:28px 16px 52px}}
.hero {{text-align:center;padding:28px 0}}
.eyebrow {{color:var(--teal);font-size:12px;font-weight:800;
letter-spacing:2px;text-transform:uppercase}}
h1 {{font-size:clamp(30px,5vw,46px);line-height:1.15;
color:var(--navy);margin:10px 0 16px}}
.hero p {{max-width:680px;margin:0 auto;color:var(--muted)}}
.card {{background:white;border:1px solid var(--line);border-radius:16px;
padding:22px;margin:18px 0;box-shadow:0 8px 28px #10243a08}}
.card h2 {{color:var(--navy);margin-top:0}}
form {{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}}
input {{flex:1 1 250px;min-width:0;padding:15px;
border:1px solid #c8d5e3;border-radius:10px;font-size:16px}}
button {{background:var(--teal);color:white;border:0;border-radius:10px;
padding:14px 20px;font-size:15px;font-weight:700;cursor:pointer}}
button:hover {{filter:brightness(.94)}}
.muted {{font-size:13px;color:var(--muted)}}
.grid {{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));
gap:12px}}
.stat {{padding:15px;border:1px solid var(--line);border-radius:12px;
background:#fff;min-width:0}}
.stat span {{display:block;color:var(--muted);font-size:12px}}
.stat strong {{display:block;color:var(--navy);font-size:22px;
overflow-wrap:anywhere}}
.score {{font-size:48px;font-weight:800;color:var(--teal);line-height:1.2}}
.score-label {{font-size:13px;color:var(--muted)}}
table {{width:100%;border-collapse:collapse}}
th,td {{padding:12px 9px;text-align:left;vertical-align:top;
border-bottom:1px solid var(--line);overflow-wrap:anywhere}}
th {{color:var(--navy);font-size:13px}}
.pass {{color:var(--green);font-weight:700}}
.review {{color:var(--amber);font-weight:700}}
.error {{background:#fff1f0;color:#922b21;padding:14px;border-radius:10px}}
a {{color:var(--teal);font-weight:700}}
footer {{text-align:center;padding:26px 16px;color:var(--muted);font-size:13px}}
@media(max-width:520px) {{
 main {{padding:16px 12px 36px}}
 .card {{padding:16px}}
 form button {{width:100%}}
 th,td {{padding:9px 5px;font-size:13px}}
 .nav small {{font-size:11px}}
}}
@media print {{
 body {{background:white}}
 header,footer,form,.no-print {{display:none!important}}
 main {{padding:0;max-width:none}}
 .card {{box-shadow:none;break-inside:avoid}}
}}
</style>
</head>
<body>
<header><div class="nav">
<div class="brand">EAQ<span>.</span></div>
<small>SEO Audit Platform</small>
</div></header>
<main>{content}</main>
<footer>EAQ SEO Audit · Analyze. Optimize. Grow.</footer>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def home():
    content = """
<section class="hero">
<div class="eyebrow">Website intelligence</div>
<h1>Understand your SEO.<br>Improve your website.</h1>
<p>Find on-page SEO issues, review important technical signals,
and get clear recommendations to help improve your website.</p>
</section>
<section class="card">
<h2>Start your website audit</h2>
<p class="muted">Enter a public website URL to analyze its on-page elements.</p>
<form method="post" action="/audit">
<input type="url" name="url" maxlength="2048"
placeholder="https://example.com" required>
<button type="submit">Analyze Website →</button>
</form>
<p class="muted">The EAQ score is an internal heuristic, not a Google ranking score.</p>
</section>
<section class="grid">
<div class="card"><h3>On-page SEO</h3>
<p class="muted">Titles, descriptions, headings, images and links.</p></div>
<div class="card"><h3>Technical signals</h3>
<p class="muted">HTTPS, canonical tags, viewport and robots directives.</p></div>
<div class="card"><h3>Actionable findings</h3>
<p class="muted">Identify issues and review practical next steps.</p></div>
</section>
"""
    return render_page(content)


@app.post("/audit", response_class=HTMLResponse)
def audit(request: Request, url: str = Form(...)):
    client_ip = request.client.host if request.client else "unknown"

    if not check_rate_limit(client_ip):
        content = """
<section class="card">
<h1>Too many requests</h1>
<p>Please wait a minute before starting another audit.</p>
<p><a href="/">Return to EAQ SEO Audit</a></p>
</section>
"""
        return HTMLResponse(
            render_page(content),
            status_code=429,
            headers={"Retry-After": str(RATE_WINDOW)},
        )

    try:
        final_url, html, status_code = fetch_public_page(url)
        result = analyze_page(final_url, html, status_code)

        rows = "".join(
            "<tr>"
            f"<td>{escape(item['name'])}</td>"
            f"<td class=\"{'pass' if item['status'] == 'PASS' else 'review'}\">"
            f"{escape(item['status'])}</td>"
            f"<td>{escape(item['detail'])}</td>"
            "</tr>"
            for item in result["findings"]
        )

        content = f"""
<section class="hero">
<div class="eyebrow">Audit report</div>
<h1>Your SEO overview</h1>
<p>{escape(result['url'])}</p>
</section>
<section class="card">
<div class="score">{result['score']}<span style="font-size:22px">/100</span></div>
<div class="score-label">EAQ heuristic score · not a Google score</div>
<p class="muted">This score summarizes the checks below. It does not predict
search rankings and should be interpreted alongside the individual findings.</p>
</section>
<section class="card">
<h2>Page overview</h2>
<div class="grid">
<div class="stat"><span>HTTP status</span><strong>{result['status_code']}</strong></div>
<div class="stat"><span>Title characters</span><strong>{result['title_length']}</strong></div>
<div class="stat"><span>Description characters</span><strong>{result['description_length']}</strong></div>
<div class="stat"><span>H1 / H2 headings</span><strong>{result['h1_count']} / {result['h2_count']}</strong></div>
<div class="stat"><span>Images missing alt</span><strong>{result['missing_alt_count']} / {result['image_count']}</strong></div>
<div class="stat"><span>Internal links</span><strong>{result['internal_links']}</strong></div>
<div class="stat"><span>External links</span><strong>{result['external_links']}</strong></div>
<div class="stat"><span>Approx. word count</span><strong>{result['word_count']}</strong></div>
</div>
</section>
<section class="card">
<h2>Metadata</h2>
<p><strong>Title:</strong> {escape(result['title'])}</p>
<p><strong>Meta description:</strong> {escape(result['description'])}</p>
<p><strong>Canonical URL:</strong> {escape(result['canonical'])}</p>
</section>
<section class="card">
<h2>Checks and recommendations</h2>
<div style="overflow-x:auto"><table>
<thead><tr><th>Check</th><th>Status</th><th>Finding</th></tr></thead>
<tbody>{rows}</tbody>
</table></div>
<p class="no-print"><button type="button" onclick="window.print()">Print / Save as PDF</button></p>
</section>
<p class="no-print"><a href="/">← Analyze another website</a></p>
"""
        return render_page(content)

    except (ValueError, requests.RequestException) as exc:
        content = f"""
<section class="card">
<h1>Unable to complete the audit</h1>
<div class="error">{escape(str(exc))}</div>
<p>Check the URL and try again. Some websites block automated requests.</p>
<p><a href="/">← Return to EAQ SEO Audit</a></p>
</section>
"""
        return HTMLResponse(render_page(content), status_code=400)


@app.get("/health")
def health():
    return JSONResponse({
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
    })
