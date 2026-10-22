import os
import re
import json
import time
import socket
import sqlite3
import ipaddress
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin, quote
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

APP_NAME = "EAQ SEO Audit"
APP_VERSION = "2.0.0"
MAX_URL_LENGTH = 2048
MAX_HTML_BYTES = 2_000_000
REQUEST_TIMEOUT = 12
MAX_REDIRECTS = 5
MAX_LINKS_TO_CHECK = 10

DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    "/var/data/eaq_audit.sqlite3"
)

PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY", "").strip()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eaq")

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    docs_url=None,
    redoc_url=None
)


# ============================================================
# LANGUAGES
# ============================================================

LANGUAGES = {
    "en": "English",
    "ar": "العربية",
    "fr": "Français",
    "es": "Español",
    "de": "Deutsch",
    "zh": "中文",
}

TRANSLATIONS = {
    "en": {
        "language": "Language",
        "tagline": "Analyze. Automate. Improve.",
        "heading": "Understand your website's SEO health",
        "intro": "Analyze technical SEO, performance, sitemaps and links.",
        "url": "Website URL",
        "placeholder": "https://example.com",
        "audit": "Analyze website",
        "results": "Audit report",
        "overall": "Checklist score",
        "passed": "Passed checks",
        "issues": "Items to improve",
        "details": "Detailed findings",
        "priorities": "Recommended priorities",
        "history": "Saved reports",
        "no_history": "No saved reports yet.",
        "date": "Date",
        "website": "Website",
        "score": "Score",
        "actions": "Actions",
        "view": "View",
        "delete": "Delete",
        "back": "New audit",
        "print": "Print / Save PDF",
        "title": "Page title",
        "description": "Meta description",
        "canonical": "Canonical URL",
        "headings": "Heading structure",
        "images": "Image alt text",
        "https": "HTTPS",
        "viewport": "Mobile viewport",
        "lang": "HTML language",
        "schema": "Structured data",
        "social": "Social metadata",
        "robots": "Robots meta directive",
        "business": "Business information",
        "good": "Looks good",
        "warning": "Review recommended",
        "speed": "Google PageSpeed Insights",
        "sitemap": "Robots and sitemap",
        "link_check": "Sampled links",
        "security": "Security and privacy",
        "privacy": "Only public website URLs can be analyzed.",
        "invalid": "Enter a valid public HTTP or HTTPS website URL.",
        "error": "Unable to analyze this website.",
        "error_detail": "Check the URL. The website may block automated requests.",
        "footer": "Technical SEO guidance, not a guarantee of search ranking.",
        "report_id": "Report ID",
        "no_business": "No business details detected.",
        "no_speed": "PageSpeed data is unavailable.",
        "no_field": "No Google field data is available for this URL or origin.",
        "no_sitemap": "No sitemap was detected.",
        "no_robots": "robots.txt could not be verified.",
        "not_rank": "This is a checklist score, not a Google ranking score.",
        "pdf_tip": "Choose Save as PDF in the print dialog.",
        "saved": "Reports are saved automatically.",
    },
    "ar": {
        "language": "اللغة",
        "tagline": "حلّل. أتمت. حسّن.",
        "heading": "افهم الحالة التقنية لموقعك",
        "intro": "فحص SEO التقني والسرعة وخريطة الموقع والروابط.",
        "url": "رابط الموقع",
        "placeholder": "https://example.com",
        "audit": "تحليل الموقع",
        "results": "تقرير الفحص",
        "overall": "نتيجة قائمة الفحوصات",
        "passed": "الفحوصات المستوفاة",
        "issues": "نقاط تحتاج إلى تحسين",
        "details": "النتائج التفصيلية",
        "priorities": "أولويات التحسين",
        "history": "التقارير المحفوظة",
        "no_history": "لا توجد تقارير محفوظة.",
        "date": "التاريخ",
        "website": "الموقع",
        "score": "النتيجة",
        "actions": "الإجراءات",
        "view": "عرض",
        "delete": "حذف",
        "back": "تحليل جديد",
        "print": "طباعة / حفظ PDF",
        "title": "عنوان الصفحة",
        "description": "الوصف التعريفي",
        "canonical": "الرابط الأساسي Canonical",
        "headings": "بنية العناوين",
        "images": "النص البديل للصور",
        "https": "اتصال HTTPS",
        "viewport": "إعداد عرض الهاتف",
        "lang": "لغة HTML",
        "schema": "البيانات المنظمة",
        "social": "بيانات المشاركة الاجتماعية",
        "robots": "توجيهات Robots",
        "business": "معلومات النشاط التجاري",
        "good": "جيد مبدئيًا",
        "warning": "يُنصح بالمراجعة",
        "speed": "سرعة الموقع - Google PageSpeed",
        "sitemap": "ملف Robots وخريطة الموقع",
        "link_check": "فحص عينة من الروابط",
        "security": "الأمان والخصوصية",
        "privacy": "يمكن فحص روابط المواقع العامة فقط.",
        "invalid": "أدخل رابط HTTP أو HTTPS عامًا وصحيحًا.",
        "error": "تعذر فحص الموقع.",
        "error_detail": "تحقق من الرابط؛ قد يمنع الموقع الطلبات الآلية.",
        "footer": "إرشادات SEO تقنية ولا تضمن ترتيبًا معينًا في البحث.",
        "report_id": "رقم التقرير",
        "no_business": "لم تُكتشف معلومات واضحة عن النشاط التجاري.",
        "no_speed": "بيانات PageSpeed غير متاحة.",
        "no_field": "لا تتوفر بيانات ميدانية من Google لهذا الرابط أو النطاق.",
        "no_sitemap": "لم تُكتشف خريطة موقع.",
        "no_robots": "تعذر التحقق من robots.txt.",
        "not_rank": "هذه نتيجة قائمة فحوصات وليست ترتيبًا من Google.",
        "pdf_tip": "اختر حفظ بصيغة PDF من نافذة الطباعة.",
        "saved": "تُحفظ التقارير تلقائيًا.",
    },
    "fr": {
        "language": "Langue",
        "tagline": "Analyser. Automatiser. Améliorer.",
        "heading": "Comprenez la santé SEO de votre site",
        "intro": "Analyse technique SEO, vitesse, sitemap et liens.",
        "url": "URL du site",
        "placeholder": "https://example.com",
        "audit": "Analyser le site",
        "results": "Rapport d'audit",
        "overall": "Score de contrôle",
        "passed": "Contrôles réussis",
        "issues": "Points à améliorer",
        "details": "Résultats détaillés",
        "priorities": "Priorités recommandées",
        "history": "Rapports enregistrés",
        "no_history": "Aucun rapport enregistré.",
        "date": "Date",
        "website": "Site",
        "score": "Score",
        "actions": "Actions",
        "view": "Voir",
        "delete": "Supprimer",
        "back": "Nouvel audit",
        "print": "Imprimer / Enregistrer PDF",
        "title": "Titre de la page",
        "description": "Méta-description",
        "canonical": "URL canonique",
        "headings": "Structure des titres",
        "images": "Textes alternatifs",
        "https": "HTTPS",
        "viewport": "Affichage mobile",
        "lang": "Langue HTML",
        "schema": "Données structurées",
        "social": "Métadonnées sociales",
        "robots": "Directive robots",
        "business": "Informations commerciales",
        "good": "Semble correct",
        "warning": "Vérification recommandée",
        "speed": "Google PageSpeed Insights",
        "sitemap": "Robots et sitemap",
        "link_check": "Liens échantillonnés",
        "security": "Sécurité et confidentialité",
        "privacy": "Seules les URL publiques peuvent être analysées.",
        "invalid": "Saisissez une URL publique HTTP ou HTTPS valide.",
        "error": "Impossible d'analyser le site.",
        "error_detail": "Vérifiez l'URL. Le site peut bloquer les requêtes automatiques.",
        "footer": "Conseils SEO techniques, sans garantie de classement.",
        "report_id": "Rapport",
        "no_business": "Aucune information commerciale détectée.",
        "no_speed": "Données PageSpeed indisponibles.",
        "no_field": "Aucune donnée terrain Google disponible.",
        "no_sitemap": "Aucun sitemap détecté.",
        "no_robots": "robots.txt non vérifié.",
        "not_rank": "Ce score n'est pas un classement Google.",
        "pdf_tip": "Choisissez Enregistrer en PDF dans la fenêtre d'impression.",
        "saved": "Les rapports sont enregistrés automatiquement.",
    },
    "es": {
        "language": "Idioma",
        "tagline": "Analiza. Automatiza. Mejora.",
        "heading": "Comprende la salud SEO de tu sitio",
        "intro": "SEO técnico, velocidad, sitemap y enlaces.",
        "url": "URL del sitio",
        "placeholder": "https://example.com",
        "audit": "Analizar sitio",
        "results": "Informe de auditoría",
        "overall": "Puntuación de comprobación",
        "passed": "Comprobaciones correctas",
        "issues": "Aspectos por mejorar",
        "details": "Resultados detallados",
        "priorities": "Prioridades recomendadas",
        "history": "Informes guardados",
        "no_history": "Todavía no hay informes.",
        "date": "Fecha",
        "website": "Sitio",
        "score": "Puntuación",
        "actions": "Acciones",
        "view": "Ver",
        "delete": "Eliminar",
        "back": "Nueva auditoría",
        "print": "Imprimir / Guardar PDF",
        "title": "Título de página",
        "description": "Meta descripción",
        "canonical": "URL canónica",
        "headings": "Estructura de encabezados",
        "images": "Texto alternativo",
        "https": "HTTPS",
        "viewport": "Vista móvil",
        "lang": "Idioma HTML",
        "schema": "Datos estructurados",
        "social": "Metadatos sociales",
        "robots": "Directiva robots",
        "business": "Información comercial",
        "good": "Parece correcto",
        "warning": "Se recomienda revisar",
        "speed": "Google PageSpeed Insights",
        "sitemap": "Robots y sitemap",
        "link_check": "Enlaces muestreados",
        "security": "Seguridad y privacidad",
        "privacy": "Solo se pueden analizar URL públicas.",
        "invalid": "Introduce una URL pública HTTP o HTTPS válida.",
        "error": "No se pudo analizar el sitio.",
        "error_detail": "Comprueba la URL; el sitio puede bloquear solicitudes automáticas.",
        "footer": "Consejos técnicos SEO, sin garantía de posicionamiento.",
        "report_id": "Informe",
        "no_business": "No se detectó información comercial.",
        "no_speed": "Datos de PageSpeed no disponibles.",
        "no_field": "No hay datos de campo de Google disponibles.",
        "no_sitemap": "No se detectó sitemap.",
        "no_robots": "No se pudo verificar robots.txt.",
        "not_rank": "Esta puntuación no es un ranking de Google.",
        "pdf_tip": "Elige Guardar como PDF en el diálogo de impresión.",
        "saved": "Los informes se guardan automáticamente.",
    },
    "de": {
        "language": "Sprache",
        "tagline": "Analysieren. Automatisieren. Verbessern.",
        "heading": "Verstehen Sie den SEO-Zustand Ihrer Website",
        "intro": "Technisches SEO, Geschwindigkeit, Sitemap und Links prüfen.",
        "url": "Website-URL",
        "placeholder": "https://example.com",
        "audit": "Website analysieren",
        "results": "Auditbericht",
        "overall": "Prüfpunktzahl",
        "passed": "Bestandene Prüfungen",
        "issues": "Verbesserungspunkte",
        "details": "Detaillierte Ergebnisse",
        "priorities": "Empfohlene Prioritäten",
        "history": "Gespeicherte Berichte",
        "no_history": "Noch keine Berichte.",
        "date": "Datum",
        "website": "Website",
        "score": "Punktzahl",
        "actions": "Aktionen",
        "view": "Anzeigen",
        "delete": "Löschen",
        "back": "Neues Audit",
        "print": "Drucken / PDF speichern",
        "title": "Seitentitel",
        "description": "Meta-Beschreibung",
        "canonical": "Kanonische URL",
        "headings": "Überschriftenstruktur",
        "images": "Alternativtexte",
        "https": "HTTPS",
        "viewport": "Mobile Ansicht",
        "lang": "HTML-Sprache",
        "schema": "Strukturierte Daten",
        "social": "Social-Metadaten",
        "robots": "Robots-Direktive",
        "business": "Unternehmensinformationen",
        "good": "Sieht gut aus",
        "warning": "Überprüfung empfohlen",
        "speed": "Google PageSpeed Insights",
        "sitemap": "Robots und Sitemap",
        "link_check": "Stichprobenlinks",
        "security": "Sicherheit und Datenschutz",
        "privacy": "Nur öffentliche URLs können analysiert werden.",
        "invalid": "Geben Sie eine gültige öffentliche HTTP- oder HTTPS-URL ein.",
        "error": "Website konnte nicht analysiert werden.",
        "error_detail": "URL prüfen; die Website kann automatisierte Anfragen blockieren.",
        "footer": "Technische SEO-Hinweise, keine Ranking-Garantie.",
        "report_id": "Bericht",
        "no_business": "Keine Unternehmensdaten erkannt.",
        "no_speed": "PageSpeed-Daten nicht verfügbar.",
        "no_field": "Keine Google-Felddaten verfügbar.",
        "no_sitemap": "Keine Sitemap erkannt.",
        "no_robots": "robots.txt konnte nicht geprüft werden.",
        "not_rank": "Diese Punktzahl ist kein Google-Ranking.",
        "pdf_tip": "Im Druckdialog Als PDF speichern wählen.",
        "saved": "Berichte werden automatisch gespeichert.",
    },
    "zh": {
        "language": "语言",
        "tagline": "分析。自动化。改进。",
        "heading": "了解网站的 SEO 状况",
        "intro": "检查技术 SEO、速度、站点地图和链接。",
        "url": "网站网址",
        "placeholder": "https://example.com",
        "audit": "分析网站",
        "results": "审计报告",
        "overall": "检查得分",
        "passed": "通过的检查",
        "issues": "待改进项目",
        "details": "详细结果",
        "priorities": "建议优先事项",
        "history": "已保存报告",
        "no_history": "暂无报告。",
        "date": "日期",
        "website": "网站",
        "score": "得分",
        "actions": "操作",
        "view": "查看",
        "delete": "删除",
        "back": "新建审计",
        "print": "打印 / 保存 PDF",
        "title": "页面标题",
        "description": "元描述",
        "canonical": "规范网址",
        "headings": "标题结构",
        "images": "图片替代文本",
        "https": "HTTPS",
        "viewport": "移动视口",
        "lang": "HTML 语言",
        "schema": "结构化数据",
        "social": "社交元数据",
        "robots": "Robots 指令",
        "business": "商业信息",
        "good": "看起来正常",
        "warning": "建议检查",
        "speed": "Google PageSpeed Insights",
        "sitemap": "Robots 与站点地图",
        "link_check": "抽样链接",
        "security": "安全与隐私",
        "privacy": "只能分析公开网址。",
        "invalid": "请输入有效的公开 HTTP 或 HTTPS 网址。",
        "error": "无法分析网站。",
        "error_detail": "请检查网址；网站可能阻止自动请求。",
        "footer": "提供技术 SEO 建议，不保证搜索排名。",
        "report_id": "报告编号",
        "no_business": "未检测到商业信息。",
        "no_speed": "PageSpeed 数据不可用。",
        "no_field": "没有可用的 Google 实地数据。",
        "no_sitemap": "未检测到站点地图。",
        "no_robots": "无法验证 robots.txt。",
        "not_rank": "此分数不是 Google 排名。",
        "pdf_tip": "在打印窗口中选择保存为 PDF。",
        "saved": "报告会自动保存。",
    },
}


