
import ipaddress
import os
import socket
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.trustedhost import TrustedHostMiddleware

APP_NAME = "EAQ SEO Audit"
MAX_HTML_BYTES = 1_500_000
TIMEOUT = 12
USER_AGENT = "EAQSEOAudit/1.0 (+https://eaq.io)"

app = FastAPI(title=APP_NAME, version="1.0.0")


def is_public_host(hostname: str) -> bool:
    """Reject localhost, private IPs and non-public DNS results."""
    if not hostname or hostname.lower() in {
        "localhost", "localhost.localdomain"
    }:
        return False

    try:
        addresses = {ipaddress.ip_address(hostname)}
    except ValueError:
        try:
            records = socket.getaddrinfo(
                hostname, None, type=socket.SOCK_STREAM
            )
            addresses = {
                ipaddress.ip_address(record[4][0])
                for record in records
            }
        except (socket.gaierror, ValueError, OSError):
            return False

    return bool(addresses) and all(
        address.is_global for address in addresses
    )


def validate_url(url: str) -> str:
    url = (url or "").strip()

    if not url or len(url) > 2048:
        raise ValueError("Please enter a valid website URL.")

    if "://" not in url:
        url = "https://" + url

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only HTTP and HTTPS URLs are supported.")

    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Please enter a valid public website URL.")

    if not is_public_host(parsed.hostname):
        raise ValueError("This hostname is not allowed.")

    return url


def safe_fetch(url: str):
    """Fetch a public page without automatically following redirects."""
    current_url = validate_url(url)

    for _ in range(4):
        response = requests.get(
            current_url,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
            allow_redirects=False,
            stream=True,
        )

        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("location")
            response.close()

            if not location:
                raise ValueError("The website returned an invalid redirect.")

            current_url = validate_url(urljoin(current_url, location))
            continue

        response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()
        if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            response.close()
            raise ValueError("The URL does not return an HTML page.")

        chunks = []
        size = 0

        try:
            for chunk in response.iter_content(chunk_size=16384):
                if not chunk:
                    continue

                size += len(chunk)
                if size > MAX_HTML_BYTES:
                    raise ValueError("The page is too large to analyze.")

                chunks.append(chunk)
        finally:
            response.close()

        encoding = response.encoding or "utf-8"
        html = b"".join(chunks).decode(encoding, errors="replace")
        return current_url, html, response.status_code

    raise ValueError("Too many redirects.")


def analyze_page(url: str, html: str, status_code: int) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    for element in soup(["script", "style", "noscript", "svg"]):
        element.decompose()

    title_tag = soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else ""

    description_tag = soup.find(
        "meta", attrs={"name": lambda value: value and value.lower() == "description"}
    )
    description = (
        description_tag.get("content", "").strip()
        if description_tag else ""
    )

    h1_tags = soup.find_all("h1")
    h2_tags = soup.find_all("h2")

    images = soup.find_all("img")
    images_missing_alt = [
        image for image in images
        if image.get("alt") is None or not image.get("alt", "").strip()
    ]

    links = soup.find_all("a", href=True)
    internal_links = []
    external_links = []

    base_host = (urlparse(url).hostname or "").lower()

    for link in links:
        href = link.get("href", "").strip()
        if not href or href.startswith(
            ("#", "mailto:", "tel:", "javascript:", "data:")
        ):
            continue

        absolute = urljoin(url, href)
        parsed_link = urlparse(absolute)

        if parsed_link.scheme not in ("http", "https"):
            continue

        if (parsed_link.hostname or "").lower() == base_host:
            internal_links.append(absolute)
        else:
            external_links.append(absolute)

    canonical_tag = soup.find(
        "link",
        rel=lambda value: value and "canonical" in [
            item.lower() for item in (
                value if isinstance(value, list) else value.split()
            )
        ],
    )
    canonical = canonical_tag.get("href", "").strip() if canonical_tag else ""

    robots_tag = soup.find(
        "meta",
        attrs={"name": lambda value: value and value.lower() == "robots"},
    )
    robots_meta = robots_tag.get("content", "").strip() if robots_tag else ""

    viewport_tag = soup.find(
        "meta",
        attrs={"name": lambda value: value and value.lower() == "viewport"},
    )

    text = soup.get_text(" ", strip=True)
    word_count = len(text.split())

    checks = [
        ("HTTP response", status_code < 400, f"HTTP {status_code}"),
        ("HTTPS enabled", urlparse(url).scheme == "https",
         "Use HTTPS to secure your website."),
        ("Title tag", bool(title), "Add a descriptive title tag."),
        ("Title length", 30 <= len(title) <= 60,
         f"Title length is {len(title)} characters; aim for about 30–60."),
        ("Meta description", bool(description),
         "Add a unique meta description."),
        ("Description length", 120 <= len(description) <= 160,
         f"Description length is {len(description)} characters; aim for about 120–160."),
        ("H1 heading", len(h1_tags) == 1,
         f"Found {len(h1_tags)} H1 headings; aim for one clear main heading."),
        ("Images alt text", len(images_missing_alt) == 0,
         f"{len(images_missing_alt)} of {len(images)} images have missing or empty alt text."),
        ("Canonical URL", bool(canonical),
         "Consider adding a canonical link when appropriate."),
        ("Mobile viewport", viewport_tag is not None,
         "Add a responsive viewport meta tag."),
        ("Content length", word_count >= 300,
         f"Found approximately {word_count} words; review whether the page answers user needs."),
        ("Robots meta", "noindex" not in robots_meta.lower(),
         "The robots meta tag contains noindex; verify that this is intentional."),
    ]

    passed = sum(1 for _, ok, _ in checks if ok)
    score = round(100 * passed / len(checks))

    findings = []
    for name, ok, detail in checks:
        if ok:
            findings.append({
                "name": name,
                "status": "PASS",
                "detail": detail if name in ("HTTP response",) else "Check passed.",
            })
        else:
            findings.append({
                "name": name,
                "status": "REVIEW",
                "detail": detail,
            })

    return {
        "url": url,
        "status_code": status_code,
        "score": score,
        "title": title or "Missing",
        "title_length": len(title),
        "description": description or "Missing",
        "description_length": len(description),
        "h1_count": len(h1_tags),
        "h2_count": len(h2_tags),
        "image_count": len(images),
        "images_missing_alt": len(images_missing_alt),
        "internal_links": len(internal_links),
        "external_links": len(external_links),
        "word_count": word_count,
        "canonical": canonical or "Not found",
        "findings": findings,
    }


