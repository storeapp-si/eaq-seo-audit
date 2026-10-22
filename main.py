import os
import re
import json
import time
import socket
import sqlite3
import ipaddress
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin, urlencode
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import escape

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

APP_NAME = "EAQ SEO Audit"
APP_VERSION = "4.0.0"

MAX_URL_LENGTH = 2048
MAX_HTML_BYTES = 2_000_000
TIMEOUT = 12
MAX_LINKS = 10

DB_PATH = os.getenv("DATABASE_PATH", "/tmp/eaq_audit.sqlite3")
PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY", "").strip()
SIMILARWEB_API_KEY = os.getenv("SIMILARWEB_API_KEY", "").strip()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eaq")

app = FastAPI(title=APP_NAME, version=APP_VERSION, docs_url=None, redoc_url=None)

LANGUAGES = {
    "ar": "العربية",
    "en": "English",
    "fr": "Français",
    "es": "Español",
    "de": "Deutsch",
    "zh": "中文",
}

T = {
    "ar": {
        "tagline": "حلّل. أتمت. حسّن.",
        "heading": "افحص الحالة التقنية لموقعك",
        "intro": "تحليل SEO والسرعة والروابط وعمر النطاق والتاريخ المتاح.",
        "url": "رابط الموقع",
        "audit": "تحليل الموقع",
        "new": "تحليل جديد",
        "report": "تقرير الفحص",
        "score": "نتيجة SEO",
        "passed": "الفحوصات المستوفاة",
        "issues": "نقاط تحتاج إلى مراجعة",
        "details": "النتائج التفصيلية",
        "priorities": "أولويات التحسين",
        "good": "جيد مبدئيًا",
        "warning": "يُنصح بالمراجعة",
        "title": "عنوان الصفحة",
        "description": "الوصف التعريفي",
        "canonical": "الرابط الأساسي Canonical",
        "headings": "بنية العناوين",
        "images": "النص البديل للصور",
        "https": "اتصال HTTPS",
        "viewport": "إعداد عرض الهاتف",
        "html_lang": "لغة HTML",
        "schema": "البيانات المنظمة",
        "social": "بيانات المشاركة الاجتماعية",
        "robots_meta": "توجيهات Robots",
        "status": "حالة الموقع",
        "speed": "سرعة الموقع - Google PageSpeed",
        "sitemap": "ملف Robots وخريطة الموقع",
        "links": "فحص عينة من الروابط",
        "business": "فحص النشاط التجاري المحلي (اختياري)",
        "business_enable": "تفعيل فحص النشاط التجاري المحلي",
        "map_enable": "تحديد موقع النشاط على الخريطة (اختياري)",
        "business_name": "اسم النشاط التجاري (اختياري)",
        "address": "عنوان النشاط التجاري (اختياري)",
        "latitude": "خط العرض",
        "longitude": "خط الطول",
        "map_help": "انقر على الخريطة لتحديد الموقع أو أدخل الإحداثيات يدويًا.",
        "local_result": "نتائج الفحص المحلي",
        "no_business": "لم تُكتشف بيانات واضحة لنشاط تجاري محلي.",
        "no_location": "لم يُحدد موقع جغرافي؛ هذا لا يمنع فحص SEO العام.",
        "domain_age": "عمر النطاق",
        "created": "تاريخ إنشاء النطاق",
        "unknown": "غير متاح",
        "years": "سنة",
        "history": "التاريخ السنوي للموقع",
        "archive": "عدد لقطات Wayback Machine السنوية",
        "visits": "الزيارات الشهرية المقدّرة",
        "visitors": "الزوار الفريدون المقدّرون",
        "no_visits": "لا تتوفر بيانات زيارات موثوقة لهذا النطاق.",
        "no_archive": "لم تتوفر بيانات أرشيف تاريخية.",
        "source": "المصدر",
        "updated": "تاريخ جلب البيانات",
        "speed_none": "بيانات PageSpeed غير متاحة.",
        "not_rank": "هذه نتيجة قائمة فحوصات وليست ترتيبًا من Google.",
        "print": "طباعة / حفظ PDF",
        "saved": "يُحفظ التقرير تلقائيًا.",
        "report_id": "رقم التقرير",
        "history_reports": "التقارير المحفوظة",
        "no_reports": "لا توجد تقارير محفوظة.",
        "view": "عرض",
        "delete": "حذف",
        "date": "التاريخ",
        "website": "الموقع",
        "actions": "الإجراءات",
        "security": "الأمان والخصوصية",
        "privacy": "يمكن فحص روابط المواقع العامة فقط.",
        "invalid": "أدخل رابط HTTP أو HTTPS عامًا وصحيحًا.",
        "error": "تعذر فحص الموقع.",
        "footer": "إرشادات تقنية لا تضمن ترتيبًا معينًا في نتائج البحث.",
        "sample": "هذه عينة محدودة من الروابط؛ قد تمنع بعض المواقع الفحص الآلي.",
        "not_checked": "لم يتم الفحص",
        "no_robots": "لم يُعثر على robots.txt.",
        "no_sitemap": "لم تُكتشف خريطة موقع.",
        "local_note": "الفحص المحلي اختياري. لا تدخل بيانات موقع لا تملك حق استخدامها.",
    },
    "en": {
        "tagline": "Analyze. Automate. Improve.",
        "heading": "Understand your website's SEO health",
        "intro": "Check technical SEO, speed, links, domain age and available history.",
        "url": "Website URL", "audit": "Analyze website", "new": "New audit",
        "report": "Audit report", "score": "SEO score",
        "passed": "Passed checks", "issues": "Items to review",
        "details": "Detailed findings", "priorities": "Recommended priorities",
        "good": "Looks good", "warning": "Review recommended",
        "title": "Page title", "description": "Meta description",
        "canonical": "Canonical URL", "headings": "Heading structure",
        "images": "Image alt text", "https": "HTTPS",
        "viewport": "Mobile viewport", "html_lang": "HTML language",
        "schema": "Structured data", "social": "Social metadata",
        "robots_meta": "Robots directives", "status": "Website status",
        "speed": "Google PageSpeed Insights", "sitemap": "Robots and sitemap",
        "links": "Sampled links", "business": "Local business audit (optional)",
        "business_enable": "Enable local business audit",
        "map_enable": "Set business location on map (optional)",
        "business_name": "Business name (optional)",
        "address": "Business address (optional)", "latitude": "Latitude",
        "longitude": "Longitude",
        "map_help": "Click the map or enter coordinates manually.",
        "local_result": "Local audit results",
        "no_business": "No clear local business details detected.",
        "no_location": "No location provided; general SEO analysis is unaffected.",
        "domain_age": "Domain age", "created": "Domain creation date",
        "unknown": "Unavailable", "years": "years",
        "history": "Website history by year",
        "archive": "Annual Wayback Machine snapshots",
        "visits": "Estimated monthly visits",
        "visitors": "Estimated unique visitors",
        "no_visits": "No reliable traffic data is available for this domain.",
        "no_archive": "No historical archive data was found.",
        "source": "Source", "updated": "Data retrieved",
        "speed_none": "PageSpeed data is unavailable.",
        "not_rank": "This is a checklist score, not a Google ranking.",
        "print": "Print / Save PDF", "saved": "Reports are saved automatically.",
        "report_id": "Report ID", "history_reports": "Saved reports",
        "no_reports": "No saved reports.", "view": "View", "delete": "Delete",
        "date": "Date", "website": "Website", "actions": "Actions",
        "security": "Security and privacy",
        "privacy": "Only public website URLs can be analyzed.",
        "invalid": "Enter a valid public HTTP or HTTPS URL.",
        "error": "Unable to analyze this website.",
        "footer": "Technical guidance does not guarantee search rankings.",
        "sample": "Only a limited sample is checked; some servers block automated requests.",
        "not_checked": "Not checked", "no_robots": "robots.txt was not found.",
        "no_sitemap": "No sitemap was detected.",
        "local_note": "Local audit is optional. Only submit business details you are authorized to use.",
    },
}

