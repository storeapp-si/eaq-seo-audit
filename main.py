import os
import re
import json
import time
import socket
import sqlite3
import ipaddress
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

APP_NAME = "EAQ SEO Audit"
APP_VERSION = "3.0.0"
MAX_URL_LENGTH = 2048
MAX_HTML_BYTES = 2_000_000
TIMEOUT = 12
MAX_LINKS = 10
DB_PATH = os.getenv("DATABASE_PATH", "/tmp/eaq_audit.sqlite3")
PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY", "").strip()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eaq")

app = FastAPI(title=APP_NAME, version=APP_VERSION, docs_url=None, redoc_url=None)

LANGUAGES = {
    "en": "English",
    "ar": "العربية",
    "fr": "Français",
    "es": "Español",
    "de": "Deutsch",
    "zh": "中文",
}

TEXT = {
    "en": {
        "language": "Language", "tagline": "Analyze. Automate. Improve.",
        "heading": "Understand your website's SEO health",
        "intro": "Analyze technical SEO, performance, sitemaps and links.",
        "url": "Website URL", "audit": "Analyze website",
        "results": "Audit report", "overall": "Checklist score",
        "passed": "Passed checks", "issues": "Items to improve",
        "details": "Detailed findings", "priorities": "Recommended priorities",
        "history": "Saved reports", "no_history": "No saved reports yet.",
        "date": "Date", "website": "Website", "score": "Score",
        "actions": "Actions", "view": "View", "delete": "Delete",
        "back": "New audit", "print": "Print / Save PDF",
        "title": "Page title", "description": "Meta description",
        "canonical": "Canonical URL", "headings": "Heading structure",
        "images": "Image alt text", "https": "HTTPS",
        "viewport": "Mobile viewport", "lang": "HTML language",
        "schema": "Structured data", "social": "Social metadata",
        "robots": "Robots meta directive", "business": "Business information",
        "status": "Website status", "good": "Looks good",
        "warning": "Review recommended", "speed": "Google PageSpeed Insights",
        "sitemap": "Robots and sitemap", "link_check": "Sampled links",
        "security": "Security and privacy",
        "privacy": "Only public website URLs can be analyzed.",
        "invalid": "Enter a valid public HTTP or HTTPS website URL.",
        "error": "Unable to analyze this website.",
        "error_detail": "Check the URL. The website may block automated requests.",
        "footer": "Technical SEO guidance, not a guarantee of search ranking.",
        "no_business": "No business details detected.",
        "no_speed": "PageSpeed data is unavailable.",
        "not_rank": "This is a checklist score, not a Google ranking score.",
        "pdf_tip": "Choose Save as PDF in the print dialog.",
        "saved": "Reports are saved automatically.",
        "map": "Choose business location on the map",
        "business_name": "Business name (optional)",
        "address": "Business address (optional)",
        "latitude": "Latitude", "longitude": "Longitude",
        "map_help": "Click the map to select a location. You can also enter coordinates.",
        "location": "Business location",
        "no_location": "No business location provided.",
        "no_field": "No Google field data is available for this URL or origin.",
        "no_sitemap": "No sitemap was detected.",
        "no_robots": "robots.txt could not be verified.",
        "report_id": "Report ID",
        "score_chart": "SEO score overview",
        "performance_chart": "PageSpeed scores",
        "high": "High", "medium": "Medium", "low": "Low",
    },
    "ar": {
        "language": "اللغة", "tagline": "حلّل. أتمت. حسّن.",
        "heading": "افهم الحالة التقنية لموقعك",
        "intro": "فحص SEO التقني والسرعة وخريطة الموقع والروابط.",
        "url": "رابط الموقع", "audit": "تحليل الموقع",
        "results": "تقرير الفحص", "overall": "نتيجة قائمة الفحوصات",
        "passed": "الفحوصات المستوفاة", "issues": "نقاط تحتاج إلى تحسين",
        "details": "النتائج التفصيلية", "priorities": "أولويات التحسين",
        "history": "التقارير المحفوظة", "no_history": "لا توجد تقارير محفوظة.",
        "date": "التاريخ", "website": "الموقع", "score": "النتيجة",
        "actions": "الإجراءات", "view": "عرض", "delete": "حذف",
        "back": "تحليل جديد", "print": "طباعة / حفظ PDF",
        "title": "عنوان الصفحة", "description": "الوصف التعريفي",
        "canonical": "الرابط الأساسي Canonical", "headings": "بنية العناوين",
        "images": "النص البديل للصور", "https": "اتصال HTTPS",
        "viewport": "إعداد عرض الهاتف", "lang": "لغة HTML",
        "schema": "البيانات المنظمة", "social": "بيانات المشاركة الاجتماعية",
        "robots": "توجيهات Robots", "business": "معلومات النشاط التجاري",
        "status": "حالة الموقع", "good": "جيد مبدئيًا",
        "warning": "يُنصح بالمراجعة", "speed": "سرعة الموقع - Google PageSpeed",
        "sitemap": "ملف Robots وخريطة الموقع", "link_check": "فحص عينة من الروابط",
        "security": "الأمان والخصوصية",
        "privacy": "يمكن فحص روابط المواقع العامة فقط.",
        "invalid": "أدخل رابط HTTP أو HTTPS عامًا وصحيحًا.",
        "error": "تعذر فحص الموقع.",
        "error_detail": "تحقق من الرابط؛ قد يمنع الموقع الطلبات الآلية.",
        "footer": "إرشادات SEO تقنية ولا تضمن ترتيبًا معينًا في البحث.",
        "no_business": "لم تُكتشف معلومات واضحة عن النشاط التجاري.",
        "no_speed": "بيانات PageSpeed غير متاحة.",
        "not_rank": "هذه نتيجة قائمة فحوصات وليست ترتيبًا من Google.",
        "pdf_tip": "اختر حفظ بصيغة PDF من نافذة الطباعة.",
        "saved": "تُحفظ التقارير تلقائيًا.",
        "map": "اختر موقع النشاط التجاري على الخريطة",
        "business_name": "اسم النشاط التجاري (اختياري)",
        "address": "عنوان النشاط التجاري (اختياري)",
        "latitude": "خط العرض", "longitude": "خط الطول",
        "map_help": "انقر على الخريطة لاختيار الموقع، أو أدخل الإحداثيات يدويًا.",
        "location": "موقع النشاط التجاري",
        "no_location": "لم يُحدّد موقع للنشاط التجاري.",
        "no_field": "لا تتوفر بيانات ميدانية من Google لهذا الرابط أو النطاق.",
        "no_sitemap": "لم تُكتشف خريطة موقع.",
        "no_robots": "تعذر التحقق من robots.txt.",
        "report_id": "رقم التقرير",
        "score_chart": "ملخص نتيجة SEO",
        "performance_chart": "درجات PageSpeed",
        "high": "مرتفع", "medium": "متوسط", "low": "منخفض",
    },
    "fr": {
        "language": "Langue", "tagline": "Analyser. Automatiser. Améliorer.",
        "heading": "Comprenez la santé SEO de votre site",
        "intro": "Analyse technique SEO, vitesse, sitemap et liens.",
        "url": "URL du site", "audit": "Analyser le site",
        "results": "Rapport d'audit", "overall": "Score de contrôle",
        "passed": "Contrôles réussis", "issues": "Points à améliorer",
        "details": "Résultats détaillés", "priorities": "Priorités recommandées",
        "history": "Rapports enregistrés", "no_history": "Aucun rapport enregistré.",
        "date": "Date", "website": "Site", "score": "Score",
        "actions": "Actions", "view": "Voir", "delete": "Supprimer",
        "back": "Nouvel audit", "print": "Imprimer / Enregistrer PDF",
        "title": "Titre de la page", "description": "Méta-description",
        "canonical": "URL canonique", "headings": "Structure des titres",
        "images": "Textes alternatifs", "https": "HTTPS",
        "viewport": "Affichage mobile", "lang": "Langue HTML",
        "schema": "Données structurées", "social": "Métadonnées sociales",
        "robots": "Directive robots", "business": "Informations commerciales",
        "status": "État du site", "good": "Semble correct",
        "warning": "Vérification recommandée", "speed": "Google PageSpeed Insights",
        "sitemap": "Robots et sitemap", "link_check": "Liens échantillonnés",
        "security": "Sécurité et confidentialité",
        "privacy": "Seules les URL publiques peuvent être analysées.",
        "invalid": "Saisissez une URL publique HTTP ou HTTPS valide.",
        "error": "Impossible d'analyser le site.",
        "error_detail": "Vérifiez l'URL. Le site peut bloquer les requêtes automatiques.",
        "footer": "Conseils SEO techniques, sans garantie de classement.",
        "no_business": "Aucune information commerciale détectée.",
        "no_speed": "Données PageSpeed indisponibles.",
        "not_rank": "Ce score n'est pas un classement Google.",
        "pdf_tip": "Choisissez Enregistrer en PDF dans la fenêtre d'impression.",
        "saved": "Les rapports sont enregistrés automatiquement.",
        "map": "Choisir l'emplacement sur la carte",
        "business_name": "Nom de l'entreprise (facultatif)",
        "address": "Adresse (facultatif)", "latitude": "Latitude",
        "longitude": "Longitude",
        "map_help": "Cliquez sur la carte pour choisir l'emplacement.",
        "location": "Emplacement de l'entreprise",
        "no_location": "Aucun emplacement fourni.",
        "no_field": "Aucune donnée Google disponible.",
        "no_sitemap": "Aucun sitemap détecté.",
        "no_robots": "robots.txt non vérifié.",
        "report_id": "Rapport", "score_chart": "Aperçu du score SEO",
        "performance_chart": "Scores PageSpeed",
        "high": "Élevé", "medium": "Moyen", "low": "Faible",
    },
    "es": {
        "language": "Idioma", "tagline": "Analiza. Automatiza. Mejora.",
        "heading": "Comprende la salud SEO de tu sitio",
        "intro": "SEO técnico, velocidad, sitemap y enlaces.",
        "url": "URL del sitio", "audit": "Analizar sitio",
        "results": "Informe de auditoría", "overall": "Puntuación de comprobación",
        "passed": "Comprobaciones correctas", "issues": "Aspectos por mejorar",
        "details": "Resultados detallados", "priorities": "Prioridades recomendadas",
        "history": "Informes guardados", "no_history": "Todavía no hay informes.",
        "date": "Fecha", "website": "Sitio", "score": "Puntuación",
        "actions": "Acciones", "view": "Ver", "delete": "Eliminar",
        "back": "Nueva auditoría", "print": "Imprimir / Guardar PDF",
        "title": "Título de página", "description": "Meta descripción",
        "canonical": "URL canónica", "headings": "Estructura de encabezados",
        "images": "Texto alternativo", "https": "HTTPS",
        "viewport": "Vista móvil", "lang": "Idioma HTML",
        "schema": "Datos estructurados", "social": "Metadatos sociales",
        "robots": "Directiva robots", "business": "Información comercial",
        "status": "Estado del sitio", "good": "Parece correcto",
        "warning": "Se recomienda revisar", "speed": "Google PageSpeed Insights",
        "sitemap": "Robots y sitemap", "link_check": "Enlaces muestreados",
        "security": "Seguridad y privacidad",
        "privacy": "Solo se pueden analizar URL públicas.",
        "invalid": "Introduce una URL pública HTTP o HTTPS válida.",
        "error": "No se pudo analizar el sitio.",
        "error_detail": "Comprueba la URL; el sitio puede bloquear solicitudes automáticas.",
        "footer": "Consejos técnicos SEO, sin garantía de posicionamiento.",
        "no_business": "No se detectó información comercial.",
        "no_speed": "Datos de PageSpeed no disponibles.",
        "not_rank": "Esta puntuación no es un ranking de Google.",
        "pdf_tip": "Elige Guardar como PDF en el diálogo de impresión.",
        "saved": "Los informes se guardan automáticamente.",
        "map": "Elegir ubicación en el mapa",
        "business_name": "Nombre comercial (opcional)",
        "address": "Dirección (opcional)", "latitude": "Latitud",
        "longitude": "Longitud",
        "map_help": "Haz clic en el mapa para seleccionar la ubicación.",
        "location": "Ubicación comercial", "no_location": "No se indicó ubicación.",
        "no_field": "No hay datos de Google disponibles.",
        "no_sitemap": "No se detectó sitemap.", "no_robots": "No se pudo verificar robots.txt.",
        "report_id": "Informe", "score_chart": "Resumen de puntuación SEO",
        "performance_chart": "Puntuaciones PageSpeed",
        "high": "Alto", "medium": "Medio", "low": "Bajo",
    },
    "de": {
        "language": "Sprache", "tagline": "Analysieren. Automatisieren. Verbessern.",
        "heading": "Verstehen Sie den SEO-Zustand Ihrer Website",
        "intro": "Technisches SEO, Geschwindigkeit, Sitemap und Links prüfen.",
        "url": "Website-URL", "audit": "Website analysieren",
        "results": "Auditbericht", "overall": "Prüfpunktzahl",
        "passed": "Bestandene Prüfungen", "issues": "Verbesserungspunkte",
        "details": "Detaillierte Ergebnisse", "priorities": "Empfohlene Prioritäten",
        "history": "Gespeicherte Berichte", "no_history": "Noch keine Berichte.",
        "date": "Datum", "website": "Website", "score": "Punktzahl",
        "actions": "Aktionen", "view": "Anzeigen", "delete": "Löschen",
        "back": "Neues Audit", "print": "Drucken / PDF speichern",
        "title": "Seitentitel", "description": "Meta-Beschreibung",
        "canonical": "Kanonische URL", "headings": "Überschriftenstruktur",
        "images": "Alternativtexte", "https": "HTTPS",
        "viewport": "Mobile Ansicht", "lang": "HTML-Sprache",
        "schema": "Strukturierte Daten", "social": "Social-Metadaten",
        "robots": "Robots-Direktive", "business": "Unternehmensinformationen",
        "status": "Website-Status", "good": "Sieht gut aus",
        "warning": "Überprüfung empfohlen", "speed": "Google PageSpeed Insights",
        "sitemap": "Robots und Sitemap", "link_check": "Stichprobenlinks",
        "security": "Sicherheit und Datenschutz",
        "privacy": "Nur öffentliche URLs können analysiert werden.",
        "invalid": "Geben Sie eine gültige öffentliche HTTP- oder HTTPS-URL ein.",
        "error": "Website konnte nicht analysiert werden.",
        "error_detail": "URL prüfen; die Website kann automatisierte Anfragen blockieren.",
        "footer": "Technische SEO-Hinweise, keine Ranking-Garantie.",
        "no_business": "Keine Unternehmensdaten erkannt.",
        "no_speed": "PageSpeed-Daten nicht verfügbar.",
        "not_rank": "Diese Punktzahl ist kein Google-Ranking.",
        "pdf_tip": "Im Druckdialog Als PDF speichern wählen.",
        "saved": "Berichte werden automatisch gespeichert.",
        "map": "Standort auf der Karte auswählen",
        "business_name": "Unternehmensname (optional)",
        "address": "Adresse (optional)", "latitude": "Breitengrad",
        "longitude": "Längengrad",
        "map_help": "Klicken Sie auf die Karte, um einen Standort auszuwählen.",
        "location": "Unternehmensstandort", "no_location": "Kein Standort angegeben.",
        "no_field": "Keine Google-Daten verfügbar.", "no_sitemap": "Keine Sitemap erkannt.",
        "no_robots": "robots.txt konnte nicht geprüft werden.",
        "report_id": "Bericht", "score_chart": "SEO-Punktzahl",
        "performance_chart": "PageSpeed-Werte",
        "high": "Hoch", "medium": "Mittel", "low": "Niedrig",
    },
    "zh": {
        "language": "语言", "tagline": "分析。自动化。改进。",
        "heading": "了解网站的 SEO 状况", "intro": "检查技术 SEO、速度、站点地图和链接。",
        "url": "网站网址", "audit": "分析网站", "results": "审计报告",
        "overall": "检查得分", "passed": "通过的检查", "issues": "待改进项目",
        "details": "详细结果", "priorities": "建议优先事项",
        "history": "已保存报告", "no_history": "暂无报告。",
        "date": "日期", "website": "网站", "score": "得分",
        "actions": "操作", "view": "查看", "delete": "删除",
        "back": "新建审计", "print": "打印 / 保存 PDF",
        "title": "页面标题", "description": "元描述", "canonical": "规范网址",
        "headings": "标题结构", "images": "图片替代文本", "https": "HTTPS",
        "viewport": "移动视口", "lang": "HTML 语言", "schema": "结构化数据",
        "social": "社交元数据", "robots": "Robots 指令", "business": "商业信息",
        "status": "网站状态", "good": "看起来正常", "warning": "建议检查",
        "speed": "Google PageSpeed Insights", "sitemap": "Robots 与站点地图",
        "link_check": "抽样链接", "security": "安全与隐私",
        "privacy": "只能分析公开网址。", "invalid": "请输入有效的公开 HTTP 或 HTTPS 网址。",
        "error": "无法分析网站。", "error_detail": "请检查网址；网站可能阻止自动请求。",
        "footer": "提供技术 SEO 建议，不保证搜索排名。",
        "no_business": "未检测到商业信息。", "no_speed": "PageSpeed 数据不可用。",
        "not_rank": "此分数不是 Google 排名。", "pdf_tip": "在打印窗口中选择保存为 PDF。",
        "saved": "报告会自动保存。", "map": "在地图上选择位置",
        "business_name": "企业名称（可选）", "address": "地址（可选）",
        "latitude": "纬度", "longitude": "经度",
        "map_help": "点击地图选择位置。", "location": "企业位置",
        "no_location": "未提供位置。", "no_field": "没有可用的 Google 数据。",
        "no_sitemap": "未检测到站点地图。", "no_robots": "无法验证 robots.txt。",
        "report_id": "报告编号", "score_chart": "SEO 得分概览",
        "performance_chart": "PageSpeed 得分",
        "high": "高", "medium": "中", "low": "低",
    },
}


