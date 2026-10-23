
import os
import re
import json
import time
import html
import socket
import sqlite3
import ipaddress
import threading
import xml.etree.ElementTree as ET

from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin, urlunparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse


# ============================================================
# EAQ SEO AUDIT v8.0
# Generic website auditor. No target domain is hardcoded.
# ============================================================

APP_NAME = "EAQ SEO Audit"
APP_VERSION = "8.0.0"

DB_PATH = os.getenv("EAQ_DB_PATH", "eaq_reports.db")
REQUEST_TIMEOUT = 12
MAX_PAGE_BYTES = 2_000_000
MAX_TEXT_BYTES = 500_000
MAX_REDIRECTS = 5
MAX_LINKS_TO_CHECK = 20
MAX_SITEMAP_URLS = 500
MAX_CRAWL_PAGES = 30
MAX_WORKERS = 5

USER_AGENT = "EAQ-SEO-Audit/8.0"
PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY", "").strip()

app = FastAPI(title=APP_NAME, version=APP_VERSION)
audit_lock = threading.Lock()


# ============================================================
# DATABASE
# ============================================================

def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                created_at TEXT NOT NULL,
                score INTEGER NOT NULL,
                result_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_reports_url
            ON reports(url)
        """)
        conn.commit()


init_db()


def save_report(url, result):
    created = datetime.now(timezone.utc).isoformat()
    score = int(result.get("score", 0))

    with db_connect() as conn:
        cur = conn.execute("""
            INSERT INTO reports(url, created_at, score, result_json)
            VALUES (?, ?, ?, ?)
        """, (
            url,
            created,
            score,
            json.dumps(result, ensure_ascii=False),
        ))
        conn.commit()
        return cur.lastrowid, created


def get_reports(limit=30):
    with db_connect() as conn:
        return conn.execute("""
            SELECT id, url, created_at, score
            FROM reports
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()


def get_report(report_id):
    with db_connect() as conn:
        row = conn.execute(
            "SELECT * FROM reports WHERE id = ?",
            (report_id,),
        ).fetchone()

    if not row:
        return None

    result = dict(row)
    result["result_json"] = json.loads(result["result_json"])
    return result


# ============================================================
# SAFE URL VALIDATION
# ============================================================

def is_public_ip(value):
    try:
        ip = ipaddress.ip_address(value)
        return ip.is_global
    except ValueError:
        return False


def validate_public_url(url):
    try:
        parsed = urlparse((url or "").strip())

        if parsed.scheme.lower() not in ("http", "https"):
            return False, "Only HTTP and HTTPS URLs are permitted."

        if not parsed.hostname:
            return False, "URL hostname is missing."

        if parsed.username or parsed.password:
            return False, "URLs containing credentials are not allowed."

        host = parsed.hostname.rstrip(".").lower()

        if not host or "%" in host:
            return False, "Invalid hostname."

        if host in ("localhost", "localhost.localdomain"):
            return False, "Localhost is not allowed."

        # Reject local/internal hostnames without a public DNS suffix.
        if not host.replace(".", "").replace("-", "").isalnum():
            return False, "Invalid hostname syntax."

        try:
            ipaddress.ip_address(host)
            addresses = [host]
        except ValueError:
            try:
                results = socket.getaddrinfo(
                    host,
                    parsed.port or (
                        443 if parsed.scheme.lower() == "https" else 80
                    ),
                    type=socket.SOCK_STREAM,
                )
                addresses = list({
                    item[4][0] for item in results
                })
            except (socket.gaierror, OSError):
                return False, "Hostname could not be resolved."

        if not addresses:
            return False, "No IP addresses found."

        if not all(is_public_ip(addr) for addr in addresses):
            return False, "Non-public IP address blocked."

        # Normalize the URL and remove the fragment.
        netloc = parsed.netloc
        normalized = urlunparse((
            parsed.scheme.lower(),
            netloc,
            parsed.path or "/",
            parsed.params,
            parsed.query,
            "",
        ))

        return True, normalized

    except Exception:
        return False, "Invalid URL."