# Missing French, Spanish, German and Chinese keys fall back to English.
for _lang in ("fr", "es", "de", "zh"):
    T[_lang] = dict(T["en"])


def tr(lang, key):
    lang = lang if lang in T else "en"
    return T[lang].get(key, T["en"].get(key, key))


def esc(value):
    return escape(str(value if value is not None else ""), quote=True)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------- Database ----------------

def get_db():
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    try:
        db = sqlite3.connect(DB_PATH, timeout=10)
    except sqlite3.OperationalError:
        db = sqlite3.connect("/tmp/eaq_audit.sqlite3", timeout=10)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                title TEXT,
                score INTEGER NOT NULL,
                report_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        db.commit()


init_db()


# ---------------- Security ----------------

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://unpkg.com; "
            "img-src 'self' data: https: blob:; "
            "connect-src 'self' https://unpkg.com; "
            "font-src 'self' data: https://unpkg.com; "
            "form-action 'self'; base-uri 'self'; frame-ancestors 'self'"
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)


def validate_public_url(raw):
    raw = (raw or "").strip()
    if not raw or len(raw) > MAX_URL_LENGTH:
        raise ValueError("Invalid URL")
    if "://" not in raw:
        raw = "https://" + raw

    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Invalid URL scheme")
    if parsed.username or parsed.password:
        raise ValueError("Credentials are not allowed")

    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(
        (".localhost", ".local", ".internal", ".test")
    ):
        raise ValueError("Private hostname")

    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            raise ValueError("Non-public IP")
    except ValueError as exc:
        if str(exc) == "Non-public IP":
            raise
        try:
            addresses = socket.getaddrinfo(host, None)
        except socket.gaierror:
            raise ValueError("Hostname could not be resolved")
        for item in addresses:
            addr = ipaddress.ip_address(item[4][0])
            if not addr.is_global:
                raise ValueError("Hostname resolves to a non-public IP")

    if parsed.port and parsed.port not in (80, 443):
        raise ValueError("Unsupported port")

    return raw


def safe_get(raw_url, max_redirects=4, stream=False):
    current = validate_public_url(raw_url)
    headers = {
        "User-Agent": "EAQ-SEO-Audit/4.0 (+public website technical checker)",
        "Accept": "text/html,application/xhtml+xml,application/xml,text/plain,*/*",
    }

    for _ in range(max_redirects + 1):
        current = validate_public_url(current)
        response = requests.get(
            current,
            headers=headers,
            timeout=TIMEOUT,
            allow_redirects=False,
            stream=stream,
        )
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            response.close()
            if not location:
                return None
            current = urljoin(current, location)
            continue
        return response

    raise ValueError("Too many redirects")