def tr(lang, key):
    lang = lang if lang in TEXT else "en"
    return TEXT[lang].get(key, TEXT["en"].get(key, key))


def esc(value):
    from html import escape
    return escape(str(value if value is not None else ""), quote=True)


# ---------------- Database ----------------

def get_db():
    folder = os.path.dirname(DB_PATH)
    if folder:
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            pass
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
    except sqlite3.OperationalError:
        conn = sqlite3.connect("/tmp/eaq_audit.sqlite3", timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


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
        )""")
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
        raise ValueError("Invalid scheme")
    if parsed.username or parsed.password:
        raise ValueError("Credentials not allowed")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".test")):
        raise ValueError("Private hostname")
    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            raise ValueError("Non-public IP")
    except ValueError as exc:
        if str(exc) == "Non-public IP":
            raise
        try:
            records = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
        except socket.gaierror as err:
            raise ValueError("DNS lookup failed") from err
        for rec in records:
            address = ipaddress.ip_address(rec[4][0].split("%")[0])
            if not address.is_global:
                raise ValueError("Hostname resolves to a non-public IP")
    return raw


def safe_get(url, allow_redirects=False, max_bytes=MAX_HTML_BYTES):
    url = validate_public_url(url)
    response = requests.get(
        url,
        timeout=TIMEOUT,
        allow_redirects=allow_redirects,
        headers={"User-Agent": "EAQ-SEO-Audit/3.0 (+public technical audit)"},
        stream=True,
    )
    chunks = []
    size = 0
    for chunk in response.iter_content(16384):
        if not chunk:
            continue
        size += len(chunk)
        if size > max_bytes:
            response.close()
            raise ValueError("Response too large")
        chunks.append(chunk)
    response._content = b"".join(chunks)
    response._content_consumed = True
    return response


def fetch_page(url):
    current = validate_public_url(url)
    for _ in range(6):
        response = safe_get(current, allow_redirects=False)
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            response.close()
            if not location:
                break
            current = validate_public_url(urljoin(current, location))
            continue
        response.encoding = response.encoding or "utf-8"
        return {
            "url": response.url,
            "status": response.status_code,
            "html": response.text,
        }
    raise ValueError("Too many redirects")


# ---------------- SEO analysis ----------------

def audit_html(url, html, status):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    description_tag = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    description = description_tag.get("content", "").strip() if description_tag else ""
    canonical_tag = soup.find("link", rel=lambda v: v and "canonical" in str(v).lower())
    canonical = canonical_tag.get("href", "").strip() if canonical_tag else ""
    h1s = soup.find_all("h1")
    images = soup.find_all("img")
    missing_alt = sum(1 for img in images if img.get("alt") is None or not img.get("alt", "").strip())
    viewport = soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)})
    html_lang = soup.html.get("lang", "") if soup.html else ""
    jsonld = soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)})
    social = soup.find("meta", property=re.compile("^(og:|twitter:)", re.I))
    robots_meta = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    business = {}
    for tag in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        try:
            data = json.loads(tag.string or tag.get_text())
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict) and item.get("@type"):
                    typ = item.get("@type")
                    if any(x in str(typ).lower() for x in ("organization", "localbusiness", "store", "professionalservice")):
                        business["Name"] = item.get("name", "")
                        business["Address"] = item.get("address", "")
                        business["Website"] = item.get("url", "")
                        break
        except Exception:
            pass

    checks = [
        ("title", bool(title), title or "No page title detected."),
        ("description", bool(description), description or "No meta description detected."),
        ("canonical", bool(canonical), canonical or "No canonical link detected."),
        ("headings", len(h1s) == 1, f"{len(h1s)} H1 heading(s)"),
        ("images", missing_alt == 0, f"{missing_alt} image(s) without alt out of {len(images)}"),
        ("https", urlparse(url).scheme == "https", urlparse(url).scheme.upper()),
        ("viewport", bool(viewport), "Viewport metadata present" if viewport else "Viewport metadata missing"),
        ("lang", bool(html_lang), html_lang or "HTML lang attribute missing"),
        ("schema", bool(jsonld), f"{len(jsonld)} JSON-LD block(s)"),
        ("social", bool(social), "Social metadata present" if social else "Social metadata missing"),
        ("robots", bool(robots_meta), "Robots meta directive present" if robots_meta else "No robots meta directive"),
        ("business", bool(business), "Business structured data detected" if business else "No business details detected."),
        ("status", 200 <= status < 400, f"HTTP {status}"),
    ]
    results = [{"key": k, "ok": ok, "details": detail} for k, ok, detail in checks]
    passed = sum(1 for item in results if item["ok"])
    score = round(100 * passed / len(results))
    priorities = []
    for item in results:
        if item["ok"]:
            continue
        priority = "high" if item["key"] == "description" else "medium"
        priorities.append({
            "key": item["key"],
            "priority": priority,
            "details": item["details"],
        })

    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        target = urljoin(url, a["href"].strip())
        parsed = urlparse(target)
        if parsed.scheme in ("http", "https") and target not in seen:
            seen.add(target)
            links.append(target)
        if len(links) >= MAX_LINKS:
            break

    return {
        "url": url, "title": title, "score": score,
        "passed": passed, "total": len(results),
        "checks": results, "priorities": priorities,
        "business": business, "sample_links": links,
    }


# ---------------- External checks ----------------

def check_resource(url):
    try:
        response = safe_get(url, max_bytes=500_000)
        status = response.status_code
        response.close()
        return {"url": url, "status": status, "ok": 200 <= status < 400}
    except Exception:
        return {"url": url, "status": None, "ok": False}


def robots_sitemap(url):
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    robots = check_resource(origin + "/robots.txt")
    candidates = [origin + "/sitemap.xml"]
    if robots["ok"]:
        try:
            r = safe_get(origin + "/robots.txt", max_bytes=200_000)
            for line in r.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    sitemap = line.split(":", 1)[1].strip()
                    if sitemap.startswith("http"):
                        candidates.insert(0, sitemap)
            r.close()
        except Exception:
            pass
    results = []
    for item in list(dict.fromkeys(candidates))[:5]:
        results.append(check_resource(item))
    return {"robots": robots, "sitemaps": results}


def check_link(url):
    try:
        response = requests.head(
            validate_public_url(url), timeout=8, allow_redirects=False,
            headers={"User-Agent": "EAQ-SEO-Audit/3.0"}
        )
        status = response.status_code
        response.close()
        if status in (403, 405, 429, 501) or status >= 500:
            return {"url": url, "status": status, "state": "Review"}
        return {"url": url, "status": status, "state": "OK" if 200 <= status < 400 else "Broken"}
    except Exception:
        return {"url": url, "status": None, "state": "Unavailable"}


def pagespeed_check(url):
    params = {"url": url, "strategy": "mobile"}
    if PAGESPEED_API_KEY:
        params["key"] = PAGESPEED_API_KEY
    try:
        response = requests.get(
            "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
            params=params, timeout=35
        )
        if response.status_code != 200:
            return {"available": False, "scores": {}, "lab": {}}
        data = response.json()
        lighthouse = data.get("lighthouseResult", {})
        categories = lighthouse.get("categories", {})
        scores = {}
        for key in ("performance", "accessibility", "best-practices", "seo"):
            value = categories.get(key, {}).get("score")
            if value is not None:
                scores[key] = round(value * 100)
        lab = {}
        audits = lighthouse.get("audits", {})
        for key in ("first-contentful-paint", "largest-contentful-paint",
                    "total-blocking-time", "cumulative-layout-shift", "speed-index"):
            if key in audits:
                lab[key.replace("-", " ").title()] = audits[key].get("displayValue", "")
        return {"available": bool(scores), "scores": scores, "lab": lab}
    except Exception:
        return {"available": False, "scores": {}, "lab": {}}


def run_external_checks(url, report):
    report["robots_sitemap"] = robots_sitemap(url)
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(check_link, link) for link in report.get("sample_links", [])]
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception:
                pass
    report["link_results"] = sorted(results, key=lambda x: x["url"])
    report["pagespeed"] = pagespeed_check(url)
    return report


# ---------------- Report storage ----------------

def save_report(report):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_db() as db:
        cursor = db.execute(
            "INSERT INTO reports(url,title,score,report_json,created_at) VALUES(?,?,?,?,?)",
            (report["url"], report.get("title", ""), report["score"],
             json.dumps(report, ensure_ascii=False), now)
        )
        report_id = cursor.lastrowid
        db.commit()
    report["report_id"] = report_id
    report["created_at"] = now
    with get_db() as db:
        db.execute(
            "UPDATE reports SET report_json=? WHERE id=?",
            (json.dumps(report, ensure_ascii=False), report_id)
        )
        db.commit()
    return report_id


def get_report(report_id):
    with get_db() as db:
        row = db.execute("SELECT report_json FROM reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["report_json"])
    except Exception:
        return None


def get_history():
    with get_db() as db:
        return db.execute(
            "SELECT id,url,title,score,created_at FROM reports ORDER BY id DESC LIMIT 100"
        ).fetchall()


# ---------------- HTML helpers ----------------

def page_shell(content, lang="en", title=APP_NAME):
    options = "".join(
        f'<option value="{code}" {"selected" if code == lang else ""}>{esc(name)}</option>'
        for code, name in LANGUAGES.items()
    )
    direction = "rtl" if lang == "ar" else "ltr"
    return f"""<!doctype html>
