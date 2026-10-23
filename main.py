
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
from urllib.parse import urlparse, urljoin, urlunparse, urldefrag
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse


# ============================================================
# EAQ SEO AUDIT v8.1.0
# Generic website SEO auditor
# No target domain is hardcoded.
# ============================================================

APP_NAME = "EAQ SEO Audit"
APP_VERSION = "8.1.0"

DB_PATH = os.getenv("EAQ_DB_PATH", "eaq_reports.db")
REQUEST_TIMEOUT = 12
MAX_PAGE_BYTES = 2_000_000
MAX_TEXT_BYTES = 500_000
MAX_REDIRECTS = 5
MAX_LINKS_TO_CHECK = 20
MAX_SITEMAP_URLS = 500
MAX_CRAWL_PAGES = 30
MAX_WORKERS = 4

USER_AGENT = "EAQ-SEO-Audit/8.1 (+website-audit)"
PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY", "").strip()

app = FastAPI(title=APP_NAME, version=APP_VERSION)
audit_lock = threading.Lock()


# ============================================================
# DATABASE
# ============================================================

def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
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

    with db_connect() as conn:
        cur = conn.execute("""
            INSERT INTO reports(url, created_at, score, result_json)
            VALUES (?, ?, ?, ?)
        """, (
            url,
            created,
            int(result.get("score", 0)),
            json.dumps(result, ensure_ascii=False),
        ))
        conn.commit()
        return cur.lastrowid, created


def get_reports(limit=50):
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
# URL VALIDATION AND BASIC SSRF PROTECTION
# ============================================================

def is_public_ip(value):
    try:
        ip = ipaddress.ip_address(value)
        return (
            ip.is_global
            and not ip.is_multicast
            and not ip.is_unspecified
        )
    except ValueError:
        return False


def validate_public_url(url):
    try:
        parsed = urlparse((url or "").strip())

        if parsed.scheme.lower() not in ("http", "https"):
            return False, "يُسمح بروابط HTTP وHTTPS فقط."

        if not parsed.hostname:
            return False, "اسم المضيف غير موجود."

        if parsed.username or parsed.password:
            return False, "الروابط التي تحتوي بيانات دخول غير مسموحة."

        if parsed.port is not None and not (1 <= parsed.port <= 65535):
            return False, "رقم المنفذ غير صالح."

        host = parsed.hostname.rstrip(".").lower()

        if not host or "%" in host:
            return False, "اسم المضيف غير صالح."

        if host in ("localhost", "localhost.localdomain"):
            return False, "لا يُسمح بالوصول إلى localhost."

        if host.endswith(".localhost") or host.endswith(".local"):
            return False, "أسماء المضيفين المحلية غير مسموحة."

        try:
            ipaddress.ip_address(host)
            addresses = [host]
        except ValueError:
            try:
                answers = socket.getaddrinfo(
                    host,
                    parsed.port or (
                        443 if parsed.scheme.lower() == "https" else 80
                    ),
                    type=socket.SOCK_STREAM,
                )
                addresses = sorted({
                    answer[4][0] for answer in answers
                })
            except (socket.gaierror, OSError):
                return False, "تعذر حل اسم النطاق."

        if not addresses:
            return False, "لم يتم العثور على عناوين IP."

        if not all(is_public_ip(addr) for addr in addresses):
            return False, "تم حظر عنوان IP غير عام."

        normalized = urlunparse((
            parsed.scheme.lower(),
            parsed.netloc,
            parsed.path or "/",
            parsed.params,
            parsed.query,
            "",
        ))

        return True, normalized

    except Exception:
        return False, "عنوان URL غير صالح."