def fetch_page(url):
    response = safe_get(url, stream=True)
    if response is None:
        raise ValueError("No response")

    content_type = response.headers.get("Content-Type", "").lower()
    if "html" not in content_type and "xhtml" not in content_type:
        response.close()
        raise ValueError("The URL did not return HTML")

    chunks = []
    total = 0
    for chunk in response.iter_content(65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_HTML_BYTES:
            response.close()
            raise ValueError("HTML document is too large")
        chunks.append(chunk)

    final_url = response.url
    status_code = response.status_code
    response.close()

    raw = b"".join(chunks)
    soup = BeautifulSoup(raw, "html.parser")
    return final_url, status_code, soup


# ---------------- SEO checks ----------------

def meta_content(soup, name=None, prop=None):
    for tag in soup.find_all("meta"):
        if name and (tag.get("name") or "").lower() == name.lower():
            return (tag.get("content") or "").strip()
        if prop and (tag.get("property") or "").lower() == prop.lower():
            return (tag.get("content") or "").strip()
    return ""


def analyze_page(url):
    final_url, status, soup = fetch_page(url)
    checks = []

    def add(label, passed, detail):
        checks.append({
            "label": label,
            "passed": bool(passed),
            "detail": str(detail),
        })

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    description = meta_content(soup, name="description")
    canonical_tag = soup.find("link", rel=lambda x: x and "canonical" in x)
    canonical = canonical_tag.get("href", "").strip() if canonical_tag else ""
    h1s = soup.find_all("h1")
    imgs = soup.find_all("img")
    missing_alt = sum(1 for img in imgs if img.get("alt") is None)
    viewport = meta_content(soup, name="viewport")
    html_lang = (soup.html.get("lang", "") if soup.html else "").strip()
    robots = meta_content(soup, name="robots")
    jsonld = soup.find_all("script", type="application/ld+json")
    social = bool(
        meta_content(soup, prop="og:title")
        or meta_content(soup, prop="og:description")
        or meta_content(soup, name="twitter:card")
    )

    # Absence of a robots meta tag is not itself an SEO error.
    robots_ok = not robots or not re.search(r"\bnoindex\b", robots, re.I)

    add("Page title", bool(title), title or "Missing page title")
    add("Meta description", bool(description), description or "Missing meta description")
    add("Canonical URL", bool(canonical), canonical or "No canonical link detected")
    add("Heading structure", len(h1s) == 1, f"{len(h1s)} H1 heading(s)")
    add("Image alt text", missing_alt == 0, f"{missing_alt} image(s) without alt out of {len(imgs)}")
    add("HTTPS", final_url.lower().startswith("https://"), final_url)
    add("Mobile viewport", bool(viewport), "Viewport metadata present" if viewport else "Viewport metadata missing")
    add("HTML language", bool(html_lang), html_lang or "HTML lang attribute missing")
    add("Structured data", bool(jsonld), f"{len(jsonld)} JSON-LD block(s)")
    add("Social metadata", social, "Social metadata present" if social else "Social metadata missing")
    add("Robots directives", robots_ok, robots or "No restrictive robots meta directive detected")
    add("Website status", 200 <= status < 400, f"HTTP {status}")

    business_types = (
        "LocalBusiness", "Organization", "ProfessionalService", "Store",
        "MedicalBusiness", "Corporation", "HomeAndConstructionBusiness",
    )
    business_detected = False
    for block in jsonld:
        try:
            data = json.loads(block.string or block.get_text())
            stack = data if isinstance(data, list) else [data]
            while stack:
                obj = stack.pop()
                if not isinstance(obj, dict):
                    continue
                typ = obj.get("@type", [])
                if isinstance(typ, str):
                    typ = [typ]
                if any(any(bt.lower() in str(x).lower() for bt in business_types) for x in typ):
                    business_detected = True
                graph = obj.get("@graph")
                if isinstance(graph, list):
                    stack.extend(graph)
        except Exception:
            continue

    # General SEO score excludes local business information.
    passed = sum(1 for c in checks if c["passed"])
    score = round(100 * passed / max(1, len(checks)))

    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(final_url, a["href"].strip())
        p = urlparse(href)
        if p.scheme not in ("http", "https") or not p.hostname:
            continue
        if href in seen:
            continue
        seen.add(href)
        links.append(href)
        if len(links) >= MAX_LINKS:
            break

    return {
        "url": url,
        "final_url": final_url,
        "http_status": status,
        "title": title,
        "description": description,
        "canonical": canonical,
        "score": score,
        "passed": passed,
        "total_checks": len(checks),
        "checks": checks,
        "links": links,
        "business_detected": business_detected,
        "html_lang": html_lang,
    }


def check_one_link(url):
    try:
        r = safe_get(url, max_redirects=3)
        if r is None:
            return {"url": url, "status": 0, "result": "No response"}
        status = r.status_code
        r.close()
        return {"url": url, "status": status, "result": "OK" if status < 400 else "Review"}
    except Exception as exc:
        return {"url": url, "status": 0, "result": type(exc).__name__}


def check_robots_sitemap(site_url):
    p = urlparse(site_url)
    base = f"{p.scheme}://{p.netloc}"
    robots_url = base + "/robots.txt"
    sitemap_url = base + "/sitemap.xml"

    out = {"robots": None, "sitemap": None}
    for key, target in (("robots", robots_url), ("sitemap", sitemap_url)):
        try:
            r = safe_get(target, max_redirects=3)
            if r:
                out[key] = {"url": target, "status": r.status_code}
                r.close()
        except Exception:
            out[key] = {"url": target, "status": 0}
    return out


def pagespeed_data(url):
    params = {"url": url, "category": ["PERFORMANCE", "SEO"]}
    if PAGESPEED_API_KEY:
        params["key"] = PAGESPEED_API_KEY

    try:
        endpoint = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
        r = requests.get(endpoint, params=params, timeout=25)
        if r.status_code != 200:
            return None
        data = r.json()
        cats = data.get("lighthouseResult", {}).get("categories", {})
        result = {}
        for key in ("performance", "seo"):
            item = cats.get(key)
            if item and item.get("score") is not None:
                result[key] = round(item["score"] * 100)
        return result or None
    except Exception:
        return None


# ---------------- Domain age and history ----------------

def get_domain_age(url):
    host = (urlparse(url).hostname or "").lower().strip(".")
    if not host:
        return {"domain": "", "created": None, "age_days": None, "age_years": None, "source": "RDAP"}

    # IP addresses do not have domain registration dates.
    try:
        ipaddress.ip_address(host)
        return {"domain": host, "created": None, "age_days": None, "age_years": None, "source": "RDAP"}
    except ValueError:
        pass

    try:
        r = requests.get(
            "https://rdap.org/domain/" + host,
            headers={"User-Agent": "EAQ-SEO-Audit/4.0"},
            timeout=10,
        )
        if r.status_code != 200:
            return {"domain": host, "created": None, "age_days": None, "age_years": None, "source": "RDAP"}
        data = r.json()
        created = None
        for event in data.get("events", []):
            if event.get("eventAction", "").lower() == "registration":
                created = event.get("eventDate")
                break
        if not created:
            return {"domain": host, "created": None, "age_days": None, "age_years": None, "source": "RDAP"}
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        days = max(0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).days)
        return {
            "domain": host,
            "created": dt.date().isoformat(),
            "age_days": days,
            "age_years": round(days / 365.2425, 1),
            "source": "RDAP",
        }
    except Exception:
        return {"domain": host, "created": None, "age_days": None, "age_years": None, "source": "RDAP"}