def escape(value) -> str:
    from html import escape as html_escape
    return html_escape(str(value), quote=True)


def page(content: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Analyze website SEO issues and get practical optimization recommendations with EAQ SEO Audit.">
<title>EAQ SEO Audit — Free Website SEO Analysis</title>
<style>
:root {{
  color-scheme: light;
  --navy: #10243a;
  --teal: #087f8c;
  --bg: #f3f6fa;
  --text: #1c2938;
  --muted: #627184;
  --border: #dce4ed;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--bg); color: var(--text);
  font-family: Arial, Helvetica, sans-serif; line-height: 1.6;
}}
header {{ background: var(--navy); color: white; padding: 18px 20px; }}
.nav {{ max-width: 1080px; margin: auto; display: flex;
  align-items: center; justify-content: space-between; gap: 12px; }}
.logo {{ font-size: 25px; font-weight: 800; letter-spacing: 1px; }}
.logo span {{ color: #5dd5d0; }}
.nav small {{ color: #d4e2ef; }}
main {{ max-width: 1000px; margin: 0 auto; padding: 30px 16px 56px; }}
.hero {{ text-align: center; padding: 26px 0 22px; }}
.hero h1 {{ color: var(--navy); font-size: clamp(30px, 5vw, 44px);
  line-height: 1.15; margin: 0 0 14px; }}
.hero p {{ max-width: 680px; margin: auto; color: var(--muted); }}
.card {{ background: white; border: 1px solid var(--border);
  border-radius: 16px; padding: 22px; margin: 20px 0;
  box-shadow: 0 8px 24px rgba(16,36,58,.04); }}
form {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 16px; }}
input[type=url] {{ flex: 1 1 260px; min-width: 0; padding: 15px;
  border: 1px solid #c7d3e0; border-radius: 9px; font-size: 16px; }}
button {{ border: 0; border-radius: 9px; background: var(--teal);
  color: white; padding: 14px 22px; font-size: 16px; font-weight: 700;
  cursor: pointer; }}
button:hover {{ filter: brightness(.93); }}
.muted {{ color: var(--muted); font-size: 14px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(190px,1fr));
  gap: 13px; }}
.stat {{ padding: 16px; border: 1px solid var(--border); border-radius: 12px; }}
.stat strong {{ display: block; color: var(--navy); font-size: 23px; overflow-wrap: anywhere; }}
.stat span {{ color: var(--muted); font-size: 13px; }}
.score {{ font-size: 44px; font-weight: 800; color: var(--teal); }}
table {{ width: 100%; border-collapse: collapse; }}
th,td {{ text-align: left; padding: 11px 8px; border-bottom: 1px solid var(--border);
  vertical-align: top; overflow-wrap: anywhere; }}
th {{ color: var(--navy); }}
.pass {{ color: #137448; font-weight: 700; }}
.review {{ color: #a15c00; font-weight: 700; }}
.error {{ color: #a32626; background: #fff1f0; border-radius: 10px; padding: 14px; }}
footer {{ text-align: center; color: var(--muted); padding: 24px 16px; }}
@media(max-width:520px) {{
  .card {{ padding: 16px; }}
  form button {{ width: 100%; }}
  th,td {{ padding: 9px 5px; font-size: 14px; }}
}}
</style>
</head>
<body>
<header><div class="nav">
<div class="logo">EAQ<span>.</span></div>
<small>SEO Audit · Website Analysis</small>
</div></header>
<main>
{content}
</main>
<footer>EAQ SEO Audit · Analyze. Optimize. Grow.</footer>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def home():
    content = """
<section class="hero">
<h1>Free Website SEO Analysis</h1>
<p>Discover technical SEO issues, review on-page elements, and get clear recommendations to improve your website.</p>
</section>
<section class="card">
<h2>Analyze your website</h2>
<p class="muted">Enter a public website URL to start a basic on-page SEO audit.</p>
<form method="post" action="/audit">
<input type="url" name="url" placeholder="https://example.com" required maxlength="2048">
<button type="submit">Analyze Website</button>
</form>
<p class="muted">This first version provides heuristic checks, not an official Google ranking score.</p>
</section>
<section class="grid">
<div class="card"><h3>On-Page SEO</h3><p class="muted">Titles, descriptions, headings, images, and links.</p></div>
<div class="card"><h3>Technical Checks</h3><p class="muted">HTTPS, canonical tags, and mobile viewport.</p></div>
<div class="card"><h3>Actionable Findings</h3><p class="muted">Review issues and prioritize improvements.</p></div>
</section>
"""
    return page(content)


@app.post("/audit", response_class=HTMLResponse)
def audit(url: str = Form(...)):
    try:
        final_url, html, status_code = safe_fetch(url)
        result = analyze_page(final_url, html, status_code)

        rows = "".join(
            f"<tr><td>{escape(item['name'])}</td>"
            f"<td class=\"{'pass' if item['status'] == 'PASS' else 'review'}\">{escape(item['status'])}</td>"
            f"<td>{escape(item['detail'])}</td></tr>"
            for item in result["findings"]
        )

        content = f"""
<section class="hero">
<h1>SEO Audit Report</h1>
<p>Analysis for <strong>{escape(result['url'])}</strong></p>
</section>
<section class="card">
<div class="score">{result['score']}/100</div>
<p class="muted">EAQ heuristic score based on the checks below. It is not a Google score or ranking prediction.</p>
</section>
<section class="card">
<h2>Page Overview</h2>
<div class="grid">
<div class="stat"><span>HTTP Status</span><strong>{result['status_code']}</strong></div>
<div class="stat"><span>Title Length</span><strong>{result['title_length']}</strong></div>
<div class="stat"><span>Meta Description Length</span><strong>{result['description_length']}</strong></div>
<div class="stat"><span>H1 / H2 Headings</span><strong>{result['h1_count']} / {result['h2_count']}</strong></div>
<div class="stat"><span>Images Missing Alt</span><strong>{result['images_missing_alt']} / {result['image_count']}</strong></div>
<div class="stat"><span>Internal / External Links</span><strong>{result['internal_links']} / {result['external_links']}</strong></div>
<div class="stat"><span>Approx. Word Count</span><strong>{result['word_count']}</strong></div>
</div>
</section>
<section class="card">
<h2>Page Metadata</h2>
<p><strong>Title:</strong> {escape(result['title'])}</p>
<p><strong>Description:</strong> {escape(result['description'])}</p>
<p><strong>Canonical:</strong> {escape(result['canonical'])}</p>
</section>
<section class="card">
<h2>Checks and Recommendations</h2>
<div style="overflow-x:auto"><table>
<thead><tr><th>Check</th><th>Status</th><th>Finding</th></tr></thead>
<tbody>{rows}</tbody>
</table></div>
<p><button type="button" onclick="window.print()">Print / Save as PDF</button></p>
</section>
<p><a href="/">← Analyze another website</a></p>
"""
        return page(content)

    except (ValueError, requests.RequestException) as exc:
        content = f"""
<section class="card">
<h1>Unable to complete the audit</h1>
<div class="error">{escape(str(exc))}</div>
<p>Please check the URL and try again.</p>
<p><a href="/">← Return to EAQ SEO Audit</a></p>
</section>
"""
        return page(content)


@app.get("/health")
def health():
    return {"status": "ok", "app": APP_NAME, "version": "1.0.0"}
  