def tr(lang, key):
    return TRANSLATIONS.get(lang, TRANSLATIONS["en"]).get(
        key, TRANSLATIONS["en"].get(key, key)
    )


def esc(value):
    from html import escape
    return escape(str(value if value is not None else ""), quote=True)


# ============================================================
# DATABASE
# ============================================================

def database_file():
    parent = os.path.dirname(DATABASE_PATH)
    if parent:
        try:
            os.makedirs(parent, exist_ok=True)
            probe = os.path.join(parent, ".eaq_write_test")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            return DATABASE_PATH
        except OSError:
            logger.warning("Database directory unavailable; using /tmp.")
    return "/tmp/eaq_audit.sqlite3"


DB_FILE = database_file()


def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                title TEXT,
                score INTEGER NOT NULL,
                report_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()


init_db()


# ============================================================
# SECURITY HEADERS AND SAFE URL FETCHING
# ============================================================

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; "
            "connect-src 'self'; font-src 'self' data:; form-action 'self'; "
            "base-uri 'self'; frame-ancestors 'none'"
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)


def validate_public_url(raw_url):
    raw_url = (raw_url or "").strip()
    if not raw_url or len(raw_url) > MAX_URL_LENGTH:
        raise ValueError("invalid URL")

    if "://" not in raw_url:
        raw_url = "https://" + raw_url

    parsed = urlparse(raw_url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError("unsupported scheme")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("invalid host or credentials")

    host = parsed.hostname.rstrip(".").lower()

    if host == "localhost" or host.endswith(
        (".localhost", ".local", ".internal", ".test")
    ):
        raise ValueError("private hostname")

    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            raise ValueError("private IP address")
    except ValueError as exc:
        if str(exc) == "private IP address":
            raise
        try:
            records = socket.getaddrinfo(
                host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM
            )
        except socket.gaierror as err:
            raise ValueError("DNS lookup failed") from err

        addresses = {record[4][0].split("%")[0] for record in records}
        if not addresses:
            raise ValueError("DNS lookup failed")

        for address in addresses:
            ip_addr = ipaddress.ip_address(address)
            if not ip_addr.is_global:
                raise ValueError("hostname resolves to a non-public IP")

    return parsed._replace(fragment="").geturl()


def safe_request(url, method="GET", stream=False, allow_non_html=False):
    current = validate_public_url(url)
    headers = {
        "User-Agent": "EAQ-SEO-Audit/2.0",
        "Accept": "*/*"
    }

    with requests.Session() as session:
        session.trust_env = False

        for _ in range(MAX_REDIRECTS + 1):
            current = validate_public_url(current)
            response = session.request(
                method,
                current,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
                stream=stream
            )

            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise ValueError("redirect without location")
                current = urljoin(current, location)
                continue

            if not allow_non_html and response.ok:
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                    response.close()
                    raise ValueError("URL did not return HTML")

            return response, current

    raise ValueError("too many redirects")


def fetch_public_page(url):
    response, final_url = safe_request(url, "GET", stream=True)

    try:
        if response.status_code >= 400:
            raise requests.HTTPError(f"HTTP {response.status_code}")

        data = bytearray()
        for chunk in response.iter_content(16384):
            if not chunk:
                continue
            data.extend(chunk)
            if len(data) > MAX_HTML_BYTES:
                raise ValueError("page too large")

        html = bytes(data).decode(response.encoding or "utf-8", errors="replace")
        return {
            "url": final_url,
            "html": html,
            "status": response.status_code
        }
    finally:
        response.close()


def check_resource(url):
    try:
        response, final_url = safe_request(
            url, "GET", stream=True, allow_non_html=True
        )
        try:
            body = bytearray()
            for chunk in response.iter_content(8192):
                if chunk:
                    body.extend(chunk)
                    if len(body) >= 200_000:
                        break

            return {
                "url": final_url,
                "status": response.status_code,
                "ok": 200 <= response.status_code < 400,
                "text": bytes(body).decode(
                    response.encoding or "utf-8", errors="replace"
                )
            }
        finally:
            response.close()
    except Exception as exc:
        return {
            "url": url,
            "status": None,
            "ok": False,
            "text": "",
            "error": type(exc).__name__
        }


def check_link(url):
    try:
        response, final_url = safe_request(
            url, "HEAD", allow_non_html=True
        )
        status = response.status_code
        response.close()

        if status in (400, 403, 405, 429, 501):
            response, final_url = safe_request(
                url, "GET", stream=True, allow_non_html=True
            )
            status = response.status_code
            response.close()

        if 200 <= status < 400:
            state = "OK"
        elif status in (401, 403, 429):
            state = "Review"
        else:
            state = "Broken"

        return {
            "url": url,
            "final_url": final_url,
            "status": status,
            "state": state
        }
    except Exception as exc:
        return {
            "url": url,
            "final_url": "",
            "status": None,
            "state": "Unverified",
            "error": type(exc).__name__
        }


# ============================================================
# GOOGLE PAGESPEED INSIGHTS
# ============================================================

def pagespeed_check(url):
    params = {
        "url": url,
        "strategy": "mobile",
        "category": [
            "performance",
            "seo",
            "accessibility",
            "best-practices"
        ]
    }

    if PAGESPEED_API_KEY:
        params["key"] = PAGESPEED_API_KEY

    try:
        response = requests.get(
            "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
            params=params,
            timeout=35
        )

        if response.status_code != 200:
            return {
                "available": False,
                "reason": f"API HTTP {response.status_code}"
            }

        data = response.json()
        lighthouse = data.get("lighthouseResult", {})
        categories = lighthouse.get("categories", {})
        scores = {}

        for key, value in categories.items():
            if isinstance(value, dict) and isinstance(value.get("score"), (int, float)):
                scores[key] = round(value["score"] * 100)

        audits = lighthouse.get("audits", {})
        lab = {}

        for key, label in (
            ("first-contentful-paint", "FCP"),
            ("largest-contentful-paint", "LCP"),
            ("total-blocking-time", "TBT"),
            ("cumulative-layout-shift", "CLS"),
            ("speed-index", "Speed Index"),
            ("interactive", "Time to Interactive")
        ):
            item = audits.get(key, {})
            if item.get("displayValue"):
                lab[label] = item["displayValue"]

        # Real-user field data is not the same as Lighthouse lab data.
        loading = data.get("loadingExperience", {}).get("metrics", {})
        origin_loading = data.get("originLoadingExperience", {}).get("metrics", {})
        field_source = loading or origin_loading
        field = {}

        for key, label in (
            ("LARGEST_CONTENTFUL_PAINT_MS", "LCP"),
            ("CUMULATIVE_LAYOUT_SHIFT_SCORE", "CLS"),
            ("INTERACTION_TO_NEXT_PAINT", "INP"),
            ("FIRST_CONTENTFUL_PAINT_MS", "FCP")
        ):
            metric = field_source.get(key)
            if isinstance(metric, dict) and metric.get("percentile") is not None:
                field[label] = metric["percentile"]

        return {
            "available": True,
            "scores": scores,
            "lab": lab,
            "field": field,
            "field_scope": "URL" if loading else (
                "Origin" if origin_loading else "Unavailable"
            )
        }

    except Exception as exc:
        return {
            "available": False,
            "reason": type(exc).__name__
        }


# ============================================================
# ROBOTS.TXT AND SITEMAP
# ============================================================

def check_robots_sitemap(page_url):
    parsed = urlparse(page_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    robots_url = urljoin(origin + "/", "robots.txt")
    robots = check_resource(robots_url)

    sitemap_urls = []

    if robots.get("status") == 200:
        for line in robots.get("text", "").splitlines():
            match = re.match(r"\s*sitemap\s*:\s*(\S+)", line, re.I)
            if match:
                sitemap_urls.append(match.group(1).strip())

    if not sitemap_urls:
        sitemap_urls.append(urljoin(origin + "/", "sitemap.xml"))

    results = []
    seen = set()

    for sitemap_url in sitemap_urls[:3]:
        try:
            sitemap_url = validate_public_url(sitemap_url)
        except ValueError:
            continue

        if sitemap_url in seen:
            continue

        seen.add(sitemap_url)
        results.append(check_resource(sitemap_url))

    return {
        "robots": robots,
        "sitemaps": results
    }


# ============================================================
# ON-PAGE SEO AUDIT
# ============================================================

def audit_html(page_url, html, status):
    soup = BeautifulSoup(html, "html.parser")
    parsed = urlparse(page_url)

    title = soup.title.get_text(" ", strip=True) if soup.title else ""

    description_tag = soup.find(
        "meta", attrs={"name": re.compile("^description$", re.I)}
    )
    description = (
        description_tag.get("content", "").strip()
        if description_tag else ""
    )

    canonical_tag = soup.find(
        "link",
        rel=lambda value: value and (
            "canonical" in value if isinstance(value, list)
            else "canonical" in str(value).lower()
        )
    )
    canonical = canonical_tag.get("href", "") if canonical_tag else ""

    h1 = soup.find_all("h1")
    images = soup.find_all("img")
    missing_alt = sum(
        1 for image in images
        if not image.has_attr("alt") or not str(image.get("alt", "")).strip()
    )

    viewport = soup.find(
        "meta", attrs={"name": re.compile("^viewport$", re.I)}
    )
    html_lang = soup.html.get("lang", "") if soup.html else ""
    jsonld = soup.find_all(
        "script", attrs={"type": re.compile("ld\\+json", re.I)}
    )
    social = (
        soup.find("meta", property=re.compile("^(og:|twitter:)", re.I))
        or soup.find("meta", attrs={"name": re.compile("^twitter:", re.I)})
    )
    robots_meta = soup.find(
        "meta", attrs={"name": re.compile("^robots$", re.I)}
    )

    business = {}

    for script in jsonld:
        try:
            obj = json.loads(script.string or script.get_text())
            candidates = obj if isinstance(obj, list) else [obj]

            for entry in candidates:
                if not isinstance(entry, dict):
                    continue

                typ = entry.get("@type", "")
                if isinstance(typ, list):
                    typ = " ".join(typ)

                if any(word in str(typ).lower() for word in (
                    "organization", "localbusiness", "store",
                    "professionalservice"
                )):
                    address = entry.get("address", "")
                    if isinstance(address, dict):
                        address = ", ".join(
                            str(address.get(key, ""))
                            for key in (
                                "streetAddress", "addressLocality",
                                "addressRegion", "postalCode", "addressCountry"
                            )
                            if address.get(key)
                        )

                    business = {
                        "name": entry.get("name", ""),
                        "address": address,
                        "phone": entry.get("telephone", ""),
                        "email": entry.get("email", ""),
                        "website": entry.get("url", "")
                    }
                    break
        except Exception:
            continue

        if business:
            break

    if not business:
        site_name = soup.find("meta", property="og:site_name")
        if site_name:
            business = {"name": site_name.get("content", "")}

    checks = []

    def add(key, ok, details):
        checks.append({
            "key": key,
            "ok": bool(ok),
            "details": str(details)[:500]
        })

    add("title", bool(title) and len(title) <= 60, title or "No page title detected.")
    add("description", bool(description) and 50 <= len(description) <= 160,
        description or "No meta description detected.")
    add("canonical", bool(canonical), canonical or "No canonical link detected.")
    add("headings", bool(h1) and len(h1) == 1, f"{len(h1)} H1 heading(s)")
    add("images", not images or missing_alt == 0,
        f"{missing_alt} image(s) without alt out of {len(images)}")
    add("https", parsed.scheme == "https", parsed.scheme.upper())
    add("viewport", bool(viewport), "Viewport metadata present" if viewport else "Missing viewport")
    add("lang", bool(html_lang), html_lang or "Missing HTML lang attribute")
    add("schema", bool(jsonld), f"{len(jsonld)} JSON-LD block(s)")
    add("social", bool(social), "Social metadata detected" if social else "Social metadata missing")
    add("robots", bool(robots_meta), "Robots meta directive detected" if robots_meta else "No robots meta directive")
    add("business", bool(business), "Business details detected" if business else "No business details detected")
    add("status", 200 <= status < 400, f"HTTP {status}")

    internal_links = []
    external_links = []
    sample_links = []

    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").strip()

        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        absolute = urljoin(page_url, href)
        target = urlparse(absolute)

        if target.scheme not in ("http", "https") or not target.hostname:
            continue

        if target.hostname.lower() == (parsed.hostname or "").lower():
            internal_links.append(absolute)
        else:
            external_links.append(absolute)

        if absolute not in sample_links and len(sample_links) < MAX_LINKS_TO_CHECK:
            sample_links.append(absolute)

    passed = sum(1 for item in checks if item["ok"])
    score = round(100 * passed / max(1, len(checks)))

    priorities = []

    for item in checks:
        if not item["ok"]:
            priorities.append({
                "key": item["key"],
                "priority": (
                    "high" if item["key"] in ("title", "description", "https", "status")
                    else "medium"
                ),
                "details": item["details"]
            })

    return {
        "url": page_url,
        "title": title,
        "description": description,
        "score": score,
        "passed": passed,
        "total": len(checks),
        "checks": checks,
        "priorities": priorities,
        "business": business,
        "internal_links": len(internal_links),
        "external_links": len(external_links),
        "sample_links": sample_links,
        "http_status": status
    }


# ============================================================
# SAVED REPORTS
# ============================================================

def save_report(report):
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO reports(url,title,score,report_json,created_at) VALUES(?,?,?,?,?)",
            (
                report["url"],
                report.get("title", ""),
                report["score"],
                json.dumps(report, ensure_ascii=False),
                created
            )
        )
        conn.execute(
            "DELETE FROM reports WHERE id NOT IN "
            "(SELECT id FROM reports ORDER BY id DESC LIMIT 100)"
        )
        conn.commit()

        return cursor.lastrowid, created


def get_report(report_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT report_json,created_at FROM reports WHERE id=?",
            (report_id,)
        ).fetchone()

    if not row:
        return None

    try:
        report = json.loads(row["report_json"])
        report["report_id"] = report_id
        report["created_at"] = row["created_at"]
        return report
    except Exception:
        return None


def get_history():
    with get_db() as conn:
        return conn.execute(
            "SELECT id,url,title,score,created_at FROM reports ORDER BY id DESC LIMIT 100"
        ).fetchall()


# ============================================================
# HTML RENDERING
# ============================================================

def language_options(selected):
    return "".join(
        f'<option value="{code}" {"selected" if code == selected else ""}>'
        f'{esc(name)}</option>'
        for code, name in LANGUAGES.items()
    )


def page_shell(content, lang="en", title=None):
    lang = lang if lang in LANGUAGES else "en"
    direction = "rtl" if lang == "ar" else "ltr"

    return f"""<!doctype html>
<html lang="{esc(lang)}" dir="{direction}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>{esc(title or APP_NAME)}</title>
<style>
:root {{
--bg:#f5f7fb;--surface:#fff;--text:#172033;--muted:#64748b;
--border:#e4e9f1;--blue:#2563eb;--blue-dark:#1d4ed8;
--good:#166534;--good-bg:#dcfce7;--warn:#92400e;--warn-bg:#fef3c7;
--shadow:0 10px 35px rgba(20,35,70,.06)
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,"Segoe UI",Arial,sans-serif;line-height:1.6}}
a{{color:var(--blue);text-decoration:none}}a:hover{{text-decoration:underline}}
button,input,select{{font:inherit}}
.topbar{{background:#101b31;color:#fff;padding:14px 20px}}
.topbar-inner{{max-width:1120px;margin:auto;display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}}
.logo{{font-size:19px;font-weight:800}}.logo span{{color:#93c5fd}}
.tagline{{color:#cbd5e1;font-size:12px}}
.lang-form{{display:flex;gap:5px;align-items:center}}
.lang-form select{{background:#fff;color:#172033;border:0;border-radius:7px;padding:5px 8px;font-size:12px;max-width:135px}}
.wrap{{max-width:1120px;margin:28px auto;padding:0 18px 40px}}
.hero{{background:linear-gradient(135deg,#172b4d,#1d4ed8);color:#fff;border-radius:20px;padding:28px;box-shadow:var(--shadow);margin-bottom:20px}}
.hero h1{{font-size:clamp(25px,4vw,38px);line-height:1.25;margin:0 0 10px}}
.hero p{{margin:0;color:#dbeafe;overflow-wrap:anywhere}}
.panel{{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:21px;margin-bottom:18px;box-shadow:var(--shadow)}}
.panel h2{{margin:0 0 14px;font-size:20px}}
.form-row{{display:flex;gap:10px;align-items:stretch}}
.url-input{{min-width:0;flex:1;border:1px solid #cbd5e1;border-radius:11px;padding:13px 14px;background:#fff;color:var(--text)}}
.btn{{display:inline-flex;justify-content:center;align-items:center;gap:8px;border:0;border-radius:10px;padding:11px 15px;cursor:pointer;font-weight:700}}
.btn-primary{{background:var(--blue);color:#fff}}.btn-primary:hover{{background:var(--blue-dark)}}
.btn-light{{background:#edf2f9;color:#172033}}.btn-danger{{background:#fee2e2;color:#991b1b}}
.small{{font-size:13px;color:var(--muted)}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}}
.metric-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}}
.metric{{padding:18px;border:1px solid var(--border);border-radius:13px;background:#fff;color:#172033}}
.metric strong{{font-size:27px;display:block;color:#172033;font-weight:800;line-height:1.4}}
.metric span{{display:block;margin-top:5px;font-size:13px;color:#475569;line-height:1.6}}
.check-list{{display:grid;gap:10px}}
.check{{display:flex;gap:12px;align-items:flex-start;padding:13px;border:1px solid var(--border);border-radius:12px;background:#fff}}
.check-icon{{flex:none;width:25px;height:25px;border-radius:50%;display:grid;place-items:center;font-size:13px;font-weight:800}}
.check-ok .check-icon{{background:var(--good-bg);color:var(--good)}}
.check-no .check-icon{{background:var(--warn-bg);color:var(--warn)}}
.check h3{{font-size:15px;margin:0 0 3px}}.check p{{font-size:13px;color:var(--muted);margin:0;overflow-wrap:anywhere}}
.pill{{display:inline-block;border-radius:999px;padding:4px 9px;background:#eef2ff;color:#3730a3;font-size:12px;font-weight:700}}
.priority{{border-inline-start:4px solid #f59e0b;padding:12px 14px;background:#fffbeb;border-radius:8px;margin:9px 0}}
.priority.high{{border-color:#dc2626;background:#fef2f2}}
.table-wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{padding:12px;text-align:start;border-bottom:1px solid var(--border);vertical-align:top}}
th{{color:var(--muted);font-size:12px}}.business-row{{padding:9px 0;border-bottom:1px solid var(--border);overflow-wrap:anywhere}}
footer{{max-width:1120px;margin:auto;padding:0 18px 28px;color:var(--muted);font-size:12px}}
.notice{{padding:12px 14px;background:#eff6ff;border:1px solid #bfdbfe;color:#1e40af;border-radius:10px;font-size:13px;margin-top:14px}}
.error{{background:#fef2f2;border:1px solid #fecaca;color:#991b1b;padding:14px;border-radius:12px;margin:15px 0}}
@media(max-width:720px){{.wrap{{margin-top:16px;padding:0 12px 28px}}.hero{{padding:22px 18px}}.panel{{padding:16px}}.grid{{grid-template-columns:1fr}}.metric-grid{{grid-template-columns:1fr 1fr}}.form-row{{flex-direction:column}}.btn{{width:100%}}.topbar{{padding:12px}}}}
@media print{{.topbar,.no-print,footer{{display:none!important}}body{{background:#fff}}.wrap{{margin:0;padding:0}}.panel,.hero{{box-shadow:none;break-inside:avoid}}.hero{{background:#fff;color:#172033;border:1px solid #ddd}}.hero p{{color:#475569}}}}
</style>
<script src="/app.js" defer></script>
</head>
<body>
<header class="topbar"><div class="topbar-inner">
<div><div class="logo">EAQ <span>SEO Audit</span></div><div class="tagline">{esc(tr(lang,"tagline"))}</div></div>
<form method="get" action="/" class="lang-form no-print">
<label for="lang" class="small" style="color:#e2e8f0">{esc(tr(lang,"language"))}</label>
<select id="lang" name="lang" onchange="this.form.submit()">{language_options(lang)}</select>
</form>
</div></header>
<main class="wrap">{content}</main>
<footer>{esc(tr(lang,"footer"))}</footer>
</body></html>"""


def history_html(lang):
    rows = get_history()

    if not rows:
        return f'<p class="small">{esc(tr(lang,"no_history"))}</p>'

    body = []

    for row in rows:
        report_link = f'/report/{int(row["id"])}?lang={quote(lang)}'
        body.append(
            "<tr>"
            f'<td>{esc(row["created_at"][:19].replace("T"," "))}</td>'
            f'<td><a href="{report_link}">{esc(row["title"] or row["url"])}</a>'
            f'<br><span class="small">{esc(row["url"][:120])}</span></td>'
            f'<td><strong>{int(row["score"])}/100</strong></td>'
            '<td>'
            f'<a href="{report_link}">{esc(tr(lang,"view"))}</a> · '
            f'<form method="post" action="/delete/{int(row["id"])}" style="display:inline">'
            f'<input type="hidden" name="lang" value="{esc(lang)}">'
            f'<button class="btn btn-danger" style="padding:4px 8px;font-size:12px" '
            f'type="submit">{esc(tr(lang,"delete"))}</button></form>'
            "</td></tr>"
        )

    return (
        '<div class="table-wrap"><table><thead><tr>'
        f'<th>{esc(tr(lang,"date"))}</th><th>{esc(tr(lang,"website"))}</th>'
        f'<th>{esc(tr(lang,"score"))}</th><th>{esc(tr(lang,"actions"))}</th>'
        '</tr></thead><tbody>' + "".join(body) + '</tbody></table></div>'
    )


def home_html(lang="en", error_key=None):
    error_html = ""

    if error_key:
        error_html = (
            f'<div class="error"><strong>{esc(tr(lang,error_key))}</strong>'
            f'<br>{esc(tr(lang,"error_detail"))}</div>'
        )

    content = f"""
<section class="hero">
<h1>{esc(tr(lang,"heading"))}</h1>
<p>{esc(tr(lang,"intro"))}</p>
</section>
<section class="panel">
<h2>{esc(tr(lang,"audit"))}</h2>
<form method="post" action="/audit">
<input type="hidden" name="lang" value="{esc(lang)}">
<label for="url"><strong>{esc(tr(lang,"url"))}</strong></label>
<div class="form-row" style="margin-top:9px">
<input class="url-input" type="text" id="url" name="url"
maxlength="{MAX_URL_LENGTH}" placeholder="{esc(tr(lang,"placeholder"))}"
autocomplete="url" inputmode="url">
<button class="btn btn-primary" type="submit">{esc(tr(lang,"audit"))}</button>
</div>
</form>
{error_html}
<div class="notice">{esc(tr(lang,"privacy"))}</div>
</section>
<section class="panel"><h2>{esc(tr(lang,"history"))}</h2>{history_html(lang)}</section>
"""
    return page_shell(content, lang, APP_NAME)


def svg_gauge(score):
    color = "#16a34a" if score >= 80 else (
        "#f59e0b" if score >= 50 else "#dc2626"
    )

    return (
        '<svg viewBox="0 0 220 130" role="img" aria-label="SEO score">'
        '<path d="M25 110 A85 85 0 0 1 195 110" fill="none" '
        'stroke="#e2e8f0" stroke-width="16" stroke-linecap="round"/>'
        f'<path d="M25 110 A85 85 0 0 1 195 110" fill="none" '
        f'stroke="{color}" stroke-width="16" stroke-linecap="round" '
        f'pathLength="100" stroke-dasharray="{score} 100"/>'
        f'<text x="110" y="96" text-anchor="middle" font-size="30" '
        f'font-weight="800" fill="#172033">{score}</text>'
        '<text x="110" y="117" text-anchor="middle" font-size="11" '
        'fill="#64748b">/ 100</text></svg>'
    )


def render_report(report, lang="en"):
    check_html = []

    for item in report.get("checks", []):
        key = item["key"]
        label = tr(lang, key)
        state = tr(lang, "good") if item["ok"] else tr(lang, "warning")

        check_html.append(
            f'<article class="check {"check-ok" if item["ok"] else "check-no"}">'
            f'<div class="check-icon">{"✓" if item["ok"] else "!"}</div>'
            f'<div><h3>{esc(label)}</h3>'
            f'<p>{esc(state)} · {esc(item.get("details",""))}</p></div>'
            '</article>'
        )

    priority_html = []

    for item in report.get("priorities", []):
        priority_html.append(
            f'<div class="priority {esc(item["priority"])}">'
            f'<span class="pill">{esc(item["priority"].title())}</span> '
            f'<strong>{esc(tr(lang,item["key"]))}</strong>'
            f'<div class="small">{esc(item.get("details",""))}</div></div>'
        )

    pagespeed = report.get("pagespeed", {})

    if pagespeed.get("available"):
        speed_html = '<div class="metric-grid">'

        for key, value in pagespeed.get("scores", {}).items():
            speed_html += (
                f'<div class="metric"><strong>{int(value)}/100</strong>'
                f'<span>{esc(key.replace("-"," ").title())}</span></div>'
            )

        speed_html += '</div>'

        if pagespeed.get("lab"):
            speed_html += '<h3>Lighthouse lab measurements</h3><div class="table-wrap"><table>'
            for key, value in pagespeed["lab"].items():
                speed_html += f'<tr><th>{esc(key)}</th><td>{esc(value)}</td></tr>'
            speed_html += '</table></div>'

        if pagespeed.get("field"):
            speed_html += (
                '<h3>Core Web Vitals — field data '
                f'({esc(pagespeed.get("field_scope","") )})</h3>'
                '<div class="table-wrap"><table>'
            )

            for key, value in pagespeed["field"].items():
                speed_html += f'<tr><th>{esc(key)}</th><td>{esc(value)}</td></tr>'

            speed_html += '</table></div>'
        else:
            speed_html += f'<p class="small">{esc(tr(lang,"no_field"))}</p>'
    else:
        speed_html = f'<p class="small">{esc(tr(lang,"no_speed"))}</p>'

    robots_sitemap = report.get("robots_sitemap", {})
    robots = robots_sitemap.get("robots", {})

    sitemap_html = (
        f'<p><strong>robots.txt:</strong> HTTP '
        f'{esc(robots.get("status") or "Unavailable")}</p>'
    )

    sitemap_results = robots_sitemap.get("sitemaps", [])

    if sitemap_results:
        sitemap_html += '<div class="table-wrap"><table><thead><tr><th>URL</th><th>HTTP</th><th>Result</th></tr></thead><tbody>'

        for result in sitemap_results:
            state = "Found" if result.get("ok") else "Not verified"
            sitemap_html += (
                f'<tr><td style="overflow-wrap:anywhere">{esc(result.get("url",""))}</td>'
                f'<td>{esc(result.get("status") or "—")}</td><td>{state}</td></tr>'
            )

        sitemap_html += '</tbody></table></div>'
    else:
        sitemap_html += f'<p class="small">{esc(tr(lang,"no_sitemap"))}</p>'

    link_html = (
        '<p class="small">Only a limited sample is checked. '
        'Some servers block automated link checks.</p>'
    )

    link_results = report.get("link_results", [])

    if link_results:
        link_html += '<div class="table-wrap"><table><thead><tr><th>URL</th><th>HTTP</th><th>Result</th></tr></thead><tbody>'

        for item in link_results:
            link_html += (
                f'<tr><td style="overflow-wrap:anywhere">{esc(item["url"])}</td>'
                f'<td>{esc(item.get("status") or "—")}</td>'
                f'<td>{esc(item["state"])}</td></tr>'
            )

        link_html += '</tbody></table></div>'

    business = report.get("business", {})
    business_html = ""

    for key, value in business.items():
        if value:
            business_html += (
                f'<div class="business-row"><strong>{esc(key.title())}:</strong> '
                f'{esc(value)}</div>'
            )

    if not business_html:
        business_html = f'<p class="small">{esc(tr(lang,"no_business"))}</p>'

    score = int(report["score"])

    content = f"""
<section class="hero">
<div class="no-print" style="margin-bottom:12px">
<a href="/?lang={quote(lang)}" style="color:#dbeafe">← {esc(tr(lang,"back"))}</a>
</div>
<h1>{esc(tr(lang,"results"))}</h1>
<p>{esc(report["url"])}</p>
<div class="metric-grid" style="margin-top:20px">
<div class="metric"><strong>{score}/100</strong><span>{esc(tr(lang,"overall"))}</span></div>
<div class="metric"><strong>{report["passed"]}/{report["total"]}</strong><span>{esc(tr(lang,"passed"))}</span></div>
<div class="metric"><strong>{len(report["priorities"])}</strong><span>{esc(tr(lang,"issues"))}</span></div>
</div>
<p style="margin-top:14px;font-size:13px">{esc(tr(lang,"not_rank"))}</p>
</section>
<div class="no-print" style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px">
<button class="btn btn-primary" type="button" id="print-report">{esc(tr(lang,"print"))}</button>
<a class="btn btn-light" href="/?lang={quote(lang)}">{esc(tr(lang,"back"))}</a>
</div>
<section class="panel"><h2>{esc(tr(lang,"speed"))}</h2>{speed_html}</section>
<section class="panel"><h2>{esc(tr(lang,"sitemap"))}</h2>{sitemap_html}</section>
<section class="panel"><h2>{esc(tr(lang,"link_check"))}</h2>{link_html}</section>
<section class="panel"><h2>{esc(tr(lang,"priorities"))}</h2>{''.join(priority_html) if priority_html else '<p class="small">No checklist priorities detected.</p>'}</section>
<section class="panel"><h2>{esc(tr(lang,"details"))}</h2><div class="check-list">{''.join(check_html)}</div></section>
<section class="panel"><h2>{esc(tr(lang,"business"))}</h2>{business_html}</section>
<section class="panel"><h2>{esc(tr(lang,"security"))}</h2>
<p class="small">{esc(tr(lang,"privacy"))}</p>
<p class="small">{esc(tr(lang,"pdf_tip"))}</p>
<p class="small">{esc(tr(lang,"saved"))}</p>
<p class="small">{esc(tr(lang,"report_id"))}: {esc(report.get("report_id","—"))}</p>
</section>
"""

    return page_shell(
        content,
        lang,
        f'{tr(lang,"results")} — {report.get("title") or report["url"]}'
    )


# ============================================================
# ADDITIONAL AUDIT CHECKS
# ============================================================

def add_external_checks(page_url, report):
    report["robots_sitemap"] = check_robots_sitemap(page_url)

    links = report.get("sample_links", [])
    link_results = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(check_link, link) for link in links]

        for future in as_completed(futures):
            try:
                link_results.append(future.result())
            except Exception:
                continue

    link_results.sort(key=lambda item: item["url"])
    report["link_results"] = link_results
    report["pagespeed"] = pagespeed_check(page_url)

    return report