def get_wayback_history(url):
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return []
    try:
        params = {
            "url": host + "/*",
            "output": "json",
            "fl": "timestamp",
            "filter": "statuscode:200",
            "collapse": "timestamp:4",
        }
        r = requests.get(
            "https://web.archive.org/cdx/search/cdx",
            params=params,
            timeout=18,
            headers={"User-Agent": "EAQ-SEO-Audit/4.0"},
        )
        if r.status_code != 200:
            return []
        rows = r.json()
        years = {}
        for row in rows[1:]:
            if not row or not row[0] or len(row[0]) < 4:
                continue
            year = row[0][:4]
            if year.isdigit():
                years[year] = years.get(year, 0) + 1
        return [{"year": y, "count": years[y]} for y in sorted(years)]
    except Exception:
        return []


def get_similarweb_data(url):
    if not SIMILARWEB_API_KEY:
        return None

    host = (urlparse(url).hostname or "").lower()
    endpoint = f"https://api.similarweb.com/v1/website/{host}/total-traffic-and-engagement/visits"
    params = {
        "api_key": SIMILARWEB_API_KEY,
        "start_date": "2025-01",
        "end_date": datetime.now().strftime("%Y-%m"),
        "granularity": "monthly",
        "main_domain_only": "true",
        "format": "json",
    }

    try:
        r = requests.get(endpoint, params=params, timeout=20)
        if r.status_code != 200:
            logger.info("Similarweb API unavailable: %s", r.status_code)
            return None
        data = r.json()
        items = data.get("visits", [])
        rows = []
        for item in items:
            date = item.get("date")
            value = item.get("visits")
            if date is not None and isinstance(value, (int, float)):
                rows.append({"month": str(date), "visits": int(value)})
        return {"source": "Similarweb API", "monthly": rows} if rows else None
    except Exception as exc:
        logger.info("Similarweb unavailable: %s", exc)
        return None


# ---------------- Local business checks ----------------

def validate_coordinates(latitude, longitude):
    if latitude in (None, "") or longitude in (None, ""):
        return None
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {"latitude": lat, "longitude": lon}


def local_business_report(page, enabled, map_enabled, name, address, latitude, longitude):
    if not enabled:
        return None

    coords = validate_coordinates(latitude, longitude) if map_enabled else None
    issues = []
    if not name.strip():
        issues.append("Business name was not provided.")
    if not address.strip():
        issues.append("Business address was not provided.")
    if map_enabled and not coords:
        issues.append("A valid map location was not provided.")

    return {
        "enabled": True,
        "name": name.strip(),
        "address": address.strip(),
        "coordinates": coords,
        "structured_business_detected": page["business_detected"],
        "issues": issues,
    }


# ---------------- HTML helpers and charts ----------------

def layout(lang, body, title=APP_NAME, extra_head=""):
    rtl = "rtl" if lang == "ar" else "ltr"
    language_options = "".join(
        f'<option value="{k}" {"selected" if k == lang else ""}>{esc(v)}</option>'
        for k, v in LANGUAGES.items()
    )
    return f"""<!doctype html>
<html lang="{esc(lang)}" dir="{rtl}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} - {APP_NAME}</title>
<style>
:root{{--bg:#f4f7fb;--card:#fff;--text:#172337;--muted:#627188;--line:#dce4ef;--blue:#2563eb;--green:#15803d;--red:#b91c1c}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:Arial,sans-serif;line-height:1.65}}
header{{background:#10213d;color:#fff;padding:20px 16px}}
.wrap{{max-width:1120px;margin:auto;padding:18px}}
.brand{{font-size:23px;font-weight:800}}
.tagline{{opacity:.85}}
nav{{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap}}
select,input,button{{font:inherit}}
select,input[type=text],input[type=url],input[type=number]{{padding:10px;border:1px solid #bdc9da;border-radius:9px;width:100%;background:white;color:#172337}}
label{{font-weight:600;display:block;margin:9px 0 5px}}
button,.btn{{display:inline-block;background:var(--blue);color:#fff;border:0;border-radius:9px;padding:10px 15px;text-decoration:none;cursor:pointer;font-weight:700}}
button.secondary,.btn.secondary{{background:#e7edf6;color:#172337}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:15px;padding:18px;margin:14px 0;box-shadow:0 3px 14px #14294a08}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:13px}}
.kpi{{font-size:27px;font-weight:800}}
.muted{{color:var(--muted);font-size:14px}}
.pill{{display:inline-block;padding:3px 9px;border-radius:20px;background:#e8f7ee;color:var(--green);font-size:13px}}
.warn{{background:#fff3d8;color:#8a5100}}
.fail{{background:#fee2e2;color:var(--red)}}
table{{width:100%;border-collapse:collapse;overflow-wrap:anywhere}}
th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:start;vertical-align:top}}
th{{background:#f0f4fa}}
.chart{{width:100%;max-width:100%;height:auto;display:block}}
.scorebox{{display:flex;gap:24px;align-items:center;flex-wrap:wrap}}
.donut{{width:160px;max-width:45vw}}
.map{{height:340px;border-radius:12px;overflow:hidden;border:1px solid var(--line);margin-top:12px}}
footer{{text-align:center;color:var(--muted);padding:25px}}
.actions{{display:flex;gap:8px;flex-wrap:wrap}}
details{{margin-top:12px}}
a{{color:#1d4ed8}}
@media(max-width:600px){{.wrap{{padding:10px}}.card{{padding:13px}}th,td{{padding:7px;font-size:13px}}}}
@media print{{body{{background:#fff}}header,.no-print,footer{{display:none!important}}.wrap{{max-width:none;padding:0}}.card{{box-shadow:none;break-inside:avoid}}a{{color:#111;text-decoration:none}}}}
</style>
{extra_head}
</head>
<body>
<header><div class="wrap"><nav>
<div><div class="brand">{APP_NAME}</div><div class="tagline">{esc(tr(lang, "tagline"))}</div></div>
<form method="get" action="/" class="no-print" style="display:flex;gap:8px;align-items:center">
<label for="lang" style="margin:0">{esc("اللغة" if lang=="ar" else "Language")}</label>
<select id="lang" name="lang" onchange="this.form.submit()" style="width:auto">{language_options}</select>
</form>
</nav></div></header>
<main class="wrap">{body}</main>
<footer>{esc(tr(lang, "footer"))}</footer>
</body></html>"""