def safe_get(url, timeout=REQUEST_TIMEOUT, max_bytes=MAX_PAGE_BYTES):
    """
    Bounded HTTP GET with manual redirect validation.
    This is defense in depth, not a substitute for network isolation.
    DNS rebinding cannot be fully prevented by validation alone.
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
                    raise ValueError("تحويل HTTP بلا عنوان وجهة.")

                current = urljoin(checked, location)
                continue

            body = bytearray()

            for chunk in response.iter_content(chunk_size=16384):
                if not chunk:
                    continue

                body.extend(chunk)

                if len(body) > max_bytes:
                    raise ValueError("حجم الاستجابة تجاوز الحد المسموح.")

            response._content = bytes(body)
            response._content_consumed = True

            # Store the validated final URL explicitly.
            response.url = checked

            return response

    raise ValueError("تجاوز عدد التحويلات الحد المسموح.")


def normalize_space(value):
    return re.sub(r"\s+", " ", value or "").strip()


def same_host(url_a, url_b):
    a = urlparse(url_a)
    b = urlparse(url_b)

    return (
        (a.hostname or "").lower().rstrip(".")
        == (b.hostname or "").lower().rstrip(".")
    )


def origin_of(url):
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def get_meta(soup, name):
    tag = soup.find(
        "meta",
        attrs={"name": re.compile("^" + re.escape(name) + "$", re.I)},
    )
    return normalize_space(tag.get("content", "")) if tag else ""


def get_property(soup, name):
    tag = soup.find(
        "meta",
        attrs={"property": re.compile("^" + re.escape(name) + "$", re.I)},
    )
    return normalize_space(tag.get("content", "")) if tag else ""


def get_canonical(soup, base_url):
    for tag in soup.find_all("link", href=True):
        rel = tag.get("rel", [])
        if isinstance(rel, str):
            rel = rel.split()

        if any(str(value).lower() == "canonical" for value in rel):
            return urljoin(base_url, tag["href"].strip())

    return ""


def count_words(text):
    return len(re.findall(r"\b[\w'-]+\b", text or "", re.UNICODE))


def token_list(value):
    return {
        token.strip().lower()
        for token in re.split(r"[\s,]+", value or "")
        if token.strip()
    }


# ============================================================
# PAGE EXTRACTION
# ============================================================

def extract_page_data(url, response):
    content_type = response.headers.get("Content-Type", "")
    html_content = response.text

    recognizable = (
        "<html" in html_content[:3000].lower()
        or "<!doctype html" in html_content[:3000].lower()
    )

    if "html" not in content_type.lower() and not recognizable:
        raise ValueError("العنوان لم يُرجع صفحة HTML معروفة.")

    soup = BeautifulSoup(html_content, "html.parser")

    title = (
        normalize_space(soup.title.get_text(" ", strip=True))
        if soup.title else ""
    )

    description = get_meta(soup, "description")
    robots_meta = get_meta(soup, "robots")
    googlebot_meta = get_meta(soup, "googlebot")

    robots_tokens = token_list(robots_meta)
    googlebot_tokens = token_list(googlebot_meta)
    noindex = (
        "noindex" in robots_tokens
        or "noindex" in googlebot_tokens
    )

    h1 = [
        normalize_space(tag.get_text(" ", strip=True))
        for tag in soup.find_all("h1")
    ]

    images = soup.find_all("img")

    missing_alt = sum(
        1 for image in images
        if image.get("alt") is None
        or not normalize_space(image.get("alt", ""))
    )

    # Decorative images can legitimately use alt="".
    # Count missing attributes separately from empty attributes.
    missing_alt_attribute = sum(
        1 for image in images if image.get("alt") is None
    )

    empty_alt = sum(
        1 for image in images
        if image.get("alt") is not None
        and not normalize_space(image.get("alt", ""))
    )

    links = []

    for anchor in soup.find_all("a", href=True):
        href = normalize_space(anchor.get("href", ""))

        if not href or href.startswith(
            ("#", "mailto:", "tel:", "javascript:", "data:")
        ):
            continue

        absolute, _fragment = urldefrag(urljoin(url, href))
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

    text_soup = BeautifulSoup(html_content, "html.parser")

    for element in text_soup([
        "script", "style", "noscript", "svg",
        "template", "nav", "footer",
    ]):
        element.decompose()

    body_text = normalize_space(text_soup.get_text(" ", strip=True))

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
        match = re.search(
            r"charset\s*=\s*([^;\s]+)",
            content_type,
            flags=re.I,
        )
        charset = match.group(1) if match else ""

    language = (
        normalize_space(soup.html.get("lang", ""))
        if soup.html else ""
    )

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
        "url": response.url,
        "status_code": response.status_code,
        "content_type": content_type,
        "title": title,
        "title_length": len(title),
        "description": description,
        "description_length": len(description),
        "h1": h1,
        "h1_count": len(h1),
        "canonical": get_canonical(soup, response.url),
        "viewport": bool(viewport),
        "charset": charset,
        "html_language": language,
        "robots_meta": robots_meta,
        "googlebot_meta": googlebot_meta,
        "noindex_meta": noindex,
        "images_count": len(images),
        "images_missing_alt": missing_alt,
        "images_missing_alt_attribute": missing_alt_attribute,
        "images_empty_alt": empty_alt,
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
        "headers": dict(response.headers),
    }


# ============================================================
# CHECK RESULT HELPERS
# ============================================================

def make_check(name, status, details, weight=1):
    return {
        "name": name,
        "status": status,  # pass / fail / unknown / info
        "details": details,
        "weight": weight,
    }


def calculate_score(checks):
    """
    Only pass/fail checks contribute to the score denominator.
    Unknown checks are excluded so rate limits do not create false failures.
    Informational checks are not scored.
    """
    scored = [
        item for item in checks
        if item["status"] in ("pass", "fail")
        and item.get("weight", 0) > 0
    ]

    possible = sum(item["weight"] for item in scored)
    earned = sum(
        item["weight"] for item in scored
        if item["status"] == "pass"
    )

    if possible == 0:
        score = None
    else:
        score = round((earned / possible) * 100)

    return {
        "score": score,
        "points_earned": earned,
        "points_possible": possible,
        "checks_passed": sum(
            item["status"] == "pass" for item in checks
        ),
        "checks_failed": sum(
            item["status"] == "fail" for item in checks
        ),
        "checks_unknown": sum(
            item["status"] == "unknown" for item in checks
        ),
        "checks_informational": sum(
            item["status"] == "info" for item in checks
        ),
    }


def build_seo_checks(page, robots, sitemap, headers):
    checks = []

    def add(name, condition, details, weight=1):
        checks.append(make_check(
            name,
            "pass" if condition else "fail",
            details,
            weight,
        ))

    status_code = page.get("status_code")
    add(
        "استجابة HTTP",
        status_code == 200,
        f"HTTP {status_code}",
        2,
    )

    content_type = page.get("content_type", "")
    add(
        "نوع محتوى HTML",
        "html" in content_type.lower(),
        content_type or "لم يتم تحديد نوع المحتوى",
        1,
    )

    add(
        "عنوان الصفحة",
        bool(page.get("title")),
        page.get("title") or "عنوان الصفحة مفقود",
        2,
    )

    title_length = page.get("title_length", 0)
    add(
        "طول العنوان",
        30 <= title_length <= 60,
        f"{title_length} حرفًا؛ 30–60 نطاق إرشادي وليس قاعدة إلزامية.",
        1,
    )

    description = page.get("description", "")
    add(
        "الوصف التعريفي",
        bool(description),
        description or "الوصف التعريفي مفقود",
        2,
    )

    desc_length = page.get("description_length", 0)
    add(
        "طول الوصف التعريفي",
        70 <= desc_length <= 160,
        f"{desc_length} حرفًا؛ 70–160 نطاق إرشادي.",
        1,
    )

    add(
        "عنوان H1",
        page.get("h1_count", 0) >= 1,
        f"عدد عناوين H1: {page.get('h1_count', 0)}",
        2,
    )

    checks.append(make_check(
        "عدد عناوين H1",
        "info",
        f"تم العثور على {page.get('h1_count', 0)} عنوان H1. "
        "وجود عدة عناوين H1 ليس خطأ SEO تلقائيًا.",
        0,
    ))

    canonical = page.get("canonical", "")
    canonical_valid = False

    if canonical:
        valid, _ = validate_public_url(canonical)
        canonical_valid = valid

    add(
        "عنوان URL الرسمي Canonical",
        canonical_valid,
        canonical or "لم يتم العثور على Canonical صالح",
        2,
    )

    if canonical:
        checks.append(make_check(
            "اتساق Canonical مع الصفحة",
            "pass" if canonical.rstrip("/") ==
            page.get("url", "").rstrip("/") else "unknown",
            "تمت مقارنة Canonical بعنوان الصفحة النهائي. "
            "قد يكون Canonical مختلفًا مشروعًا عند وجود صفحات مكررة.",
            0,
        ))

    add(
        "بيانات تعريف منطقة العرض",
        page.get("viewport", False),
        "تم العثور على viewport" if page.get("viewport")
        else "علامة viewport مفقودة",
        1,
    )

    add(
        "ترميز الأحرف",
        bool(page.get("charset")),
        page.get("charset") or "لم يتم تحديد ترميز الأحرف",
        1,
    )

    add(
        "لغة HTML",
        bool(page.get("html_language")),
        page.get("html_language") or "خاصية lang مفقودة في عنصر HTML",
        1,
    )

    add(
        "تعليمات noindex",
        not page.get("noindex_meta", False),
        "لم يتم العثور على noindex في علامات robots المفحوصة"
        if not page.get("noindex_meta", False)
        else "تم العثور على noindex؛ تأكد أن منع الفهرسة مقصود.",
        1,
    )

    image_count = page.get("images_count", 0)
    missing_alt = page.get("images_missing_alt", 0)

    if image_count == 0:
        checks.append(make_check(
            "النص البديل للصور",
            "unknown",
            "لم يتم العثور على صور في HTML الذي جرى تحليله.",
            1,
        ))
    else:
        add(
            "النص البديل للصور",
            missing_alt == 0,
            f"الصور: {image_count}؛ الصور التي ينقصها alt: {missing_alt}؛ "
            f"alt فارغ: {page.get('images_empty_alt', 0)}.",
            2,
        )

    # HTTPS is only a meaningful check for HTTPS pages.
    is_https = urlparse(page.get("url", "")).scheme.lower() == "https"
    add(
        "HTTPS",
        is_https,
        page.get("url", ""),
        2,
    )

    for key, label in (
        ("robots_txt", "robots.txt"),
        ("sitemap_xml", "Sitemap XML"),
    ):
        item = robots.get(key, {})

        if item.get("status") == 429 or item.get("status") == 403:
            checks.append(make_check(
                label,
                "unknown",
                f"HTTP {item.get('status')}: تعذر التحقق بسبب تقييد الوصول.",
                1,
            ))
        elif item.get("status") is None:
            checks.append(make_check(
                label,
                "unknown",
                item.get("error") or "تعذر التحقق.",
                1,
            ))
        elif key == "robots_txt":
            # A 404 robots.txt is not necessarily a technical SEO error.
            checks.append(make_check(
                label,
                "pass" if item.get("status") in (200, 404) else "fail",
                f"HTTP {item.get('status')}; 404 يعني أن الملف غير موجود.",
                1,
            ))
        else:
            add(
                label,
                item.get("status") == 200 and item.get("xml_valid", False),
                f"HTTP {item.get('status')}; "
                f"XML صالح: {bool(item.get('xml_valid', False))}",
                2,
            )

    security_headers = check_security_headers(headers)

    # Security headers are useful diagnostics but not direct ranking factors.
    checks.append(make_check(
        "Security Headers",
        "info",
        json.dumps(security_headers, 
