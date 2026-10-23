import os
import re
import json
import time
import socket
import ipaddress
import sqlite3
import logging
import threading
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin
from xml.etree import ElementTree
from html import escape

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse


# ============================================================
# EAQ SEO AUDIT — VERSION 5.1.0
# ============================================================

APP_NAME = "EAQ SEO Audit"
APP_VERSION = "5.1.0"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    os.path.join(BASE_DIR, "eaq_audit.sqlite3")
)

REQUEST_TIMEOUT = 12
MAX_REDIRECTS = 5
MAX_LINKS_TO_CHECK = 25
MAX_HTML_BYTES = 2_000_000
MAX_URL_LENGTH = 2048
USER_AGENT = (
    "EAQSEOAudit/5.1 "
    "(Technical website diagnostics; respectful rate limits)"
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("eaq")

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Technical SEO audit and website diagnostics"
)

_db_lock = threading.Lock()


# ============================================================
# GENERAL HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).isoformat()


def e(value):
    return escape(str(value if value is not None else ""), quote=True)


def db_connection():
    connection = sqlite3.connect(DATABASE_PATH, timeout=20)
    connection.row_factory = sqlite3.Row
    return connection


def init_database():
    with _db_lock:
        with db_connection() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    report_json TEXT NOT NULL
                )
            """)
            connection.commit()


init_database()


# ============================================================
# HTML LAYOUT
# ============================================================

def page_template(title, body, lang="en"):
    language = "ar" if lang == "ar" else "en"
    direction = "rtl" if language == "ar" else "ltr"

    if language == "ar":
        home_text = "الرئيسية"
        reports_text = "التقارير"
        health_text = "حالة الخدمة"
        arabic_text = "العربية"
        english_text = "English"
        footer_text = (
            "فحوصات تقنية للمواقع؛ النتائج إرشادية وليست ضمانًا "
            "لتحسين ترتيب Google."
        )
    else:
        home_text = "Home"
        reports_text = "Reports"
        health_text = "Health"
        arabic_text = "العربية"
        english_text = "English"
        footer_text = (
            "Technical diagnostics, not a guarantee of Google rankings."
        )

    return f"""<!doctype html>
<html lang="{language}" dir="{direction}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>{e(title)} | EAQ SEO Audit</title>
<style>
:root {{
 --bg:#f3f6fb;--card:#fff;--text:#17253b;--muted:#64748b;
 --primary:#1456d9;--border:#dce4ef;--green:#16804a;
 --red:#bd3434;--orange:#a45a00;
}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:Arial,Helvetica,sans-serif;
 background:var(--bg);color:var(--text);line-height:1.7}}