def donut_svg(score, passed, total, size=160):
    score = max(0, min(100, int(score)))
    circumference = 2 * 3.141592653589793 * 43
    dash = circumference * score / 100
    color = "#16a34a" if score >= 80 else ("#d97706" if score >= 55 else "#dc2626")
    return f"""
<svg class="donut" viewBox="0 0 120 120" role="img" aria-label="SEO score {score}">
<circle cx="60" cy="60" r="43" fill="none" stroke="#e5eaf2" stroke-width="11"/>
<circle cx="60" cy="60" r="43" fill="none" stroke="{color}" stroke-width="11"
stroke-linecap="round" stroke-dasharray="{dash:.2f} {circumference:.2f}"
transform="rotate(-90 60 60)"/>
<text x="60" y="56" text-anchor="middle" font-size="25" font-weight="800" fill="currentColor">{score}</text>
<text x="60" y="74" text-anchor="middle" font-size="10" fill="currentColor">/ 100</text>
</svg>"""


def line_chart_svg(items, xkey, ykey, title, color="#2563eb"):
    if not items:
        return '<p class="muted">No chart data available.</p>'

    values = []
    for item in items:
        try:
            values.append(float(item[ykey]))
        except (ValueError, TypeError, KeyError):
            values.append(0.0)

    width, height = 760, 270
    left, right, top, bottom = 58, 20, 28, 55
    plot_w, plot_h = width-left-right, height-top-bottom
    max_v = max(values) if values else 1
    if max_v <= 0:
        max_v = 1
    min_v = min(0, min(values))
    span = max_v - min_v
    if span <= 0:
        span = 1

    points = []
    labels = []
    for i, (item, value) in enumerate(zip(items, values)):
        x = left + (plot_w * i / max(1, len(items)-1))
        y = top + plot_h - ((value-min_v)/span)*plot_h
        points.append((x, y))
        label = str(item.get(xkey, ""))[:10]
        labels.append(f'<text x="{x:.1f}" y="{height-25}" font-size="11" text-anchor="middle" fill="currentColor">{esc(label)}</text>')

    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    circles = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}"><title>{esc(items[i].get(xkey,""))}: {values[i]:,.0f}</title></circle>'
        for i, (x, y) in enumerate(points)
    )
    grid = []
    for i in range(5):
        y = top + plot_h * i / 4
        value = max_v - (max_v-min_v)*i/4
        grid.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#dfe6f0"/>'
            f'<text x="{left-8}" y="{y+4:.1f}" font-size="10" text-anchor="end" fill="currentColor">{value:,.0f}</text>'
        )

    return f"""
<div class="card">
<h3>{esc(title)}</h3>
<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">
{''.join(grid)}
<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>
{circles}
{''.join(labels)}
</svg>
</div>"""


def pie_svg(passed, failed):
    total = max(1, passed + failed)
    pct = 100 * passed / total
    c = 2 * 3.141592653589793 * 42
    dash = c * pct / 100
    return f"""
<svg class="donut" viewBox="0 0 120 120" role="img" aria-label="Passed and failed checks">
<circle cx="60" cy="60" r="42" fill="none" stroke="#fee2e2" stroke-width="14"/>
<circle cx="60" cy="60" r="42" fill="none" stroke="#16a34a" stroke-width="14"
stroke-dasharray="{dash:.2f} {c:.2f}" transform="rotate(-90 60 60)"/>
<text x="60" y="56" font-size="22" font-weight="800" text-anchor="middle" fill="currentColor">{passed}</text>
<text x="60" y="72" font-size="10" text-anchor="middle" fill="currentColor">/{total}</text>
</svg>"""


def render_table(rows, columns):
    if not rows:
        return '<p class="muted">No data available.</p>'
    head = "".join(f"<th>{esc(label)}</th>" for _, label in columns)
    body = []
    for row in rows:
        cells = "".join(f"<td>{esc(row.get(key, ''))}</td>" for key, _ in columns)
        body.append(f"<tr>{cells}</tr>")
    return f"<div style='overflow-x:auto'><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"


# ---------------- Pages ----------------