<html lang="{esc(lang)}" dir="{direction}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
:root{{--bg:#f3f6fb;--surface:#fff;--text:#172033;--muted:#64748b;--border:#e2e8f0;--blue:#2563eb}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,"Segoe UI",Arial,sans-serif;line-height:1.6}}
a{{color:var(--blue);text-decoration:none}}a:hover{{text-decoration:underline}}
button,input,select{{font:inherit}}
.topbar{{background:#101b31;color:#fff;padding:14px 20px}}
.topbar-inner{{max-width:1120px;margin:auto;display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}}
.logo{{font-size:20px;font-weight:800}}.logo span{{color:#93c5fd}}.tagline{{color:#cbd5e1;font-size:12px}}
.lang-form{{display:flex;gap:7px;align-items:center}}.lang-form select{{max-width:125px;padding:5px 8px;border-radius:7px;color:#172033;background:white}}
.wrap{{max-width:1120px;margin:28px auto;padding:0 18px 40px}}
.hero{{background:linear-gradient(135deg,#172b4d,#1d4ed8);color:#fff;border-radius:20px;padding:28px;margin-bottom:20px;box-shadow:0 10px 35px #14234612}}
.hero h1{{font-size:clamp(25px,4vw,38px);line-height:1.25;margin:0 0 10px}}.hero p{{color:#dbeafe;overflow-wrap:anywhere}}
.panel{{background:white;border:1px solid var(--border);border-radius:16px;padding:21px;margin-bottom:18px;box-shadow:0 10px 35px #1423460a}}
.panel h2{{margin:0 0 14px;font-size:20px}}
.form-row{{display:flex;gap:10px;align-items:stretch}}
.url-input,input[type=text],input[type=number]{{min-width:0;border:1px solid #cbd5e1;border-radius:10px;padding:11px;background:white;color:#172033;width:100%}}
.url-input{{flex:1}}
.btn{{display:inline-flex;justify-content:center;align-items:center;gap:8px;border:0;border-radius:10px;padding:11px 15px;cursor:pointer;font-weight:700}}
.btn-primary{{background:#2563eb;color:white}}.btn-light{{background:#edf2f9;color:#172033}}.btn-danger{{background:#fee2e2;color:#991b1b}}
.small{{font-size:13px;color:var(--muted)}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}}
.metric-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}}
.metric{{padding:16px;border:1px solid var(--border);border-radius:13px;background:#fff;color:#172033;min-width:0}}
.metric strong{{font-size:25px;display:block;color:#172033;line-height:1.4;overflow-wrap:anywhere}}
.metric span{{display:block;margin-top:5px;font-size:13px;color:#475569;line-height:1.5}}
.check-list{{display:grid;gap:10px}}.check{{display:flex;gap:12px;align-items:flex-start;padding:13px;border:1px solid var(--border);border-radius:12px;background:white}}
.check-icon{{flex:none;width:25px;height:25px;border-radius:50%;display:grid;place-items:center;font-size:13px;font-weight:800}}
.check-ok .check-icon{{background:#dcfce7;color:#166534}}.check-no .check-icon{{background:#fef3c7;color:#92400e}}
.check h3{{font-size:15px;margin:0 0 3px}}.check p{{font-size:13px;color:var(--muted);margin:0;overflow-wrap:anywhere}}
.priority{{border-inline-start:4px solid #f59e0b;padding:12px 14px;background:#fffbeb;border-radius:8px;margin:9px 0}}
.priority.high{{border-color:#dc2626;background:#fef2f2}}.pill{{display:inline-block;border-radius:999px;padding:4px 9px;background:#eef2ff;color:#3730a3;font-size:12px;font-weight:700}}
.table-wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:12px;text-align:start;border-bottom:1px solid var(--border);vertical-align:top;overflow-wrap:anywhere}}
th{{color:var(--muted);font-size:12px}}.business-row{{padding:9px 0;border-bottom:1px solid var(--border);overflow-wrap:anywhere}}
.notice{{padding:12px 14px;background:#eff6ff;border:1px solid #bfdbfe;color:#1e40af;border-radius:10px;font-size:13px;margin-top:14px}}
.error{{background:#fef2f2;border:1px solid #fecaca;color:#991b1b;padding:14px;border-radius:12px;margin:15px 0}}
#map{{height:320px;border-radius:12px;border:1px solid #cbd5e1;margin-top:12px;z-index:1}}
.location-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.chart-row{{display:grid;grid-template-columns:190px 1fr;gap:22px;align-items:center}}
.gauge{{width:100%;max-width:190px;display:block;margin:auto}}
.bar-chart{{display:grid;gap:12px}}.bar-item{{display:grid;grid-template-columns:minmax(90px,140px) 1fr 45px;gap:10px;align-items:center;font-size:13px}}
.bar-track{{height:13px;border-radius:99px;background:#e2e8f0;overflow:hidden}}
.bar-fill{{height:100%;border-radius:99px;background:linear-gradient(90deg,#2563eb,#06b6d4)}}
footer{{max-width:1120px;margin:auto;padding:0 18px 28px;color:var(--muted);font-size:12px}}
@media(max-width:720px){{.wrap{{margin-top:16px;padding:0 12px 28px}}.hero{{padding:22px 18px}}.panel{{padding:16px}}.grid{{grid-template-columns:1fr}}.metric-grid{{grid-template-columns:1fr 1fr}}.form-row{{flex-direction:column}}.btn{{width:100%}}.chart-row{{grid-template-columns:1fr}}.location-grid{{grid-template-columns:1fr}}.topbar{{padding:12px}}}}
@media print{{.topbar,.no-print,footer{{display:none!important}}body{{background:white}}.wrap{{margin:0;padding:0}}.panel,.hero{{box-shadow:none;break-inside:avoid}}}}
</style>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" defer></script>
<script src="/app.js" defer></script>
</head>
<body>
<header class="topbar"><div class="topbar-inner">
<div><div class="logo">EAQ <span>SEO Audit</span></div><div class="tagline">{esc(tr(lang,"tagline"))}</div></div>
<form method="get" action="/" class="lang-form no-print">
<label for="lang">{esc(tr(lang,"language"))}</label>
<select id="lang" name="lang">{options}</select>
</form></div></header>
<main class="wrap">{content}</main>
<footer>{esc(tr(lang,"footer"))}</footer>
</body></html>"""


def history_html(lang):
    rows = get_history()
    if not rows:
        return f'<p class="small">{esc(tr(lang,"no_history"))}</p>'
    out = ['<div class="table-wrap"><table><thead><tr>']
    for key in ("date", "website", "score", "actions"):
        out.append(f"<th>{esc(tr(lang,key))}</th>")
    out.append("</tr></thead><tbody>")
    for row in rows:
        report_link = f"/report/{int(row['id'])}?lang={lang}"
        out.append(
            "<tr>"
            f"<td>{esc(row['created_at'][:19].replace('T',' '))}</td>"
            f'<td><a href="{report_link}">{esc(row["title"] or row["url"])}</a>'
            f'<br><span class="small">{esc(row["url"])}</span></td>'
            f'<td><strong>{int(row["score"])}/100</strong></td>'
            f'<td><a href="{report_link}">{esc(tr(lang,"view"))}</a> · '
            f'<form method="post" action="/delete/{int(row["id"])}" style="display:inline">'
            f'<input type="hidden" name="lang" value="{esc(lang)}">'
            f'<button class="btn btn-danger" type="submit">{esc(tr(lang,"delete"))}</button></form></td>'
            "</tr>"
        )
    out.append("</tbody></table></div>")
    return "".join(out)


def home_html(lang="en", error=None):
    error_html = (
        f'<div class="error"><strong>{esc(tr(lang,error))}</strong>'
        f'<p>{esc(tr(lang,"error_detail"))}</p></div>' if error else ""
    )
    content = f"""
<section class="hero"><h1>{esc(tr(lang,"heading"))}</h1><p>{esc(tr(lang,"intro"))}</p></section>
<section class="panel">
<h2>{esc(tr(lang,"audit"))}</h2>
<form method="post" action="/audit">
<input type="hidden" name="lang" value="{esc(lang)}">
<label for="url"><strong>{esc(tr(lang,"url"))}</strong></label>
<div class="form-row" style="margin-top:9px">
<input class="url-input" type="text" id="url" name="url" maxlength="{MAX_URL_LENGTH}"
placeholder="https://example.com" autocomplete="url" inputmode="url">
<button class="btn btn-primary" type="submit">{esc(tr(lang,"audit"))}</button>
</div>
<hr style="border:0;border-top:1px solid #e2e8f0;margin:22px 0">
<h2>{esc(tr(lang,"business"))}</h2>
<div class="location-grid">
<div><label for="business_name">{esc(tr(lang,"business_name"))}</label>
<input id="business_name" name="business_name" type="text" maxlength="200"></div>
<div><label for="business_address">{esc(tr(lang,"address"))}</label>
<input id="business_address" name="business_address" type="text" maxlength="300"></div>
<div><label for="latitude">{esc(tr(lang,"latitude"))}</label>
<input id="latitude" name="latitude" type="number" step="any" min="-90" max="90" placeholder="36.19"></div>
<div><label for="longitude">{esc(tr(lang,"longitude"))}</label>
<input id="longitude" name="longitude" type="number" step="any" min="-180" max="180" placeholder="6.15"></div>
</div>
<p class="small">{esc(tr(lang,"map_help"))}</p>
<div id="map" aria-label="Interactive location map"></div>
{error_html}
<div class="notice">{esc(tr(lang,"privacy"))}</div>
</form></section>
<section class="panel"><h2>{esc(tr(lang,"history"))}</h2>{history_html(lang)}</section>
"""
    return page_shell(content, lang, APP_NAME)


def gauge_svg(score):
    color = "#16a34a" if score >= 80 else "#f59e0b" if score >= 50 else "#dc2626"
    # A half-circle gauge, with a score arc.
    circumference = 267.0
    length = circumference * max(0, min(100, score)) / 100
    return f"""
<svg class="gauge" viewBox="0 0 220 140" role="img" aria-label="SEO score {score} out of 100">
<path d="M25 115 A85 85 0 0 1 195 115" fill="none" stroke="#e2e8f0" stroke-width="17" stroke-linecap="round"/>
<path d="M25 115 A85 85 0 0 1 195 115" fill="none" stroke="{color}" stroke-width="17"
stroke-linecap="round" pathLength="100" stroke-dasharray="{score} 100"/>
<text x="110" y="96" text-anchor="middle" font-size="33" font-weight="800" fill="#172033">{score}</text>
<text x="110" y="119" text-anchor="middle" font-size="11" fill="#64748b">/ 100</text>
</svg>"""


def render_report(report, lang="en"):
    checks = []
    for item in report.get("checks", []):
        key = item["key"]
        state = tr(lang, "good") if item["ok"] else tr(lang, "warning")
        checks.append(
            f'<article class="check {"check-ok" if item["ok"] else "check-no"}">'
            f'<div class="check-icon">{"✓" if item["ok"] else "!"}</div>'
            f'<div><h3>{esc(tr(lang,key))}</h3>'
            f'<p>{esc(state)} · {esc(item.get("details",""))}</p></div></article>'
        )

    priorities = []
    for item in report.get("priorities", []):
        level = item.get("priority", "medium")
        priorities.append(
            f'<div class="priority {esc(level)}"><span class="pill">{esc(tr(lang,level))}</span> '
            f'<strong>{esc(tr(lang,item["key"]))}</strong>'
            f'<div class="small">{esc(item.get("details",""))}</div></div>'
        )

    score = int(report.get("score", 0))
    passed = int(report.get("passed", 0))
    total = int(report.get("total", 0))
    pagespeed = report.get("pagespeed", {})
    if pagespeed.get("available"):
        bars = []
        for name, value in pagespeed.get("scores", {}).items():
            bars.append(
                f'<div class="bar-item"><span>{esc(name.replace("-"," ").title())}</span>'
                f'<div class="bar-track"><div class="bar-fill" style="width:{max(0,min(100,int(value)))}%"></div></div>'
                f'<strong>{int(value)}/100</strong></div>'
            )
        speed_html = '<div class="bar-chart">' + "".join(bars) + "</div>"
        if pagespeed.get("lab"):
            speed_html += "<h3>Lighthouse lab measurements</h3><table>"
            for key, value in pagespeed["lab"].items():
                speed_html += f"<tr><th>{esc(key)}</th><td>{esc(value)}</td></tr>"
            speed_html += "</table>"
    else:
        speed_html = f'<p class="small">{esc(tr(lang,"no_speed"))}</p>'

    robots = report.get("robots_sitemap", {})
    robots_data = robots.get("robots", {})
    sitemap_html = (
        f'<p><strong>robots.txt:</strong> HTTP {esc(robots_data.get("status") or "Unavailable")}</p>'
    )
    sitemap_html += "<div class='table-wrap'><table><tr><th>URL</th><th>HTTP</th><th>Result</th></tr>"
    for item in robots.get("sitemaps", []):
        sitemap_html += (
            f'<tr><td>{esc(item["url"])}</td><td>{esc(item.get("status") or "—")}</td>'
            f'<td>{"Found" if item.get("ok") else "Not verified"}</td></tr>'
        )
    sitemap_html += "</table></div>"

    link_html = (
        '<p class="small">Only a limited sample is checked. Some servers block automated link checks.</p>'
        '<div class="table-wrap"><table><tr><th>URL</th><th>HTTP</th><th>Result</th></tr>'
    )
    for item in report.get("link_results", []):
        link_html += (
            f'<tr><td>{esc(item["url"])}</td><td>{esc(item.get("status") or "—")}</td>'
            f'<td>{esc(item["state"])}</td></tr>'
        )
    link_html += "</table></div>"

    business = report.get("business", {})
    business_rows = ""
    for key, value in business.items():
        if value:
            business_rows += f'<div class="business-row"><strong>{esc(key)}:</strong> {esc(value)}</div>'
    if not business_rows:
        business_rows = f'<p class="small">{esc(tr(lang,"no_business"))}</p>'

    location = report.get("location", {})
    if location.get("latitude") not in ("", None) and location.get("longitude") not in ("", None):
        lat, lon = float(location["latitude"]), float(location["longitude"])
        map_html = (
            f'<p>{esc(location.get("address") or "")}</p>'
            f'<p class="small">{esc(tr(lang,"latitude"))}: {lat}, {esc(tr(lang,"longitude"))}: {lon}</p>'
            f'<p><a href="https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=15/{lat}/{lon}" target="_blank" rel="noopener">Open location in OpenStreetMap</a></p>'
            f'<iframe title="Business location" width="100%" height="300" style="border:0;border-radius:12px" loading="lazy" '
            f'src="https://www.openstreetmap.org/export/embed.html?bbox={lon-0.02}%2C{lat-0.02}%2C{lon+0.02}%2C{lat+0.02}&layer=mapnik&marker={lat}%2C{lon}"></iframe>'
        )
    else:
        map_html = f'<p class="small">{esc(tr(lang,"no_location"))}</p>'

    content = f"""
<section class="hero">
<div class="no-print" style="margin-bottom:12px"><a href="/?lang={lang}" style="color:#dbeafe">← {esc(tr(lang,"back"))}</a></div>
<h1>{esc(tr(lang,"results"))}</h1><p>{esc(report["url"])}</p>
<div class="chart-row" style="margin-top:20px">
<div>{gauge_svg(score)}<p style="text-align:center">{esc(tr(lang,"score_chart"))}</p></div>
<div class="metric-grid">
<div class="metric"><strong>{score}/100</strong><span>{esc(tr(lang,"overall"))}</span></div>
<div class="metric"><strong>{passed}/{total}</strong><span>{esc(tr(lang,"passed"))}</span></div>
<div class="metric"><strong>{len(report.get("priorities",[]))}</strong><span>{esc(tr(lang,"issues"))}</span></div>
</div></div>
<p style="font-size:13px">{esc(tr(lang,"not_rank"))}</p>
</section>
<div class="no-print" style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px">
<button class="btn btn-primary" id="print-report" type="button">{esc(tr(lang,"print"))}</button>
<a class="btn btn-light" href="/?lang={lang}">{esc(tr(lang,"back"))}</a></div>
<section class="panel"><h2>{esc(tr(lang,"speed"))}</h2>{speed_html}</section>
<section class="panel"><h2>{esc(tr(lang,"sitemap"))}</h2>{sitemap_html}</section>
<section class="panel"><h2>{esc(tr(lang,"link_check"))}</h2>{link_html}</section>
<section class="panel"><h2>{esc(tr(lang,"priorities"))}</h2>{"".join(priorities) or "<p>No checklist priorities detected.</p>"}</section>
<section class="panel"><h2>{esc(tr(lang,"details"))}</h2><div class="check-list">{"".join(checks)}</div></section>
<section class="panel"><h2>{esc(tr(lang,"business"))}</h2>{business_rows}</section>
<section class="panel"><h2>{esc(tr(lang,"location"))}</h2>{map_html}</section>
<section class="panel"><h2>{esc(tr(lang,"security"))}</h2>
<p class="small">{esc(tr(lang,"privacy"))}</p>
<p class="small">{esc(tr(lang,"pdf_tip"))}</p><p class="small">{esc(tr(lang,"saved"))}</p>
<p class="small">{esc(tr(lang,"report_id"))}: {esc(report.get("report_id","—"))}</p></section>
"""
    return page_shell(content, lang, f'{tr(lang,"results")} — {report.get("title") or report["url"]}')


# ---------------- Browser JavaScript ----------------

APP_JS = r"""
"use strict";
document.addEventListener("DOMContentLoaded", function () {
  const langSelect = document.getElementById("lang");
  if (langSelect) {
    langSelect.addEventListener("change", function () {
      this.form.submit();
    });
  }

  const printButton = document.getElementById("print-report");
  if (printButton) {
    printButton.addEventListener("click", function () {
      window.print();
    });
  }

  const mapElement = document.getElementById("map");
  if (mapElement && window.L) {
    const latInput = document.getElementById("latitude");
    const lonInput = document.getElementById("longitude");
    const defaultLat = 36.19;
    const defaultLon = 6.15;
    const initialLat = parseFloat(latInput.value) || defaultLat;
    const initialLon = parseFloat(lonInput.value) || defaultLon;
    const map = L.map("map").setView([initialLat, initialLon], 6);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    let marker = L.marker([initialLat, initialLon]).addTo(map);

    function setLocation(lat, lon) {
      latInput.value = Number(lat).toFixed(6);
      lonInput.value = Number(lon).toFixed(6);
      marker.setLatLng([lat, lon]);
    }

    map.on("click", function (event) {
      setLocation(event.latlng.lat, event.latlng.lng);
    });

    latInput.addEventListener("change", function () {
      const lat = parseFloat(latInput.value);
      const lon = parseFloat(lonInput.value);
      if (Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180) {
        setLocation(lat, lon);
        map.setView([lat, lon], 13);
      }
    });
    lonInput.addEventListener("change", function () {
      const lat = parseFloat(latInput.value);
      const lon = parseFloat(lonInput.value);
      if (Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180) {
        setLocation(lat, lon);
        map.setView([lat, lon], 13);
      }
    });
    setTimeout(function () { map.invalidateSize(); }, 300);
  }
});
"""


@app.get("/app.js")
def app_js():
    return Response(APP_JS, media_type="application/javascript", headers={"Cache-Control": "no-cache"})


# ---------------- Routes ----------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request, lang: str = "en"):
    if lang not in LANGUAGES:
        lang = "en"
    return HTMLResponse(home_html(lang))


@app.post("/audit", response_class=HTMLResponse)
def audit(
    url: str = Form(""),
    lang: str = Form("en"),
    business_name: str = Form(""),
    business_address: str = Form(""),
    latitude: str = Form(""),
    longitude: str = Form(""),
):
    if lang not in LANGUAGES:
        lang = "en"
    try:
        clean_url = validate_public_url(url)
    except ValueError:
        return HTMLResponse(home_html(lang, "invalid"), status_code=400)

    try:
        fetched = fetch_page(clean_url)
        report = audit_html(fetched["url"], fetched["html"], fetched["status"])
        report["business"] = report.get("business", {})
        if business_name.strip():
            report["business"]["Name"] = business_name.strip()[:200]
        if business_address.strip():
            report["business"]["Address"] = business_address.strip()[:300]

        loc = {"address": business_address.strip()[:300]}
        try:
            lat = float(latitude) if latitude.strip() else None
            lon = float(longitude) if longitude.strip() else None
        except ValueError:
            lat, lon = None, None
        if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
            loc["latitude"] = lat
            loc["longitude"] = lon
        report["location"] = loc

        report = run_external_checks(fetched["url"], report)
        save_report(report)
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
    with get_db() as db:
        db.execute("DELETE FROM reports WHERE id=?", (report_id,))
        db.commit()
    return HTMLResponse(home_html(lang))


@app.get("/health")
def health():
    return JSONResponse({"status": "ok", "app": APP_NAME, "version": APP_VERSION})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