header{{background:#102747;color:white;padding:20px 16px}}
nav,.container{{max-width:1100px;margin:auto}}
nav{{display:flex;align-items:center;justify-content:space-between;
 gap:14px;flex-wrap:wrap}}
nav a{{color:white;text-decoration:none;margin-inline-start:12px}}
.brand{{font-size:22px;font-weight:800}}
.container{{padding:24px 16px 48px}}
.card{{background:var(--card);border:1px solid var(--border);
 border-radius:15px;padding:22px;margin-bottom:18px;
 box-shadow:0 4px 16px rgba(20,40,80,.035)}}
h1{{font-size:clamp(25px,4vw,38px);line-height:1.3}}
h2{{font-size:22px;margin-top:0}}
h3{{font-size:17px}}
.muted{{color:var(--muted)}}
.small{{font-size:13px}}
label{{display:block;font-weight:700;margin:12px 0 5px}}
input[type=url],input[type=text],select{{
 width:100%;border:1px solid #cbd5e1;border-radius:9px;
 padding:12px;background:white;font-size:16px}}
button,.button{{border:0;border-radius:9px;background:var(--primary);
 color:white;padding:12px 18px;font-size:15px;font-weight:700;
 cursor:pointer;text-decoration:none;display:inline-block}}
button:disabled{{opacity:.6;cursor:wait}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
 gap:14px}}
.metric{{background:#f8faff;border:1px solid var(--border);
 padding:16px;border-radius:12px;overflow-wrap:anywhere}}
.metric strong{{font-size:27px;display:block}}
table{{width:100%;border-collapse:collapse}}
th,td{{padding:11px 9px;border-bottom:1px solid var(--border);
 text-align:start;vertical-align:top;overflow-wrap:anywhere}}
th{{background:#f4f7fc}}
.table-wrap{{overflow-x:auto}}
.status-pass{{color:var(--green);font-weight:700}}
.status-fail{{color:var(--red);font-weight:700}}
.status-warn{{color:var(--orange);font-weight:700}}
.notice{{background:#fff8e7;border:1px solid #f1d28a;
 border-radius:10px;padding:12px 15px}}
.pill{{display:inline-block;padding:4px 9px;border-radius:30px;
 background:#e8efff;color:#1848a8;font-size:12px;font-weight:700}}
a{{color:var(--primary)}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere}}
footer{{text-align:center;color:var(--muted);padding:20px 12px}}
@media print{{header,.no-print,footer{{display:none!important}}
 body{{background:white}}.card{{box-shadow:none;break-inside:avoid}}
 .container{{max-width:none}}}}
</style>
</head>
<body>
<header>
<nav>
 <div class="brand">EAQ <span style="color:#7db1ff">SEO AUDIT</span></div>
 <div>
  <a href="/?lang={language}">{home_text}</a>
  <a href="/reports?lang={language}">{reports_text}</a>
  <a href="/health">{health_text}</a>
  <a href="/?lang=ar">{arabic_text}</a>
  <a href="/?lang=en">{english_text}</a>
 </div>
</nav>
</header>
<main class="container">
{body}
</main>
<footer>EAQ SEO Audit v{APP_VERSION} · {footer_text}</footer>
</body>
</html>"""


def error_page(message, lang="en", status_code=400):
    title = "حدث خطأ" if lang == "ar" else "Error"
    label = "العودة للرئيسية" if lang == "ar" else "Return home"
    body = f"""
    <section class="card">
      <h1>{e(title)}</h1>
      <p>{e(message)}</p>
      <a class="button" href="/?lang={e(lang)}">{e(label)}</a>
    </section>
    """
    return HTMLResponse(
        page_template(title, body, lang),
        status_code=status_code
    )


# ============================================================
# URL VALIDATION AND NETWORK SAFETY
# ============================================================

def normalize_url(raw_url):
    raw_url = (raw_url or "").strip()

    if not raw_url:
        raise ValueError("Please enter a website URL.")

    if len(raw_url) > MAX_URL_LENGTH:
        raise ValueError("The URL is too long.")

    if not re.match(r"^https?://", raw_url, re.IGNORECASE):
        raw_url = "https://" + raw_url

    try:
        parsed = urlparse(raw_url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("The URL contains an invalid host or port.")

    scheme = parsed.scheme.lower()

    if scheme not in ("http", "https"):
        raise ValueError("Only HTTP and HTTPS URLs are supported.")

    if not hostname:
        raise ValueError("The URL must contain a valid hostname.")

    if parsed.username or parsed.password:
        raise ValueError("URLs containing credentials are not allowed.")

    if port is not None:
        allowed = (
            scheme == "http" and port == 80
        ) or (
            scheme == "https" and port == 443
        )
        if not allowed:
            raise ValueError("Only standard HTTP/HTTPS ports are allowed.")

    host = hostname.rstrip(".").lower()

    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("Local hostnames are not allowed.")

    if host.endswith((".local", ".internal", ".test", ".invalid")):
        raise ValueError("Private or reserved hostnames are not allowed.")

    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            raise ValueError("Private or reserved IP addresses are not allowed.")
    except ValueError as exc:
        if "not allowed" in str(exc):
            raise
        # A domain name is expected if parsing as an IP address fails.

    return raw_url


def hostname_is_public(host):
    host = (host or "").rstrip(".").lower()

    if not host or host == "localhost":
        return False

    if host.endswith((".local", ".localhost", ".internal", ".test", ".invalid")):
        return False

    try:
        ip = ipaddress.ip_address(host)
        return ip.is_global
    except ValueError:
        pass

    try:
        records = socket.getaddrinfo(
            host, None, type=socket.SOCK_STREAM
        )
    except (socket.gaierror, OSError):
        return False

    if not records:
        return False

    # Reject a hostname if any resolved address is non-public.
    for record in records:
        address = record[4][0]
        try:
            if not ipaddress.ip_address(address).is_global:
                return False
        except ValueError:
            return False

    return True


def safe_get(raw_url, timeout=REQUEST_TIMEOUT, max_bytes=MAX_HTML_BYTES):
    """
    Fetch a public HTTP(S) URL with redirect validation and a response
    size limit. This is a defensive layer, not a complete defense against
    every DNS-rebinding or network-level SSRF scenario.
    """
    current_url = normalize_url(raw_url)
    session = requests.Session()
    session.trust_env = False
    response = None

    try:
        for _ in range(MAX_REDIRECTS + 1):
            parsed = urlparse(current_url)

            if not hostname_is_public(parsed.hostname):
                raise ValueError(
                    "The hostname is private, reserved, or cannot be resolved safely."
                )

            response = session.get(
                current_url,
                headers={"User-Agent": USER_AGENT},
                timeout=timeout,
                allow_redirects=False,
                stream=True
            )

            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    return response

                next_url = urljoin(current_url, location)
                response.close()
                response = None
                current_url = normalize_url(next_url)
                continue

            content = bytearray()

            for chunk in response.iter_content(chunk_size=16384):
                if not chunk:
                    continue

                remaining = max_bytes - len(content)
                if remaining <= 0:
                    break

                content.extend(chunk[:remaining])

                if len(content) >= max_bytes:
                    break

            response._content = bytes(content)
            response._content_consumed = True
            return response

        raise ValueError("Too many redirects.")

    finally:
        if response is not None and response.is_redirect:
            response.close()
        session.close()


def fetch_text(url, timeout=REQUEST_TIMEOUT, max_bytes=MAX_HTML_BYTES):
    response = safe_get(url, timeout=timeout, max_bytes=max_bytes)

    try:
        return {
            "status": response.status_code,
            "url": response.url,
            "headers": dict(response.headers),
            "text": response.text,
            "content_type": response.headers.get("Content-Type", "")
        }
    finally:
        response.close()


# ============================================================
# DOMAIN HELPERS
# ============================================================

def get_domain(url):
    return (urlparse(url).hostname or "").lower().rstrip(".")


def registrable_domain(host):
    """
    Approximation only. This does not implement the complete Public Suffix
    List; domains with unusual suffixes may need manual verification.
    """
    host = (host or "").lower().strip(".")
    parts = host.split(".")

    if len(parts) <= 2:
        return host

    common_two_level_suffixes = {
        "co.uk", "org.uk", "me.uk", "ac.uk", "gov.uk",
        "com.au", "net.au", "org.au",
        "co.nz", "org.nz",
        "co.jp", "co.in",
        "com.br", "com.cn", "com.sg",
        "com.mx", "com.tr", "com.sa"
    }

    suffix2 = ".".join(parts[-2:])

    if suffix2 in common_two_level_suffixes:
        return ".".join(parts[-3:])

    return ".".join(parts[-2:])


# ============================================================
# TECHNICAL SEO CHECKS
# ============================================================

def add_check(checks, name, passed, details, severity="warning"):
    checks.append({
        "name": name,
        "passed": bool(passed),
        "details": str(details),
        "severity": severity
    })


def check_robots_and_sitemap(base_url):
    results = {}

    targets = {
        "robots": urljoin(base_url, "/robots.txt"),
        "sitemap": urljoin(base_url, "/sitemap.xml")
    }

    for key, target in targets.items():
        try:
            result = fetch_text(
                target, timeout=8, max_bytes=300000
            )
            results[key] = {
                "url": result["url"],
                "status": result["status"],
                "text": result["text"][:100000],
                "content_type": result["content_type"]
            }
        except Exception as exc:
            results[key] = {
                "url": target,
                "status": None,
                "text": "",
                "error": str(exc)[:250]
            }

    return results


def sitemap_and_status_ok(results, sitemap_is_xml):
    return (
        results["sitemap"].get("status") == 200
        and sitemap_is_xml
    )


def run_technical_audit(url):
    checks = []
    supplementary = {}

    response = safe_get(url)
    try:
        final_url = response.url
        status = response.status_code
        content_type = response.headers.get("Content-Type", "")
        html = response.text[:MAX_HTML_BYTES]
        headers = dict(response.headers)
    finally:
        response.close()

    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else ""

    description_tag = soup.find(
        "meta", attrs={"name": re.compile(r"^description$", re.I)}
    )
    description = (
        description_tag.get("content", "").strip()
        if description_tag else ""
    )

    canonical_tag = soup.find(
        "link",
        attrs={
            "rel": lambda value: (
                value and "canonical" in [
                    str(item).lower()
                    for item in (
                        value if isinstance(value, list) else [value]
                    )
                ]
            )
        }
    )
    canonical = (
        canonical_tag.get("href", "").strip()
        if canonical_tag else ""
    )

    h1_tags = soup.find_all("h1")
    images = soup.find_all("img")
    images_missing_alt = [
        image for image in images if not image.has_attr("alt")
    ]

    viewport = soup.find(
        "meta", attrs={"name": re.compile(r"^viewport$", re.I)}
    )

    charset_value = ""
    charset = soup.find("meta", attrs={"charset": True})

    if charset:
        charset_value = charset.get("charset", "")

    if not charset_value:
        equiv = soup.find(
            "meta",
            attrs={"http-equiv": re.compile(r"^content-type$", re.I)}
        )
        if equiv:
            charset_value = equiv.get("content", "")

    links = []
    seen_links = set()

    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "").strip()

        if not href or href.startswith(
            ("#", "mailto:", "tel:", "javascript:", "data:")
        ):
            continue

        absolute = urljoin(final_url, href)
        parsed_link = urlparse(absolute)

        if parsed_link.scheme.lower() not in ("http", "https"):
            continue

        if absolute in seen_links:
            continue

        seen_links.add(absolute)
        links.append({
            "url": absolute,
            "text": tag.get_text(" ", strip=True)[:160]
        })

    robots_and_sitemap = check_robots_and_sitemap(final_url)

    supplementary["robots"] = {
        "url": robots_and_sitemap["robots"]["url"],
        "status": robots_and_sitemap["robots"].get("status"),
        "error": robots_and_sitemap["robots"].get("error"),
        "preview": robots_and_sitemap["robots"].get("text", "")[:1200]
    }

    supplementary["sitemap"] = {
        "url": robots_and_sitemap["sitemap"]["url"],
        "status": robots_and_sitemap["sitemap"].get("status"),
        "error": robots_and_sitemap["sitemap"].get("error")
    }

    sitemap_text = robots_and_sitemap["sitemap"].get("text", "")
    sitemap_is_xml = False

    if sitemap_text.strip():
        try:
            ElementTree.fromstring(sitemap_text)
            sitemap_is_xml = True
        except ElementTree.ParseError:
            sitemap_is_xml = False

    add_check(
        checks, "HTTP response",
        200 <= status < 400,
        f"HTTP {status}", "critical"
    )

    add_check(
        checks, "HTML content type",
        "html" in content_type.lower(),
        content_type or "Content-Type header missing"
    )

    add_check(
        checks, "Page title",
        bool(title),
        f"Title: {title[:180]}" if title else "No title tag found"
    )

    add_check(
        checks, "Title length",
        30 <= len(title) <= 60,
        f"{len(title)} characters; 30–60 is a common guideline"
    )

    add_check(
        checks, "Meta description",
        bool(description),
        f"Description: {description[:220]}"
        if description else "Meta description not found"
    )

    add_check(
        checks, "Meta description length",
        70 <= len(description) <= 160,
        f"{len(description)} characters; 70–160 is a common guideline"
    )

    add_check(
        checks, "H1 heading",
        len(h1_tags) >= 1,
        f"{len(h1_tags)} H1 heading(s) found"
    )

    add_check(
        checks, "Single H1",
        len(h1_tags) == 1,
        f"{len(h1_tags)} H1 heading(s); multiple H1s are not automatically an SEO error"
    )

    add_check(
        checks, "Canonical URL",
        bool(canonical),
        canonical or "Canonical link not found"
    )

    if canonical:
        canonical_url = urljoin(final_url, canonical)
        canonical_scheme = urlparse(canonical_url).scheme.lower()
        add_check(
            checks, "Canonical URL format",
            canonical_scheme in ("http", "https"),
            canonical_url
        )
    else:
        add_check(
            checks, "Canonical URL format", False,
            "Cannot evaluate because no canonical link was found"
        )

    add_check(
        checks, "Viewport meta",
        viewport is not None,
        "Viewport meta tag found" if viewport else "Viewport meta tag not found"
    )

    add_check(
        checks, "Character encoding",
        bool(charset_value) or "charset=" in content_type.lower(),
        charset_value or content_type or "Encoding not explicitly detected"
    )

    add_check(
        checks, "Image alt attributes",
        len(images_missing_alt) == 0,
        f"{len(images_missing_alt)} of {len(images)} images lack an alt attribute"
    )

    add_check(
        checks, "HTTPS",
        urlparse(final_url).scheme.lower() == "https",
        final_url
    )

    robots_status = robots_and_sitemap["robots"].get("status")
    add_check(
        checks, "robots.txt",
        robots_status == 200,
        f"HTTP {robots_status}"
        if robots_status is not None
        else robots_and_sitemap["robots"].get("error", "Unavailable")
    )

    sitemap_status = robots_and_sitemap["sitemap"].get("status")
    add_check(
        checks, "Sitemap XML",
        sitemap_status == 200 and sitemap_is_xml,
        (
            f"HTTP {sitemap_status}; XML parsed successfully"
            if sitemap_and_status_ok(robots_and_sitemap, sitemap_is_xml)
            else f"HTTP {sitemap_status}; valid XML not confirmed"
        )
    )

    supplementary.update({
        "title": title,
        "title_length": len(title),
        "description": description,
        "description_length": len(description),
        "h1_count": len(h1_tags),
        "h1_text": [
            tag.get_text(" ", strip=True)[:160]
            for tag in h1_tags[:10]
        ],
        "canonical": canonical,
        "viewport": bool(viewport),
        "image_count": len(images),
        "images_missing_alt": len(images_missing_alt),
        "charset": charset_value,
        "content_type": content_type,
        "server": headers.get("Server", "Not disclosed"),
        "final_url": final_url,
        "link_count": len(links),
        "links": links[:MAX_LINKS_TO_CHECK]
    })

    passed = sum(1 for check in checks if check["passed"])
    score = round(100 * passed / len(checks)) if checks else 0

    return {
        "requested_url": url,
        "final_url": final_url,
        "http_status": status,
        "score": score,
        "passed_checks": passed,
        "total_checks": len(checks),
        "checks": checks,
        "details": supplementary,
        "generated_at": utc_now()
    }


# ============================================================
# LINK CHECKER
# ============================================================

def check_links(urls):
    output = []

    for item in urls[:MAX_LINKS_TO_CHECK]:
        link_url = item.get("url", "")
        link_text = item.get("text", "")

        record = {
            "url": link_url,
            "text": link_text,
            "status": None,
            "result": "",
            "category": "unknown"
        }

        try:
            result = fetch_text(
                link_url, timeout=8, max_bytes=1000
            )
            status = result["status"]
            record["status"] = status

            if 200 <= status < 400:
                record["result"] = "Reachable"
                record["category"] = "ok"
            elif status in (401, 403, 429):
                record["result"] = (
                    "Blocked, restricted, or rate limited; review manually"
                )
                record["category"] = "review"
            elif status in (404, 410):
                record["result"] = "Target reports the resource is missing"
                record["category"] = "broken"
            else:
                record["result"] = f"HTTP {status}; review manually"
                record["category"] = "review"

        except Exception as exc:
            record["result"] = f"Could not verify: {str(exc)[:180]}"
            record["category"] = "unknown"

        output.append(record)
        time.sleep(0.05)

    return output


# ============================================================
# PAGESPEED INSIGHTS
# ============================================================

def get_pagespeed(url, strategy="mobile"):
    endpoint = (
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    )

    params = [
        ("url", url),
        ("strategy", strategy),
        ("category", "PERFORMANCE"),
        ("category", "SEO"),
        ("category", "ACCESSIBILITY"),
        ("category", "BEST_PRACTICES")
    ]

    api_key = os.getenv("PAGESPEED_API_KEY")
    if api_key:
        params.append(("key", api_key))

    try:
        response = requests.get(
            endpoint,
            params=params,
            timeout=45,
            headers={"User-Agent": USER_AGENT}
        )

        if response.status_code != 200:
            return {
                "available": False,
                "strategy": strategy,
                "error": (
                    f"Google PageSpeed returned HTTP {response.status_code}"
                )
            }

        data = response.json()
        lighthouse = data.get("lighthouseResult", {})
        categories = lighthouse.get("categories", {})
        scores = {}

        for key, category in categories.items():
            score = category.get("score")
            scores[key] = (
                round(score * 100)
                if isinstance(score, (int, float)) else None
            )

        audits = lighthouse.get("audits", {})
        selected_audits = {}

        for key in (
            "first-contentful-paint",
            "largest-contentful-paint",
            "speed-index",
            "total-blocking-time",
            "cumulative-layout-shift",
            "interactive"
        ):
            audit = audits.get(key, {})
            selected_audits[key] = {
                "title": audit.get("title", key),
                "display_value": audit.get("displayValue"),
                "numeric_value": audit.get("numericValue"),
                "score": audit.get("score")
            }

        return {
            "available": True,
            "strategy": strategy,
            "scores": scores,
            "metrics": selected_audits,
            "fetch_time": lighthouse.get("fetchTime"),
            "final_url": lighthouse.get("finalDisplayedUrl", url)
        }

    except Exception as exc:
        return {
            "available": False,
            "strategy": strategy,
            "error": str(exc)[:250]
        }


# ============================================================
# RDAP DOMAIN AGE
# ============================================================

def get_domain_age(url):
    domain = registrable_domain(get_domain(url))
    endpoint = f"https://rdap.org/domain/{domain}"

    try:
        response = requests.get(
            endpoint,
            timeout=15,
            headers={
                "Accept": "application/rdap+json, application/json",
                "User-Agent": USER_AGENT
            },
            allow_redirects=True
        )

        if response.status_code != 200:
            return {
                "available": False,
                "domain": domain,
                "error": f"RDAP returned HTTP {response.status_code}"
            }

        data = response.json()
        created = None

        for event in data.get("events", []):
            action = str(event.get("eventAction", "")).lower()
            if action in ("registration", "registered", "creation"):
                created = event.get("eventDate")
                break

        if not created:
            return {
                "available": False,
                "domain": domain,
                "error": "Registration date was not provided by RDAP"
            }

        created_dt = datetime.fromisoformat(
            created.replace("Z", "+00:00")
        )
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=timezone.utc)

        age_days = max(
            0, (datetime.now(timezone.utc) - created_dt).days
        )

        return {
            "available": True,
            "domain": domain,
            "created_at": created,
            "age_days": age_days,
            "age_years": round(age_days / 365.2425, 2)
        }

    except Exception as exc:
        return {
            "available": False,
            "domain": domain,
            "error": str(exc)[:250]
        }


# ============================================================
# WAYBACK MACHINE
# ============================================================

def get_wayback_history(url):
    domain = registrable_domain(get_domain(url))
    endpoint = "https://web.archive.org/cdx/search/cdx"

    params = {
        "url": domain + "/*",
        "output": "json",
        "fl": "timestamp,statuscode",
        "filter": "statuscode:200",
        "collapse": "timestamp:4",
        "from": "1996"
    }

    try:
        response = requests.get(
            endpoint,
            params=params,
            timeout=25,
            headers={"User-Agent": USER_AGENT}
        )

        if response.status_code != 200:
            return {
                "available": False,
                "domain": domain,
                "error": (
                    f"Wayback Machine returned HTTP {response.status_code}"
                )
            }

        data = response.json()

        if not isinstance(data, list) or len(data) <= 1:
            return {
                "available": True,
                "domain": domain,
                "total_returned": 0,
                "years": {},
                "note": "No matching snapshots were returned by this query."
            }

        years = {}

        for row in data[1:]:
            if not row or not row[0] or len(row[0]) < 4:
                continue
            year = row[0][:4]
            years[year] = years.get(year, 0) + 1

        return {
            "available": True,
            "domain": domain,
            "total_returned": len(data) - 1,
            "years": dict(sorted(years.items())),
            "note": (
                "Counts represent records returned by this query, "
                "not a guaranteed total of all archived pages."
            )
        }

    except Exception as exc:
        return {
            "available": False,
            "domain": domain,
            "error": str(exc)[:250]
        }


# ============================================================
# OPTIONAL TRAFFIC ESTIMATE
# ============================================================

def get_traffic_estimate(url):
    domain = registrable_domain(get_domain(url))
    api_key = os.getenv("SIMILARWEB_API_KEY")

    if not api_key:
        return {
            "available": False,
            "domain": domain,
            "message": (
                "Traffic data is not configured. A compatible API "
                "subscription and key are required."
            )
        }

    return {
        "available": False,
        "domain": domain,
        "message": (
            "A Similarweb API key was detected, but no verified endpoint "
            "configuration is available for this subscription."
        )
    }


# ============================================================
# FULL REPORT GENERATION
# ============================================================

def run_full_audit(url, do_pagespeed=True, do_links=True):
    url = normalize_url(url)
    technical = run_technical_audit(url)
    links = []

    if do_links:
        links = check_links(
            technical["details"].get("links", [])
        )

    pagespeed = {
        "mobile": {
            "available": False,
            "error": "Not requested"
        },
        "desktop": {
            "available": False,
            "error": "Not requested"
        }
    }

    if do_pagespeed:
        pagespeed["mobile"] = get_pagespeed(
            technical["final_url"], "mobile"
        )
        pagespeed["desktop"] = get_pagespeed(
            technical["final_url"], "desktop"
        )

    domain_age = get_domain_age(technical["final_url"])
    wayback = get_wayback_history(technical["final_url"])
    traffic = get_traffic_estimate(technical["final_url"])

    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "requested_url": url,
        "final_url": technical["final_url"],
        "created_at": utc_now(),
        "score": technical["score"],
        "technical": technical,
        "links": links,
        "pagespeed": pagespeed,
        "domain_age": domain_age,
        "wayback": wayback,
        "traffic": traffic
    }


def save_report(report):
    with _db_lock:
        with db_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO reports (url, created_at, score, report_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    report.get(
                        "final_url",
                        report.get("requested_url", "")
                    ),
                    report.get("created_at", utc_now()),
                    int(report.get("score", 0)),
                    json.dumps(report, ensure_ascii=False)
                )
            )
            connection.commit()
            return cursor.lastrowid


def get_report(report_id):
    with db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM reports WHERE id = ?",
            (report_id,)
        ).fetchone()

    if not row:
        return None

    try:
        report = json.loads(row["report_json"])
    except (TypeError, json.JSONDecodeError):
        return None

    report["report_id"] = row["id"]
    return report


# ============================================================
# REPORT HTML RENDERING
# ============================================================

def metric_card(label, value, note=""):
    return f"""
    <div class="metric">
      <span class="muted">{e(label)}</span>
      <strong>{e(value)}</strong>
      <div class="small muted">{e(note)}</div>
    </div>
    """


def render_check_table(checks, lang="en"):
    if lang == "ar":
        headings = ("الفحص", "النتيجة", "التفاصيل")
        passed_text = "ناجح"
        failed_text = "يحتاج مراجعة"
    else:
        headings = ("Check", "Result", "Details")
        passed_text = "Pass"
        failed_text = "Review"

    rows = []

    for check in checks:
        passed = check.get("passed", False)
        css = "status-pass" if passed else (
            "status-fail"
            if check.get("severity") == "critical"
            else "status-warn"
        )
        result = passed_text if passed else failed_text

        rows.append(
            "<tr>"
            f"<td>{e(check.get('name', ''))}</td>"
            f'<td class="{css}">{e(result)}</td>'
            f"<td>{e(check.get('details', ''))}</td>"
            "</tr>"
        )

    return f"""
    <div class="table-wrap">
    <table>
      <thead><tr>
        <th>{e(headings[0])}</th>
        <th>{e(headings[1])}</th>
        <th>{e(headings[2])}</th>
      </tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    </div>
    """


def render_links_table(links, lang="en"):
    if lang == "ar":
        headings = ("الرابط", "الحالة", "النتيجة")
    else:
        headings = ("URL", "Status", "Result")

    rows = []

    for item in links:
        url = item.get("url", "")
        status = item.get("status")
        category = item.get("category", "unknown")
        css = (
            "status-pass" if category == "ok"
            else "status-fail" if category == "broken"
            else "status-warn"
        )

        rows.append(
            "<tr>"
            f"<td>{e(url)}</td>"
            f'<td class="{css}">{e(status if status is not None else "N/A")}</td>'
            f"<td>{e(item.get('result', ''))}</td>"
            "</tr>"
        )

    if not rows:
        return (
            "<p class='muted'>لا توجد روابط مفحوصة.</p>"
            if lang == "ar"
            else "<p class='muted'>No links were checked.</p>"
        )

    return f"""
    <div class="table-wrap">
    <table>
      <thead><tr>
        <th>{e(headings[0])}</th>
        <th>{e(headings[1])}</th>
        <th>{e(headings[2])}</th>
      </tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    </div>
    """


def render_pagespeed_section(pagespeed, lang="en"):
    if lang == "ar":
        title = "Google PageSpeed Insights"
        unavailable = "البيانات غير متاحة"
        mobile = "الهاتف"
        desktop = "الحاسوب"
    else:
        title = "Google PageSpeed Insights"
        unavailable = "Data unavailable"
        mobile = "Mobile"
        desktop = "Desktop"

    sections = [f"<h2>{e(title)}</h2>"]

    for key, label in (("mobile", mobile), ("desktop", desktop)):
        result = pagespeed.get(key, {})
        sections.append(f"<h3>{e(label)}</h3>")

        if not result.get("available"):
            sections.append(
                f"<p class='muted'>{e(unavailable)}: "
                f"{e(result.get('error', 'Unknown error'))}</p>"
            )
            continue

        cards = []

        for category, score in result.get("scores", {}).items():
            display = f"{score}/100" if score is not None else "N/A"
            cards.append(metric_card(category.replace("_", " ").title(), display))

        sections.append(
            '<div class="grid">' + "".join(cards) + "</div>"
        )

        rows = []
        for metric, details in result.get("metrics", {}).items():
            rows.append(
                "<tr>"
                f"<td>{e(details.get('title', metric))}</td>"
                f"<td>{e(details.get('display_value') or 'N/A')}</td>"
                "</tr>"
            )

        if rows:
            sections.append(
                "<div class='table-wrap'><table>"
                "<thead><tr><th>Metric</th><th>Value</th></tr></thead>"
                f"<tbody>{''.join(rows)}</tbody></table></div>"
            )

    return "".join(sections)


def render_report(report, lang="en"):
    is_ar = lang == "ar"
    title = "تقرير التدقيق" if is_ar else "Audit report"
    final_url = report.get("final_url", "")
    technical = report.get("technical", {})
    details = technical.get("details", {})
    score = report.get("score", 0)
    report_id = report.get("report_id")

    score_label = "النتيجة التقنية" if is_ar else "Technical score"
    url_label = "الرابط النهائي" if is_ar else "Final URL"
    date_label = "تاريخ الفحص" if is_ar else "Audit date"
    checks_label = "الفحوصات التقنية" if is_ar else "Technical checks"
    links_label = "فحص الروابط" if is_ar else "Link checks"
    domain_label = "عمر النطاق" if is_ar else "Domain age"
    history_label = "أرشيف Wayback" if is_ar else "Wayback history"
    print_label = "طباعة التقرير" if is_ar else "Print report"
    report_label = "رقم التقرير" if is_ar else "Report ID"

    domain_age = report.get("domain_age", {})
    if domain_age.get("available"):
        age = f"{domain_age.get('age_years')} years"
    else:
        age = domain_age.get("error", "Unavailable")

    wayback = report.get("wayback", {})
    if wayback.get("available"):
        history_value = wayback.get("total_returned", 0)
        history_note = "returned records" if not is_ar else "سجلًا مسترجعًا"
    else:
        history_value = "N/A"
        history_note = wayback.get("error", "Unavailable")

    h1_text = details.get("h1_text", [])
    h1_html = (
        "<ul>" + "".join(f"<li>{e(item)}</li>" for item in h1_text) + "</ul>"
        if h1_text else (
            "<p>لا توجد عناوين H1.</p>" if is_ar
            else "<p>No H1 headings found.</p>"
        )
    )

    link_html = render_links_table(report.get("links", []), lang)
    checks_html = render_check_table(
        technical.get("checks", []), lang
    )
    pagespeed_html = render_pagespeed_section(
        report.get("pagespeed", {}), lang
    )

    body = f"""
    <section class="card">
      <div class="no-print">
        <button onclick="window.print()">{e(print_label)}</button>
      </div>
      <h1>{e(title)}</h1>
      <p class="muted">{e(report_label)}: {e(report_id or "Not saved")}</p>
      <p><strong>{e(url_label)}:</strong> {e(final_url)}</p>
      <p><strong>{e(date_label)}:</strong> {e(report.get('created_at', ''))}</p>
      <div class="grid">
        {metric_card(score_label, f"{score}/100")}
        {metric_card("HTTP", technical.get("http_status", "N/A"))}
        {metric_card(
            "Checks passed" if not is_ar else "الفحوصات الناجحة",
            f"{technical.get('passed_checks', 0)}/{technical.get('total_checks', 0)}"
        )}
        {metric_card(
            "Links checked" if not is_ar else "الروابط المفحوصة",
            len(report.get("links", []))
        )}
        {metric_card(domain_label, age)}
        {metric_card(history_label, history_value, history_note)}
      </div>
    </section>

    <section class="card">
      <h2>{e(checks_label)}</h2>
      {checks_html}
    </section>

    <section class="card">
      <h2>{e('On-page details' if not is_ar else 'تفاصيل الصفحة')}</h2>
      <div class="grid">
        {metric_card('Title' if not is_ar else 'العنوان', details.get('title') or 'Missing')}
        {metric_card('Title length' if not is_ar else 'طول العنوان', details.get('title_length', 0))}
        {metric_card('Meta description' if not is_ar else 'الوصف', details.get('description') or 'Missing')}
        {metric_card('Description length' if not is_ar else 'طول الوصف', details.get('description_length', 0))}
        {metric_card('Images' if not is_ar else 'الصور', details.get('image_count', 0))}
        {metric_card('Images missing alt' if not is_ar else 'صور دون alt', details.get('images_missing_alt', 0))}
        {metric_card('Links found' if not is_ar else 'الروابط الموجودة', details.get('link_count', 0))}
        {metric_card('Server header' if not is_ar else 'الخادم', details.get('server', 'Not disclosed'))}
      </div>
      <h3>H1</h3>
      {h1_html}
      <p><strong>Canonical:</strong> {e(details.get('canonical') or 'Missing')}</p>
      <p><strong>robots.txt:</strong> {e(details.get('robots', {}).get('status', 'N/A'))}</p>
      <p><strong>Sitemap:</strong> {e(details.get('sitemap', {}).get('status', 'N/A'))}</p>
    </section>

    <section class="card">
      <h2>{e(links_label)}</h2>
      {link_html}
    </section>

    <section class="card">
      {pagespeed_html}
    </section>

    <section class="card">
      <h2>{e('Traffic estimate' if not is_ar else 'تقدير الزيارات')}</h2>
      <p>{e(report.get('traffic', {}).get('message', 'Unavailable'))}</p>
      <p class="muted">
        {'لا يتم اختلاق أرقام الزيارات عند عدم توفر مصدر موثوق.' if is_ar else 'Traffic figures are not invented when no verified data source is configured.'}
      </p>
    </section>
    """

    return page_template(title, body, lang)


# ============================================================
# HOME PAGE
# ============================================================

@app.get("/", response_class=HTMLResponse)
def home(lang: str = Query(default="en")):
    lang = "ar" if lang == "ar" else "en"

    if lang == "ar":
        title = "تدقيق SEO للمواقع"
        intro = (
            "افحص الجوانب التقنية لموقعك، وبيانات الصفحة، والروابط، "
            "وسرعة الأداء، وعمر النطاق، وسجل الأرشفة."
        )
        url_label = "رابط الموقع"
        url_placeholder = "https://example.com"
        submit = "ابدأ التدقيق"
        pagespeed = "تضمين فحص PageSpeed Insights"
        links = "فحص الروابط الداخلية والخارجية"
        disclaimer = (
            "قد تستغرق العملية وقتًا بسبب الخدمات الخارجية. "
            "النتيجة مؤشر تشخيصي وليست مقياسًا رسميًا من Google."
        )
    else:
        title = "Technical SEO audit"
        intro = (
            "Check technical SEO, page metadata, links, PageSpeed, "
            "domain registration data, and Wayback archive history."
        )
        url_label = "Website URL"
        url_placeholder = "https://example.com"
        submit = "Start audit"
        pagespeed = "Include PageSpeed Insights"
        links = "Check internal and external links"
        disclaimer = (
            "The audit may take time because it calls external services. "
            "The score is diagnostic, not an official Google score."
        )

    body = f"""
    <section class="card">
      <span class="pill">EAQ SEO AUDIT {APP_VERSION}</span>
      <h1>{e(title)}</h1>
      <p>{e(intro)}</p>
      <form action="/audit" method="post">
        <input type="hidden" name="lang" value="{e(lang)}">
        <label for="url">{e(url_label)}</label>
        <input id="url" name="url" type="url"
               placeholder="{e(url_placeholder)}"
               maxlength="{MAX_URL_LENGTH}" required>
        <p>
          <label>
            <input type="checkbox" name="do_pagespeed" value="yes" checked>
            {e(pagespeed)}
          </label>
        </p>
        <p>
          <label>
            <input type="checkbox" name="do_links" value="yes" checked>
            {e(links)}
          </label>
        </p>
        <button type="submit">{e(submit)}</button>
      </form>
    </section>
    <section class="card notice">
      <strong>{e('Important' if lang == 'en' else 'ملاحظة')}:</strong>
      {e(disclaimer)}
    </section>
    """

    return page_template(title, body, lang)


# ============================================================
# RUN AUDIT
# ============================================================

@app.post("/audit", response_class=HTMLResponse)
def audit(
    url: str = Form(...),
    lang: str = Form("en"),
    do_pagespeed: str = Form("yes"),
    do_links: str = Form("yes")
):
    lang = "ar" if lang == "ar" else "en"

    try:
        normalized = normalize_url(url)
    except ValueError as exc:
        return error_page(str(exc), lang, 400)

    try:
        report = run_full_audit(
            normalized,
            do_pagespeed=(do_pagespeed == "yes"),
            do_links=(do_links == "yes")
        )
        report_id = save_report(report)
        report["report_id"] = report_id
        return HTMLResponse(render_report(report, lang))

    except ValueError as exc:
        return error_page(str(exc), lang, 400)
    except requests.RequestException as exc:
        logger.warning("Request error during audit: %s", exc)
        return error_page(
            (
                "تعذر الوصول إلى الموقع أو إحدى الخدمات الخارجية."
                if lang == "ar"
                else "The website or an external service could not be reached."
            ),
            lang,
            502
        )
    except Exception:
        logger.exception("Unexpected audit failure")
        return error_page(
            (
                "حدث خطأ أثناء التدقيق. راجع سجلات الخدمة."
                if lang == "ar"
                else "The audit failed unexpectedly. Check the service logs."
            ),
            lang,
            500
        )


# ============================================================
# SAVED REPORTS
# ============================================================

@app.get("/reports", response_class=HTMLResponse)
def reports(lang: str = Query(default="en")):
    lang = "ar" if lang == "ar" else "en"

    with db_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, url, created_at, score
            FROM reports
            ORDER BY id DESC
            LIMIT 100
            """
        ).fetchall()

    if lang == "ar":
        title = "التقارير المحفوظة"
        intro = "آخر 100 تقرير محفوظ."
        empty = "لا توجد تقارير محفوظة حتى الآن."
        headers = ("رقم", "الموقع", "النتيجة", "التاريخ", "عرض")
        view = "فتح التقرير"
    else:
        title = "Saved reports"
        intro = "Latest 100 saved reports."
        empty = "No saved reports yet."
        headers = ("ID", "Website", "Score", "Date", "View")
        view = "Open report"

    if not rows:
        table = f"<p>{e(empty)}</p>"
    else:
        table_rows = []

        for row in rows:
            table_rows.append(
                "<tr>"
                f"<td>{e(row['id'])}</td>"
                f"<td>{e(row['url'])}</td>"
                f"<td>{e(row['score'])}/100</td>"
                f"<td>{e(row['created_at'])}</td>"
                f'<td><a href="/report/{int(row["id"])}?lang={e(lang)}">'
                f"{e(view)}</a></td>"
                "</tr>"
            )

        table = f"""
        <div class="table-wrap">
        <table>
          <thead><tr>
            {''.join(f'<th>{e(h)}</th>' for h in headers)}
          </tr></thead>
          <tbody>{''.join(table_rows)}</tbody>
        </table>
        </div>
        """

    body = f"""
    <section class="card">
      <h1>{e(title)}</h1>
      <p>{e(intro)}</p>
      {table}
    </section>
    """

    return page_template(title, body, lang)


@app.get("/report/{report_id}", response_class=HTMLResponse)
def report_detail(
    report_id: int,
    lang: str = Query(default="en")
):
    lang = "ar" if lang == "ar" else "en"
    report = get_report(report_id)

    if not report:
        return error_page(
            "التقرير غير موجود." if lang == "ar" else "Report not found.",
            lang,
            404
        )

    return HTMLResponse(render_report(report, lang))


# ============================================================
# JSON API
# ============================================================

@app.get("/api/reports/{report_id}")
def report_json(report_id: int):
    report = get_report(report_id)

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    return JSONResponse(content=report)


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():
    try:
        with db_connection() as connection:
            connection.execute("SELECT 1").fetchone()

        return {
            "status": "ok",
            "app": APP_NAME,
            "version": APP_VERSION,
            "database": "ok",
            "timestamp": utc_now()
        }
    except Exception:
        logger.exception("Health check failed")
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "app": APP_NAME,
                "version": APP_VERSION,
                "database": "unavailable",
                "timestamp": utc_now()
            }
        )


# ============================================================
# ROOT-LEVEL API INFORMATION
# ============================================================

@app.get("/api")
def api_info():
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "status": "running",
        "endpoints": {
            "home": "/",
            "health": "/health",
            "reports": "/reports",
            "api_docs": "/docs"
        }
    }