def safe_get(url, timeout=REQUEST_TIMEOUT, max_bytes=MAX_PAGE_BYTES):
    """
    Fetch a URL with manual redirect validation and a response-size limit.
    This reduces SSRF exposure but is not a substitute for network isolation.
    """
    current = url

    for _ in range(MAX_REDIRECTS + 1):
        valid, checked = validate_public_url(current)

        if not valid:
            raise ValueError(checked)

        with requests.get(
            checked,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            allow_redirects=False,
            stream=True,
        ) as response:

            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")

                if not location:
                    raise ValueError("Redirect has no Location header.")

                current = urljoin(checked, location)
                continue

            # Read a bounded amount of response content.
            content = bytearray()

            for chunk in response.iter_content(chunk_size=16384):
                if not chunk:
                    continue

                content.extend(chunk)

                if len(content) > max_bytes:
                    raise ValueError("Response exceeded size limit.")

            # Raise HTTP errors only after safely limiting the body.
            response._content = bytes(content)
            response._content_consumed = True
            response.raise_for_status()

            return response

    raise ValueError("Too many redirects.")


def normalize_space(value):
    return re.sub(r"\s+", " ", value or "").strip()


def get_meta(soup, name):
    tag = soup.find(
        "meta",
        attrs={"name": re.compile(
            "^" + re.escape(name) + "$", re.I
        )},
    )
    return normalize_space(tag.get("content", "")) if tag else ""


def get_property(soup, name):
    tag = soup.find(
        "meta",
        attrs={"property": re.compile(
            "^" + re.escape(name) + "$", re.I
        )},
    )
    return normalize_space(tag.get("content", "")) if tag else ""


def get_canonical(soup, base_url):
    tag = soup.find(
        "link",
        rel=lambda value: value and "canonical" in [
            item.lower() for item in (
                value if isinstance(value, list) else [value]
            )
        ],
    )

    if tag and tag.get("href"):
        return urljoin(base_url, tag["href"])

    return ""


def count_words(text):
    return len(re.findall(r"\b[\w'-]+\b", text or "", re.UNICODE))


# ============================================================
# PAGE EXTRACTION
# ============================================================