# ============================================================
# JAVASCRIPT
# ============================================================

APP_JS = r"""
"use strict";

document.addEventListener("DOMContentLoaded", function () {
    const printButton = document.getElementById("print-report");

    if (printButton) {
        printButton.addEventListener("click", function () {
            window.print();
        });
    }
});
"""


@app.get("/app.js")
def app_js():
    return Response(
        content=APP_JS,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=3600"}
    )


# ============================================================
# ROUTES
# ============================================================

@app.get("/", response_class=HTMLResponse)
def home(request: Request, lang: str = "en"):
    if lang not in LANGUAGES:
        lang = "en"

    return HTMLResponse(home_html(lang))


@app.post("/audit", response_class=HTMLResponse)
def audit(url: str = Form(""), lang: str = Form("en")):
    if lang not in LANGUAGES:
        lang = "en"

    # The input is not browser-required, but an actual URL is needed to audit a site.
    try:
        clean_url = validate_public_url(url)
    except ValueError:
        return HTMLResponse(
            home_html(lang, "invalid"),
            status_code=400
        )

    try:
        fetched = fetch_public_page(clean_url)

        report = audit_html(
            fetched["url"],
            fetched["html"],
            fetched["status"]
        )

        report = add_external_checks(fetched["url"], report)

        report_id, created_at = save_report(report)
        report["report_id"] = report_id
        report["created_at"] = created_at

        # Store the complete report including PageSpeed, sitemap and link checks.
        with get_db() as conn:
            conn.execute(
                "UPDATE reports SET report_json=? WHERE id=?",
                (json.dumps(report, ensure_ascii=False), report_id)
            )
            conn.commit()

        return HTMLResponse(render_report(report, lang))

    except (requests.RequestException, ValueError, OSError) as exc:
        logger.info("Audit failed: %s", type(exc).__name__)
        return HTMLResponse(home_html(lang, "error"), status_code=400)

    except Exception:
        logger.exception("Unexpected audit error")
        return HTMLResponse(home_html(lang, "error"), status_code=500)


@app.get("/report/{report_id}", response_class=HTMLResponse)
def report_page(report_id: int, lang: str = "en"):
    if lang not in LANGUAGES:
        lang = "en"

    report = get_report(report_id)

    if not report:
        return HTMLResponse(home_html(lang, "error"), status_code=404)

    return HTMLResponse(render_report(report, lang))


@app.post("/delete/{report_id}", response_class=HTMLResponse)
def delete_report(report_id: int, lang: str = Form("en")):
    if lang not in LANGUAGES:
        lang = "en"

    with get_db() as conn:
        conn.execute("DELETE FROM reports WHERE id=?", (report_id,))
        conn.commit()

    return HTMLResponse(home_html(lang))


@app.get("/health")
def health():
    return JSONResponse({
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION
    })


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=False
    )