@app.get("/", response_class=HTMLResponse)
def home(lang: str = "ar"):
    lang = lang if lang in LANGUAGES else "ar"
    body = f"""
<section class="card">
<h1>{esc(tr(lang, "heading"))}</h1>
<p>{esc(tr(lang, "intro"))}</p>
<form method="post" action="/audit">
<input type="hidden" name="lang" value="{esc(lang)}">
<label for="url">{esc(tr(lang, "url"))}</label>
<input id="url" name="url" type="url" placeholder="https://example.com" required maxlength="{MAX_URL_LENGTH}">
<p class="muted">{esc(tr(lang, "privacy"))}</p>

<div class="card">
<label style="display:flex;gap:10px;align-items:center">
<input type="checkbox" name="local_enabled" value="yes" id="local_enabled" style="width:auto">
<span>{esc(tr(lang, "business_enable"))}</span>
</label>
<p class="muted">{esc(tr(lang, "local_note"))}</p>

<div id="local_fields" hidden>
<label for="business_name">{esc(tr(lang, "business_name"))}</label>
<input id="business_name" name="business_name" type="text" maxlength="200">

<label for="address">{esc(tr(lang, "address"))}</label>
<input id="address" name="address" type="text" maxlength="300">

<label style="display:flex;gap:10px;align-items:center">
<input type="checkbox" name="map_enabled" value="yes" id="map_enabled" style="width:auto">
<span>{esc(tr(lang, "map_enable"))}</span>
</label>

<div id="map_fields" hidden>
<div class="grid">
<div><label for="latitude">{esc(tr(lang, "latitude"))}</label>
<input id="latitude" name="latitude" type="number" step="any" min="-90" max="90" placeholder="24.7136"></div>
<div><label for="longitude">{esc(tr(lang, "longitude"))}</label>
<input id="longitude" name="longitude" type="number" step="any" min="-180" max="180" placeholder="46.6753"></div>
</div>
<p class="muted">{esc(tr(lang, "map_help"))}</p>
<div id="map" class="map"></div>
</div>
</div>
</div>

<button type="submit">{esc(tr(lang, "audit"))}</button>
</form>
</section>

<section class="card">
<h2>{esc(tr(lang, "history_reports"))}</h2>
{render_history(lang)}
</section>

<script>
const localCheck = document.getElementById('local_enabled');
const mapCheck = document.getElementById('map_enabled');
const localFields = document.getElementById('local_fields');
const mapFields = document.getElementById('map_fields');
let mapInstance = null;
let mapMarker = null;

function syncLocal() {{
  localFields.hidden = !localCheck.checked;
  if (!localCheck.checked) {{
    mapCheck.checked = false;
    mapFields.hidden = true;
  }}
}}
function syncMap() {{
  mapFields.hidden = !mapCheck.checked || !localCheck.checked;
  if (!mapFields.hidden) {{
    loadMap();
  }}
}}
localCheck.addEventListener('change', syncLocal);
localCheck.addEventListener('change', syncMap);
mapCheck.addEventListener('change', syncMap);

function loadMap() {{
  if (mapInstance) {{
    setTimeout(() => mapInstance.invalidateSize(), 150);
    return;
  }}
  if (!window.L) {{
    const css = document.createElement('link');
    css.rel = 'stylesheet';
    css.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
    document.head.appendChild(css);
    const script = document.createElement('script');
    script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    script.onload = initMap;
    document.head.appendChild(script);
  }} else {{
    initMap();
  }}
}}
function initMap() {{
  if (mapInstance || !window.L) return;
  mapInstance = L.map('map').setView([24.7136, 46.6753], 5);
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }}).addTo(mapInstance);
  mapInstance.on('click', function(e) {{
    document.getElementById('latitude').value = e.latlng.lat.toFixed(6);
    document.getElementById('longitude').value = e.latlng.lng.toFixed(6);
    if (mapMarker) mapMarker.setLatLng(e.latlng);
    else mapMarker = L.marker(e.latlng).addTo(mapInstance);
  }});
  setTimeout(() => mapInstance.invalidateSize(), 200);
}}
</script>
"""
    return HTMLResponse(layout(lang, body, APP_NAME))


def render_history(lang):
    with get_db() as db:
        rows = db.execute(
            "SELECT id,url,title,score,created_at FROM reports ORDER BY id DESC LIMIT 20"
        ).fetchall()

    if not rows:
        return f"<p>{esc(tr(lang, 'no_reports'))}</p>"

    result = ["<div style='overflow-x:auto'><table><thead><tr>"]
    for key in ("date", "website", "score", "actions"):
        result.append(f"<th>{esc(tr(lang, key))}</th>")
    result.append("</tr></thead><tbody>")

    for row in rows:
        result.append(
            "<tr>"
            f"<td>{esc(row['created_at'][:19].replace('T',' '))}</td>"
            f"<td>{esc(row['url'])}</td>"
            f"<td>{int(row['score'])}/100</td>"
            "<td class='actions'>"
            f"<a class='btn secondary' href='/report/{int(row['id'])}?lang={esc(lang)}'>{esc(tr(lang,'view'))}</a>"
            f"<form method='post' action='/delete/{int(row['id'])}' onsubmit=\"return confirm('Delete report?')\">"
            f"<input type='hidden' name='lang' value='{esc(lang)}'>"
            f"<button class='secondary' type='submit'>{esc(tr(lang,'delete'))}</button>"
            "</form></td></tr>"
        )
    result.append("</tbody></table></div>")
    return "".join(result)