def extract_page_data(url, response):
    content_type = response.headers.get("Content-Type", "")
    html_content = response.text

    if "html" not in content_type.lower() and not (
        "<html" in html_content[:1000].lower()
        or "<!doctype html" in html_content[:1000].lower()
    ):
        raise ValueError(
            "The URL did not return recognizable HTML."
        )

    soup = BeautifulSoup(html_content, "html.parser")

    title = (
        normalize_space(soup.title.get_text(" ", strip=True))
        if soup.title else ""
    )

    description = get_meta(soup, "description")
    robots_meta = get_meta(soup, "robots")

    h1 = [
        normalize_space(tag.get_text(" ", strip=True))
        for tag in soup.find_all("h1")
    ]

    images = soup.find_all("img")
    missing_alt = sum(
        1 for image in images
        if not normalize_space(image.get("alt", ""))
    )

    links = []
    for anchor in soup.find_all("a", href=True):
        href = normalize_space(anchor.get("href", ""))

        if not href or href.startswith(
            ("#", "mailto:", "tel:", "javascript:", "data:")
        ):
            continue

        absolute = urljoin(url, href)
        parsed = urlparse(absolute)

        if parsed.scheme.lower() not in ("http", "https"):
            continue

        if not parsed.hostname:
            continue

        links.append({
            "url": absolute,
            "text": normalize_space(
                anchor.get_text(" ", strip=True)
            )[:140],
        })

    # Remove non-content elements before measuring visible text.
    text_soup = BeautifulSoup(html_content, "html.parser")

    for element in text_soup([
        "script", "style", "noscript", "svg",
        "template", "nav", "footer",
    ]):
        element.decompose()

    body_text = normalize_space(
        text_soup.get_text(" ", strip=True)
    )

    headings = {
        f"h{level}": len(soup.find_all(f"h{level}"))
        for level in range(1, 7)
    }

    viewport = soup.find(
        "meta",
        attrs={"name": re.compile("^viewport$", re.I)},
    )

    charset_tag = soup.find("meta", charset=True)
    charset = charset_tag.get("charset", "") if charset_tag else ""

    if not charset:
        content_type_lower = content_type.lower()
        match = re.search(r"charset=([^;\s]+)", content_type_lower)
        charset = match.group(1) if match else ""

    language = normalize_space(
        soup.html.get("lang", "")
    ) if soup.html else ""

    emails = sorted(set(re.findall(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        html_content,
        flags=re.I,
    )))[:10]

    phones = sorted(set(re.findall(
        r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)",
        body_text,
    )))[:10]

    return {
        "url": url,
        "status_code": response.status_code,
        "content_type": content_type,
        "title": title,
        "title_length": len(title),
        "description": description,
        "description_length": len(description),
        "h1": h1,
        "h1_count": len(h1),
        "canonical": get_canonical(soup, url),
        "viewport": bool(viewport),
        "charset": charset,
        "html_language": language,
        "robots_meta": robots_meta,
        "images_count": len(images),
        "images_missing_alt": missing_alt,
        "links": links,
        "links_count": len(links),
        "word_count": count_words(body_text),
        "headings": headings,
        "og_title": get_property(soup, "og:title"),
        "og_description": get_property(soup, "og:description"),
        "og_image": get_property(soup, "og:image"),
        "emails": emails,
        "phones": phones,
        "text_preview": body_text[:900],
    }


# ============================================================
# HTTP STATUS CHECKS
# ============================================================

def check_url_status(url):
    try:
        response = safe_get(
            url,
            timeout=8,
            max_bytes=100_000,
        )

        return {
            "url": url,
            "status": response.status_code,
            "ok": 200 <= response.status_code < 400,
            "error": "",
        }

    except Exception as exc:
        return {
            "url": url,
            "status": None,
            "ok": False,
            "error": str(exc)[:200],
        }


def check_sample_links(page_url, links):
    parsed_base = urlparse(page_url)
    base_host = (parsed_base.hostname or "").lower()

    unique = []
    seen = set()

    for link in links:
        target = link["url"]

        if target in seen:
            continue

        seen.add(target)
        unique.append(link)

        if len(unique) >= MAX_LINKS_TO_CHECK:
            break

    results = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(check_url_status, item["url"]): item
            for item in unique
        }

        for future in as_completed(futures):
            item = futures[future]

            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "url": item["url"],
                    "status": None,
                    "ok": False,
                    "error": str(exc)[:180],
                }

            result["text"] = item["text"]
            result["internal"] = (
                (urlparse(result["url"]).hostname or "").lower()
                == base_host
            )
            results.append(result)

    results.sort(key=lambda item: item["url"])
    return results


# ============================================================
# ROBOTS.TXT AND SITEMAP
# ============================================================

def origin_of(url):
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def check_robots_and_sitemap(base_url):
    origin = origin_of(base_url)
    output = {}

    for key, path in (
        ("robots_txt", "/robots.txt"),
        ("sitemap_xml", "/sitemap.xml"),
    ):
        target = origin + path

        try:
            response = safe_get(
                target,
                timeout=8,
                max_bytes=MAX_TEXT_BYTES,
            )

            output[key] = {
                "found": response.status_code == 200,
                "status": response.status_code,
                "preview": response.text[:700],
                "error": "",
            }

        except Exception as exc:
            output[key] = {
                "found": False,
                "status": None,
                "preview": "",
                "error": str(exc)[:200],
            }

    return output