@app.post("/audit", response_class=HTMLResponse)
def audit(
    url: str = Form(...),
    lang: str = Form("ar"),
    local_enabled: str = Form(""),
    map_enabled: str = Form(""),
    business_name: str = Form(""),
    address: str = Form(""),
    latitude: str = Form(""),
    longitude: str = Form(""),
):
    lang = lang if lang in LANGUAGES else "ar"

    try:
        clean_url = validate_public_url(url)
        page = analyze_page(clean_url)
    except Exception as exc:
        logger.info("Audit failed: %s", exc)
        body = f"""
<div class="card">
<h1>{esc(tr(lang, "error"))}</h1>
<p>{esc(tr(lang, "invalid"))}</p>
<p class="muted">{esc(tr(lang, "error"))}</p>
<a class="btn" href="/?lang={esc(lang)}">{esc(tr(lang, "new"))}</a>
</div>"""
        return HTMLResponse(layout(lang, body), status_code=400)

    link_results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(check_one_link, link) for link in page["links"]]
        for future in as_completed(futures):
            try:
                link_results.append(future.result())
            except Exception:
                pass
    link_results.sort(key=lambda x: x["url"])

    robots = check_robots_sitemap(page["final_url"])
    speed = pagespeed_data(page["final_url"])
    domain = get_domain_age(page["final_url"])
    archive = get_wayback_history(page["final_url"])
    traffic = get_similarweb_data(page["final_url"])

    local = local_business_report(
        page=page,
        enabled=(local_enabled == "yes"),
        map_enabled=(map_enabled == "yes"),
        name=business_name,
        address=address,
        latitude=latitude,
        longitude=longitude,
    )

    report = {
        "url": clean_url,
        "final_url": page["final_url"],
        "http_status": page["http_status"],
        "title": page["title"],
        "description": page["description"],
        "canonical": page["canonical"],
        "score": page["score"],
        "passed": page["passed"],
        "total_checks": page["total_checks"],
        "checks": page["checks"],
        "links": link_results,
        "robots_sitemap": robots,
        "pagespeed": speed,
        "domain": domain,
        "archive": archive,
        "traffic": traffic,
        "local": local,
        "created_at": now_iso(),
    }

    with get_db() as db:
        cursor = db.execute(
            "INSERT INTO reports(url,title,score,report_json,created_at) VALUES(?,?,?,?,?)",
            (
                clean_url,
                page["title"],
                page["score"],
                json.dumps(report, ensure_ascii=False),
                now_iso(),
            ),
        )
        report_id = cursor.lastrowid
        db.commit()

    return RedirectResponse(
        url=f"/report/{report_id}?lang={lang}",
        status_code=303,
    )