def parse_sitemap_url(sitemap_url, max_urls=MAX_SITEMAP_URLS):
    """
    Parses a sitemap or sitemap index.
    Only a bounded number of URLs are returned.
    """
    collected = []
    visited = set()
    queue = [sitemap_url]
    errors = []

    while queue and len(collected) < max_urls:
        current = queue.pop(0)

        if current in visited:
            continue

        visited.add(current)

        try:
            response = safe_get(
                current,
                timeout=12,
                max_bytes=2_000_000,
            )

            root = ET.fromstring(response.content)
            root_name = root.tag.split("}")[-1].lower()

            if root_name == "sitemapindex":
                for element in root:
                    if element.tag.split("}")[-1].lower() == "sitemap":
                        loc = next(
                            (
                                child.text.strip()
                                for child in element
                                if child.tag.split("}")[-1].lower() == "loc"
                                and child.text
                            ),
                            "",
                        )
                        if loc and loc not in visited:
                            queue.append(loc)

            elif root_name == "urlset":
                for element in root:
                    if element.tag.split("}")[-1].lower() == "url":
                        loc = next(
                            (
                                child.text.strip()
                                for child in element
                                if child.tag.split("}")[-1].lower() == "loc"
                                and child.text
                            ),
                            "",
                        )
                        if loc:
                            collected.append(loc)

                            if len(collected) >= max_urls:
                                break

        except Exception as exc:
            errors.append({
                "sitemap": current,
                "error": str(exc)[:180],
            })

    return {
        "urls": collected,
        "count": len(collected),
        "sitemaps_checked": len(visited),
        "errors": errors,
        "limit": max_urls,
    }


# ============================================================
# SECURITY HEADERS
# ============================================================

def check_security_headers(headers):
    expected = {
        "strict_transport_security": "Strict-Transport-Security",
        "content_security_policy": "Content-Security-Policy",
        "x_content_type_options": "X-Content-Type-Options",
        "x_frame_options": "X-Frame-Options",
        "referrer_policy": "Referrer-Policy",
    }

    result = {}

    for key, header_name in expected.items():
        value = headers.get(header_name, "")
        result[key] = {
            "present": bool(value),
            "value": value[:300],
        }

    return result


# ============================================================
# GOOGLE PAGESPEED INSIGHTS
# ============================================================

def check_pagespeed(url, strategy="mobile"):
    endpoint = (
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    )

    params = [
        ("url", url),
        ("strategy", strategy),
        ("category", "PERFORMANCE"),
        ("category", "SEO"),
        ("category", "ACCESSIBILITY"),
        ("category", "BEST_PRACTICES"),
    ]

    if PAGESPEED_API_KEY:
        params.append(("key", PAGESPEED_API_KEY))

    try:
        response = requests.get(
            endpoint,
            params=params,
            timeout=40,
            headers={"User-Agent": USER_AGENT},
        )

        if response.status_code != 200:
            return {
                "available": False,
                "strategy": strategy,
                "http_status": response.status_code,
                "error": (
                    f"PageSpeed returned HTTP {response.status_code}. "
                    "This does not by itself mean the website is broken."
                ),
            }

        data = response.json()
        lighthouse = data.get("lighthouseResult", {})
        categories = lighthouse.get("categories", {})

        scores = {}

        for key in (
            "performance",
            "seo",
            "accessibility",
            "best-practices",
        ):
            score = categories.get(key, {}).get("score")
            scores[key] = (
                round(score * 100)
                if isinstance(score, (int, float))
                else None
            )

        audits = lighthouse.get("audits", {})
        metrics = {}

        for key in (
            "first-contentful-paint",
            "largest-contentful-paint",
            "speed-index",
            "total-blocking-time",
            "cumulative-layout-shift",
            "interactive",
        ):
            audit = audits.get(key, {})
            metrics[key] = {
                "display_value": audit.get("displayValue", ""),
                "numeric_va