@app.get("/report/{report_id}", response_class=HTMLResponse)
def view_report(report_id: int, lang: str = "ar"):
    lang = lang if lang in LANGUAGES else "ar"
    with get_db() as db:
        row = db.execute(
            "SELECT report_json FROM reports WHERE id=?",
            (report_id,),
        ).fetchone()

    if not row:
        return HTMLResponse(
            layout(lang, f"<div class='card'><h1>Report not found</h1><a href='/?lang={esc(lang)}'>{esc(tr(lang,'new'))}</a></div>"),
            status_code=404,
        )

    report = json.loads(row["report_json"])
    score = int(report.get("score", 0))
    passed = int(report.get("passed", 0))
    total = int(report.get("total_checks", 0))
    failed = max(0, total - passed)
    domain = report.get("domain") or {}
    archive = report.get("archive") or []
    traffic = report.get("traffic")
    speed = report.get("pagespeed")
    local = report.get("local")

    checks_html = []
    for check in report.get("checks", []):
        status = "pill" if check["passed"] else "pill fail"
        symbol = "✓" if check["passed"] else "!"
        checks_html.append(
            f"<tr><td><span class='{status}'>{symbol}</span></td>"
            f"<td><strong>{esc(check['label'])}</strong></td>"
            f"<td>{esc(check['detail'])}</td></tr>"
        )

    robots = report.get("robots_sitemap") or {}
    robots_rows = []
    for key in ("robots", "sitemap"):
        item = robots.get(key) or {}
        robots_rows.append({
            "type": key,
            "url": item.get("url", ""),
            "status": item.get("status", "Unknown"),
            "result": "Found" if item.get("status", 0) == 200 else "Review",
        })

    link_html = render_table(
        report.get("links", []),
        [("url", "URL"), ("status", "HTTP"), ("result", "Result")],
    )

    domain_age = domain.get("age_years")
    age_text = (
        f"{domain_age} {esc(tr(lang,'years'))}"
        if domain_age is not None
        else esc(tr(lang, "unknown"))
    )

    domain_card = f"""
<div class="card">
<h2>{esc(tr(lang,'domain_age'))}</h2>
<div class="grid">
<div><div class="muted">{esc(tr(lang,'domain_age'))}</div><div class="kpi">{age_text}</div></div>
<div><div class="muted">{esc(tr(lang,'created'))}</div><div class="kpi" style="font-size:19px">{esc(domain.get('created') or tr(lang,'unknown'))}</div></div>
</div>
<p class="muted">{esc(tr(lang,'source'))}: RDAP. Domain registration age may differ from the age of the website itself.</p>
</div>"""

    archive_chart = ""
    if archive:
        archive_chart = line_chart_svg(
            archive, "year", "count", tr(lang, "archive"), "#7c3aed"
        )
        archive_table = render_table(
            archive, [("year", "Year"), ("count", "Archived snapshots")]
        )
    else:
        archive_chart = f"<div class='card'><h2>{esc(tr(lang,'history'))}</h2><p>{esc(tr(lang,'no_archive'))}</p></div>"
        archive_table = ""

    traffic_section = ""
    if traffic and traffic.get("monthly"):
        traffic_section = line_chart_svg(
            traffic["monthly"], "month", "visits", tr(lang, "visits"), "#0891b2"
        )
        traffic_section += f"<p class='muted'>{esc(tr(lang,'source'))}: {esc(traffic.get('source','External provider'))}. These are estimates, not verified analytics.</p>"
        traffic_section += render_table(
            traffic["monthly"],
            [("month", "Month"), ("visits", "Estimated visits")],
        )
    else:
        traffic_section = (
            f"<div class='card'><h2>{esc(tr(lang,'visits'))}</h2>"
            f"<p>{esc(tr(lang,'no_visits'))}</p>"
            "<p class='muted'>To enable traffic estimates, configure SIMILARWEB_API_KEY in the server environment. Availability depends on the provider and subscription.</p></div>"
        )

    speed_section = ""
    if speed:
        speed_rows = [{"metric": k.title(), "score": v} for k, v in speed.items()]
        speed_section = (
            f"<div class='card'><h2>{esc(tr(lang,'speed'))}</h2>"
            + render_table(speed_rows, [("metric", "Metric"), ("score", "Score / 100")])
            + "</div>"
        )
        speed_chart_items = [{"metric": k.title(), "score": v} for k, v in speed.items()]
        speed_section += line_chart_svg(speed_chart_items, "metric", "score", tr(lang, "speed"), "#0f766e")
    else:
        speed_section = f"<div class='card'><h2>{esc(tr(lang,'speed'))}</h2><p>{esc(tr(lang,'speed_none'))}</p></div>"

    local_section = ""
    if local:
        coords = local.get("coordinates")
        coord_text = (
            f"{coords['latitude']}, {coords['longitude']}"
            if coords else tr(lang, "no_location")
        )
        map_html = ""
        if coords:
            lat = coords["latitude"]
            lon = coords["longitude"]
            map_html = f"""
<div class="card">
<h3>{esc(tr(lang,'business'))}</h3>
<p><strong>{esc(local.get('name') or tr(lang,'unknown'))}</strong></p>
<p>{esc(local.get('address') or tr(lang,'unknown'))}</p>
<p>{esc(coord_text)}</p>
<p><a href="https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=14/{lat}/{lon}" target="_blank" rel="noopener noreferrer">Open location in OpenStreetMap</a></p>
</div>"""
        else:
            map_html = f"<div class='card'><h3>{esc(tr(lang,'business'))}</h3><p>{esc(local.get('name') or tr(lang,'unknown'))}</p><p>{esc(local.get('address') or tr(lang,'unknown'))}</p><p>{esc(tr(lang,'no_location'))}</p></div>"

        local_issues = "".join(f"<li>{esc(x)}</li>" for x in local.get("issues", []))
        local_section = f"""
<div class="card">
<h2>{esc(tr(lang,'local_result'))}</h2>
<p>{esc(tr(lang,'business'))}: {esc(local.get('name') or tr(lang,'unknown'))}</p>
<p>{esc(tr(lang,'address'))}: {esc(local.get('address') or tr(lang,'unknown'))}</p>
<p>Structured local business data: {"Detected" if local.get('structured_business_detected') else esc(tr(lang,'no_business'))}</p>
<ul>{local_issues}</ul>
</div>{map_html}"""

    score_cards = f"""
<div class="card">
<div class="scorebox">
{donut_svg(score, passed, total)}
<div>
<h1>{esc(tr(lang,'report'))}</h1>
<div class="kpi">{score}/100</div>
<p>{esc(tr(lang,'not_rank'))}</p>
<p><span class="pill">{passed} {esc(tr(lang,'passed'))}</span>
<span class="pill warn">{failed} {esc(tr(lang,'issues'))}</span></p>
<p><a href="{esc(report.get('final_url',''))}" target="_blank" rel="noopener noreferrer">{esc(report.get('final_url',''))}</a></p>
<p class="muted">{esc(tr(lang,'report_id'))}: {report_id} · {esc(report.get('created_at','')[:19])}</p>
</div>
</div>
<hr style="border:0;border-top:1px solid #dce4ef;margin:18px 0">
<div class="grid">
<div><h3>{esc(tr(lang,'score'))}</h3>{donut_svg(score, passed, total)}</div>
<div><h3>Check distribution</h3>{pie_svg(passed, failed)}</div>
</div>
</div>"""

    body = f"""
<div class="actions no-print">
<a class="btn secondary" href="/?lang={esc(lang)}">{esc(tr(lang,'new'))}</a>
<button onclick="window.print()">{esc(tr(lang,'print'))}</button>
</div>
{score_cards}
{domain_card}
{archive_chart}
{archive_table}
{traffic_section}
{speed_section}

<div class="card">
<h2>{esc(tr(lang,'sitemap'))}</h2>
{render_table(robots_rows, [('type','Type'),('url','URL'),('status','HTTP'),('result','Result')])}
</div>

<div class="card">
<h2>{esc(tr(lang,'links'))}</h2>
<p class="muted">{esc(tr(lang,'sample'))}</p>
{link_html}
</div>

<div class="card">
<h2>{esc(tr(lang,'details'))}</h2>
{pie_svg(passed, failed)}
<div style="overflow-x:auto"><table><thead><tr><th></th><th>Check</th><th>Finding</th></tr></thead>
<tbody>{''.join(checks_html)}</tbody></table></div>
</div>

{local_section}

<div class="card">
<h2>{esc(tr(lang,'security'))}</h2>
<p>{esc(tr(lang,'privacy'))}</p>
<p class="muted">{esc(tr(lang,'saved'))}</p>
</div>
"""
    return HTMLResponse(layout(lang, body, f"{APP_NAME} Report #{report_id}"))


@app.post("/delete/{report_id}")
def delete_report(report_id: int, lang: str = Form("ar")):
    lang = lang if lang in LANGUAGES else "ar"
    with get_db() as db:
        db.execute("DELETE FROM reports WHERE id=?", (report_id,))
        db.commit()
    return RedirectResponse(url=f"/?lang={lang}", status_code=303)


@app.get("/health")
def health():
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION}
