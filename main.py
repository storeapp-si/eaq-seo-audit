
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
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

# ============================================================
# EAQ SEO AUDIT
# Analyze. Automate. Improve.
# ============================================================

APP_NAME = "EAQ SEO Audit"
APP_VERSION = "1.0.0"
MAX_HTML_BYTES = 2_000_000
REQUEST_TIMEOUT = 12
MAX_HISTORY = 100
MAX_URL_LENGTH = 2048

DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    "/var/data/eaq_audit.sqlite3"
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eaq")

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    docs_url=None,
    redoc_url=None
)

# ------------------------------------------------------------
# Security headers
# ------------------------------------------------------------

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "font-src 'self' data:; "
            "form-action 'self'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'"
        )
        return response

app.add_middleware(SecurityHeadersMiddleware)

# ------------------------------------------------------------
# Database
# ------------------------------------------------------------

def database_file():
    parent = os.path.dirname(DATABASE_PATH)
    if parent:
        try:
            os.makedirs(parent, exist_ok=True)
            test_path = os.path.join(parent, ".eaq_write_test")
            with open(test_path, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(test_path)
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

# ------------------------------------------------------------
# Internationalization
# ------------------------------------------------------------

TRANSLATIONS = {
    "en": {
        "brand": "EAQ SEO Audit",
        "tagline": "Analyze. Automate. Improve.",
        "heading": "Understand your website's SEO health",
        "intro": "Run a technical and on-page checklist using publicly accessible page content.",
        "url": "Website URL",
        "audit": "Analyze website",
        "placeholder": "https://example.com",
        "results": "Audit report",
        "overall": "Checklist score",
        "not_rank": "This is an audit checklist score, not a Google ranking score.",
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
        "print": "Print / Save PDF",
        "back": "New audit",
        "title": "Page title",
        "description": "Meta description",
        "canonical": "Canonical URL",
        "headings": "Heading structure",
        "images": "Image alt text",
        "links": "Links",
        "https": "HTTPS",
        "robots": "Robots directive",
        "viewport": "Mobile viewport",
        "lang": "HTML language",
        "schema": "Structured data",
        "social": "Social sharing metadata",
        "business": "Business information",
        "yes": "Found",
        "no": "Missing or needs review",
        "warning": "Review recommended",
        "good": "Looks good",
        "missing": "Not detected",
        "not_measured": "Not measured",
        "speed_note": "Page speed and Core Web Vitals were not measured by this audit.",
        "business_note": "Business details are shown only when detected in the page metadata or structured data.",
        "location": "Published business address",
        "map": "Search this address on map",
        "no_address": "No published business address detected.",
        "error": "Unable to audit this URL.",
        "error_detail": "Check the address and try again. The site may block automated requests.",
        "invalid": "Enter a valid public HTTP or HTTPS website URL.",
        "loading": "Analyzing…",
        "chart_bars": "Check summary",
        "chart_donut": "Result distribution",
        "chart_radar": "SEO categories",
        "chart_gauge": "Checklist score",
        "priority_high": "High priority",
        "priority_medium": "Medium priority",
        "priority_low": "Low priority",
        "footer": "EAQ SEO Audit provides technical guidance, not a guarantee of search ranking.",
        "save": "Reports are saved automatically.",
        "business_name": "Business name",
        "phone": "Phone",
        "email": "Email",
        "website_field": "Website",
        "no_title": "No page title detected.",
        "no_description": "No meta description detected.",
        "no_h1": "No H1 heading detected.",
        "long_title": "Title is unusually long.",
        "short_title": "Title is short; consider describing the page more clearly.",
        "long_desc": "Meta description is long.",
        "short_desc": "Meta description is short.",
        "images_missing": "Some images have no alt attribute.",
        "multiple_h1": "Multiple H1 headings detected; review the page structure.",
        "no_canonical": "No canonical link detected.",
        "no_viewport": "Mobile viewport metadata is missing.",
        "no_lang": "HTML lang attribute is missing.",
        "no_schema": "No JSON-LD structured data detected.",
        "no_social": "Open Graph or social sharing metadata is limited or missing.",
        "no_https": "The submitted URL does not use HTTPS.",
        "no_robots": "No robots meta directive detected; this is not necessarily an error.",
        "no_business": "No recognizable business details found in page metadata.",
        "site_external": "External links",
        "site_internal": "Internal links",
        "indexable": "Indexing directives",
        "report_id": "Report ID",
        "language": "Language",
        "pdf_tip": "In the print dialog, select “Save as PDF”.",
        "security": "Security and privacy",
        "privacy_note": "The audit fetches the public page server-side. Do not submit private URLs or pages requiring authentication.",
    },
    "ar": {
        "brand": "EAQ SEO Audit",
        "tagline": "حلّل. أتمت. حسّن.",
        "heading": "افهم الحالة التقنية لموقعك",
        "intro": "تحليل قائمة فحوصات تقنية ومحتوى الصفحة العامة.",
        "url": "رابط الموقع",
        "audit": "تحليل الموقع",
        "placeholder": "https://example.com",
        "results": "تقرير الفحص",
        "overall": "نتيجة قائمة الفحوصات",
        "not_rank": "هذه نتيجة قائمة فحوصات وليست ترتيبًا من Google.",
        "passed": "الفحوصات المستوفاة",
        "issues": "نقاط تحتاج إلى تحسين",
        "details": "النتائج التفصيلية",
        "priorities": "أولويات مقترحة",
        "history": "التقارير المحفوظة",
        "no_history": "لا توجد تقارير محفوظة بعد.",
        "date": "التاريخ",
        "website": "الموقع",
        "score": "النتيجة",
        "actions": "الإجراءات",
        "view": "عرض",
        "delete": "حذف",
        "print": "طباعة / حفظ PDF",
        "back": "تحليل جديد",
        "title": "عنوان الصفحة",
        "description": "الوصف التعريفي",
        "canonical": "الرابط الأساسي Canonical",
        "headings": "بنية العناوين",
        "images": "النص البديل للصور",
        "links": "الروابط",
        "https": "اتصال HTTPS",
        "robots": "توجيهات Robots",
        "viewport": "إعداد عرض الهاتف",
        "lang": "لغة HTML",
        "schema": "البيانات المنظمة",
        "social": "بيانات المشاركة الاجتماعية",
        "business": "معلومات النشاط التجاري",
        "yes": "موجود",
        "no": "مفقود أو يحتاج مراجعة",
        "warning": "يُنصح بالمراجعة",
        "good": "جيد مبدئيًا",
        "missing": "لم يتم اكتشافه",
        "not_measured": "لم يتم قياسه",
        "speed_note": "لم يجرِ هذا الفحص قياس سرعة الصفحة أو Core Web Vitals.",
        "business_note": "تُعرض بيانات النشاط التجاري فقط عند اكتشافها في بيانات الصفحة أو البيانات المنظمة.",
        "location": "عنوان النشاط المنشور",
        "map": "البحث عن العنوان على الخريطة",
        "no_address": "لم يُكتشف عنوان تجاري منشور.",
        "error": "تعذر فحص الرابط.",
        "error_detail": "تحقق من الرابط وحاول مجددًا. قد يمنع الموقع الطلبات الآلية.",
        "invalid": "أدخل رابط HTTP أو HTTPS عامًا وصحيحًا.",
        "loading": "جارٍ التحليل…",
        "chart_bars": "ملخص الفحوصات",
        "chart_donut": "توزيع النتائج",
        "chart_radar": "فئات SEO",
        "chart_gauge": "نتيجة الفحص",
        "priority_high": "أولوية مرتفعة",
        "priority_medium": "أولوية متوسطة",
        "priority_low": "أولوية منخفضة",
        "footer": "يوفر EAQ SEO Audit إرشادات تقنية ولا يضمن ترتيبًا معينًا في نتائج البحث.",
        "save": "تُحفظ التقارير تلقائيًا.",
        "business_name": "اسم النشاط",
        "phone": "الهاتف",
        "email": "البريد الإلكتروني",
        "website_field": "الموقع",
        "no_title": "لم يُكتشف عنوان للصفحة.",
        "no_description": "لم يُكتشف وصف تعريفي.",
        "no_h1": "لم يُكتشف عنوان H1.",
        "long_title": "عنوان الصفحة طويل بشكل ملحوظ.",
        "short_title": "العنوان قصير؛ فكّر في وصف الصفحة بشكل أوضح.",
        "long_desc": "الوصف التعريفي طويل.",
        "short_desc": "الوصف التعريفي قصير.",
        "images_missing": "بعض الصور لا تحتوي على خاصية alt.",
        "multiple_h1": "تم اكتشاف عدة عناوين H1؛ راجع بنية الصفحة.",
        "no_canonical": "لم يُكتشف رابط Canonical.",
        "no_viewport": "إعداد عرض الهاتف مفقود.",
        "no_lang": "خاصية lang غير موجودة في HTML.",
        "no_schema": "لم يتم اكتشاف بيانات منظمة بصيغة JSON-LD.",
        "no_social": "بيانات Open Graph أو المشاركة الاجتماعية محدودة أو مفقودة.",
        "no_https": "الرابط المُدخل لا يستخدم HTTPS.",
        "no_robots": "لم يتم اكتشاف توجيه robots؛ وهذا ليس خطأ بالضرورة.",
        "no_business": "لم تُكتشف بيانات نشاط تجاري واضحة في بيانات الصفحة.",
        "site_external": "روابط خارجية",
        "site_internal": "روابط داخلية",
        "indexable": "توجيهات الفهرسة",
        "report_id": "رقم التقرير",
        "language": "اللغة",
        "pdf_tip": "من نافذة الطباعة اختر «حفظ بصيغة PDF».",
        "security": "الأمان والخصوصية",
        "privacy_note": "يجلب الفحص الصفحة العامة من الخادم. لا ترسل روابط خاصة أو صفحات تتطلب تسجيل الدخول.",
    },
    "fr": {
        "brand": "EAQ SEO Audit",
        "tagline": "Analyser. Automatiser. Améliorer.",
        "heading": "Comprenez la santé SEO de votre site",
        "intro": "Liste de contrôles techniques et de contenu accessibles publiquement.",
        "url": "URL du site",
        "audit": "Analyser le site",
        "placeholder": "https://example.com",
        "results": "Rapport d'audit",
        "overall": "Score de la liste de contrôle",
        "not_rank": "Ce score n'est pas un classement Google.",
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
        "print": "Imprimer / Enregistrer en PDF",
        "back": "Nouvel audit",
        "title": "Titre de la page",
        "description": "Méta-description",
        "canonical": "URL canonique",
        "headings": "Structure des titres",
        "images": "Textes alternatifs des images",
        "links": "Liens",
        "https": "HTTPS",
        "robots": "Directive robots",
        "viewport": "Affichage mobile",
        "lang": "Langue HTML",
        "schema": "Données structurées",
        "social": "Métadonnées sociales",
        "business": "Informations de l'entreprise",
        "yes": "Détecté",
        "no": "Absent ou à vérifier",
        "warning": "Vérification recommandée",
        "good": "Semble correct",
        "missing": "Non détecté",
        "not_measured": "Non mesuré",
        "speed_note": "La vitesse et les Core Web Vitals n'ont pas été mesurés.",
        "business_note": "Les informations commerciales proviennent uniquement des métadonnées détectées.",
        "location": "Adresse publiée",
        "map": "Rechercher l'adresse sur la carte",
        "no_address": "Aucune adresse publiée détectée.",
        "error": "Impossible d'analyser cette URL.",
        "error_detail": "Vérifiez l'adresse. Le site peut bloquer les requêtes automatisées.",
        "invalid": "Saisissez une URL publique HTTP ou HTTPS valide.",
        "loading": "Analyse en cours…",
        "chart_bars": "Résumé des contrôles",
        "chart_donut": "Répartition des résultats",
        "chart_radar": "Catégories SEO",
        "chart_gauge": "Score de contrôle",
        "priority_high": "Priorité élevée",
        "priority_medium": "Priorité moyenne",
        "priority_low": "Priorité faible",
        "footer": "EAQ SEO Audit fournit des conseils techniques sans garantir le classement.",
        "save": "Les rapports sont enregistrés automatiquement.",
        "business_name": "Nom de l'entreprise",
        "phone": "Téléphone",
        "email": "E-mail",
        "website_field": "Site web",
        "no_title": "Aucun titre détecté.",
        "no_description": "Aucune méta-description détectée.",
        "no_h1": "Aucun titre H1 détecté.",
        "long_title": "Le titre est particulièrement long.",
        "short_title": "Le titre est court.",
        "long_desc": "La méta-description est longue.",
        "short_desc": "La méta-description est courte.",
        "images_missing": "Certaines images n'ont pas d'attribut alt.",
        "multiple_h1": "Plusieurs titres H1 détectés.",
        "no_canonical": "Aucun lien canonique détecté.",
        "no_viewport": "La configuration mobile est absente.",
        "no_lang": "L'attribut lang est absent.",
        "no_schema": "Aucune donnée JSON-LD détectée.",
        "no_social": "Les métadonnées sociales sont limitées ou absentes.",
        "no_https": "L'URL n'utilise pas HTTPS.",
        "no_robots": "Aucune directive robots détectée; ce n'est pas nécessairement une erreur.",
        "no_business": "Aucune information commerciale claire détectée.",
        "site_external": "Liens externes",
        "site_internal": "Liens internes",
        "indexable": "Directives d'indexation",
        "report_id": "Rapport",
        "language": "Langue",
        "pdf_tip": "Dans la boîte d'impression, choisissez « Enregistrer au format PDF ».",
        "security": "Sécurité et confidentialité",
        "privacy_note": "N'envoyez pas d'URL privées ni de pages nécessitant une authentification.",
    },
    "es": {
        "brand": "EAQ SEO Audit",
        "tagline": "Analiza. Automatiza. Mejora.",
        "heading": "Comprende la salud SEO de tu sitio",
        "intro": "Lista de comprobaciones técnicas y de contenido público.",
        "url": "URL del sitio",
        "audit": "Analizar sitio",
        "placeholder": "https://example.com",
        "results": "Informe de auditoría",
        "overall": "Puntuación de comprobación",
        "not_rank": "No es una clasificación de Google.",
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
        "print": "Imprimir / Guardar PDF",
        "back": "Nueva auditoría",
        "title": "Título de página",
        "description": "Meta descripción",
        "canonical": "URL canónica",
        "headings": "Estructura de encabezados",
        "images": "Texto alternativo de imágenes",
        "links": "Enlaces",
        "https": "HTTPS",
        "robots": "Directiva robots",
        "viewport": "Vista móvil",
        "lang": "Idioma HTML",
        "schema": "Datos estructurados",
        "social": "Metadatos sociales",
        "business": "Información comercial",
        "yes": "Detectado",
        "no": "Falta o revisar",
        "warning": "Se recomienda revisar",
        "good": "Parece correcto",
        "missing": "No detectado",
        "not_measured": "No medido",
        "speed_note": "No se midieron la velocidad ni los Core Web Vitals.",
        "business_note": "Los datos comerciales solo se muestran si se detectan en los metadatos.",
        "location": "Dirección publicada",
        "map": "Buscar dirección en el mapa",
        "no_address": "No se detectó una dirección publicada.",
        "error": "No se pudo analizar esta URL.",
        "error_detail": "Comprueba la dirección; el sitio podría bloquear solicitudes automatizadas.",
        "invalid": "Introduce una URL pública HTTP o HTTPS válida.",
        "loading": "Analizando…",
        "chart_bars": "Resumen de comprobaciones",
        "chart_donut": "Distribución de resultados",
        "chart_radar": "Categorías SEO",
        "chart_gauge": "Puntuación",
        "priority_high": "Prioridad alta",
        "priority_medium": "Prioridad media",
        "priority_low": "Prioridad baja",
        "footer": "EAQ SEO Audit ofrece orientación técnica, no garantiza posiciones.",
        "save": "Los informes se guardan automáticamente.",
        "business_name": "Nombre comercial",
        "phone": "Teléfono",
        "email": "Correo electrónico",
        "website_field": "Sitio web",
        "no_title": "No se detectó título.",
        "no_description": "No se detectó meta descripción.",
        "no_h1": "No se detectó encabezado H1.",
        "long_title": "El título es muy largo.",
        "short_title": "El título es corto.",
        "long_desc": "La meta descripción es larga.",
        "short_desc": "La meta descripción es corta.",
        "images_missing": "Algunas imágenes no tienen atributo alt.",
        "multiple_h1": "Se detectaron varios encabezados H1.",
        "no_canonical": "No se detectó URL canónica.",
        "no_viewport": "Falta la configuración móvil.",
        "no_lang": "Falta el atributo lang.",
        "no_schema": "No se detectaron datos JSON-LD.",
        "no_social": "Los metadatos sociales son limitados o faltan.",
        "no_https": "La URL no utiliza HTTPS.",
        "no_robots": "No se detectó directiva robots; no siempre es un error.",
        "no_business": "No se detectó información comercial clara.",
        "site_external": "Enlaces externos",
        "site_internal": "Enlaces internos",
        "indexable": "Directivas de indexación",
        "report_id": "Informe",
        "language": "Idioma",
        "pdf_tip": "En la ventana de impresión, elige «Guardar como PDF».",
        "security": "Seguridad y privacidad",
        "privacy_note": "No envíes URL privadas ni páginas que requieran autenticación.",
    },
    "de": {
        "brand": "EAQ SEO Audit",
        "tagline": "Analysieren. Automatisieren. Verbessern.",
        "heading": "Verstehen Sie den SEO-Zustand Ihrer Website",
        "intro": "Technische und inhaltliche Prüfungen öffentlich zugänglicher Seiten.",
        "url": "Website-URL",
        "audit": "Website analysieren",
        "placeholder": "https://example.com",
        "results": "Prüfbericht",
        "overall": "Prüfpunktzahl",
        "not_rank": "Dies ist kein Google-Ranking.",
        "passed": "Bestandene Prüfungen",
        "issues": "Verbesserungspunkte",
        "details": "Detaillierte Ergebnisse",
        "priorities": "Empfohlene Prioritäten",
        "history": "Gespeicherte Berichte",
        "no_history": "Noch keine Berichte gespeichert.",
        "date": "Datum",
        "website": "Website",
        "score": "Punktzahl",
        "actions": "Aktionen",
        "view": "Ansehen",
        "delete": "Löschen",
        "print": "Drucken / Als PDF speichern",
        "back": "Neue Prüfung",
        "title": "Seitentitel",
        "description": "Meta-Beschreibung",
        "canonical": "Kanonische URL",
        "headings": "Überschriftenstruktur",
        "images": "Alternativtexte der Bilder",
        "links": "Links",
        "https": "HTTPS",
        "robots": "Robots-Direktive",
        "viewport": "Mobile Ansicht",
        "lang": "HTML-Sprache",
        "schema": "Strukturierte Daten",
        "social": "Social-Media-Metadaten",
        "business": "Unternehmensinformationen",
        "yes": "Gefunden",
        "no": "Fehlt oder prüfen",
        "warning": "Prüfung empfohlen",
        "good": "Sieht gut aus",
        "missing": "Nicht gefunden",
        "not_measured": "Nicht gemessen",
        "speed_note": "Seitengeschwindigkeit und Core Web Vitals wurden nicht gemessen.",
        "business_note": "Unternehmensdaten werden nur aus erkannten Seitenmetadaten übernommen.",
        "location": "Veröffentlichte Geschäftsadresse",
        "map": "Adresse auf der Karte suchen",
        "no_address": "Keine veröffentlichte Adresse erkannt.",
        "error": "Diese URL konnte nicht geprüft werden.",
        "error_detail": "URL prüfen; die Website blockiert möglicherweise automatisierte Anfragen.",
        "invalid": "Gültige öffentliche HTTP- oder HTTPS-URL eingeben.",
        "loading": "Analyse läuft…",
        "chart_bars": "Prüfübersicht",
        "chart_donut": "Ergebnisverteilung",
        "chart_radar": "SEO-Kategorien",
        "chart_gauge": "Prüfpunktzahl",
        "priority_high": "Hohe Priorität",
        "priority_medium": "Mittlere Priorität",
        "priority_low": "Niedrige Priorität",
        "footer": "EAQ SEO Audit bietet technische Hinweise und garantiert keine Rankings.",
        "save": "Berichte werden automatisch gespeichert.",
        "business_name": "Unternehmensname",
        "phone": "Telefon",
        "email": "E-Mail",
        "website_field": "Website",
        "no_title": "Kein Seitentitel erkannt.",
        "no_description": "Keine Meta-Beschreibung erkannt.",
        "no_h1": "Keine H1-Überschrift erkannt.",
        "long_title": "Der Titel ist ungewöhnlich lang.",
        "short_title": "Der Titel ist kurz.",
        "long_desc": "Die Meta-Beschreibung ist lang.",
        "short_desc": "Die Meta-Beschreibung ist kurz.",
        "images_missing": "Einige Bilder haben kein alt-Attribut.",
        "multiple_h1": "Mehrere H1-Überschriften erkannt.",
        "no_canonical": "Keine kanonische URL erkannt.",
        "no_viewport": "Mobile Viewport-Einstellung fehlt.",
        "no_lang": "HTML-lang-Attribut fehlt.",
        "no_schema": "Keine JSON-LD-Daten erkannt.",
        "no_social": "Social-Metadaten fehlen oder sind begrenzt.",
        "no_https": "Die URL verwendet kein HTTPS.",
        "no_robots": "Keine robots-Direktive erkannt; das ist nicht immer ein Fehler.",
        "no_business": "Keine eindeutigen Unternehmensdaten erkannt.",
        "site_external": "Externe Links",
        "site_internal": "Interne Links",
        "indexable": "Indexierungsdirektiven",
        "report_id": "Bericht",
        "language": "Sprache",
        "pdf_tip": "Im Druckdialog «Als PDF speichern» auswählen.",
        "security": "Sicherheit und Datenschutz",
        "privacy_note": "Keine privaten URLs oder Anmeldeseiten übermitteln.",
    },
    "hi": {
        "brand": "EAQ SEO Audit",
        "tagline": "विश्लेषण करें। स्वचालित करें। सुधारें।",
        "heading": "अपनी वेबसाइट की SEO स्थिति समझें",
        "intro": "सार्वजनिक पेज के तकनीकी और सामग्री संबंधी परीक्षण।",
        "url": "वेबसाइट URL",
        "audit": "वेबसाइट का विश्लेषण करें",
        "placeholder": "https://example.com",
        "results": "ऑडिट रिपोर्ट",
        "overall": "जाँच स्कोर",
        "not_rank": "यह Google रैंकिंग स्कोर नहीं है।",
        "passed": "सफल जाँच",
        "issues": "सुधार के बिंदु",
        "details": "विस्तृत परिणाम",
        "priorities": "सुझाई गई प्राथमिकताएँ",
        "history": "सहेजी गई रिपोर्ट",
        "no_history": "अभी कोई रिपोर्ट नहीं है।",
        "date": "तारीख",
        "website": "वेबसाइट",
        "score": "स्कोर",
        "actions": "कार्रवाई",
        "view": "देखें",
        "delete": "हटाएँ",
        "print": "प्रिंट / PDF सहेजें",
        "back": "नई जाँच",
        "title": "पेज शीर्षक",
        "description": "मेटा विवरण",
        "canonical": "Canonical URL",
        "headings": "शीर्षक संरचना",
        "images": "इमेज alt टेक्स्ट",
        "links": "लिंक",
        "https": "HTTPS",
        "robots": "Robots निर्देश",
        "viewport": "मोबाइल व्यू",
        "lang": "HTML भाषा",
        "schema": "संरचित डेटा",
        "social": "सोशल मेटाडेटा",
        "business": "व्यावसायिक जानकारी",
        "yes": "मिला",
        "no": "अनुपस्थित या जाँचें",
        "warning": "जाँच की सलाह",
        "good": "ठीक लगता है",
        "missing": "नहीं मिला",
        "not_measured": "मापा नहीं गया",
        "speed_note": "पेज गति और Core Web Vitals नहीं मापे गए।",
        "business_note": "व्यावसायिक विवरण केवल पेज मेटाडेटा में मिलने पर दिखाए जाते हैं।",
        "location": "प्रकाशित व्यावसायिक पता",
        "map": "मानचित्र पर पता खोजें",
        "no_address": "कोई प्रकाशित पता नहीं मिला।",
        "error": "इस URL का विश्लेषण नहीं हो सका।",
        "error_detail": "URL जाँचें; वेबसाइट स्वचालित अनुरोध रोक सकती है।",
        "invalid": "मान्य सार्वजनिक HTTP या HTTPS URL दर्ज करें।",
        "loading": "विश्लेषण जारी है…",
        "chart_bars": "जाँच सारांश",
        "chart_donut": "परिणाम वितरण",
        "chart_radar": "SEO श्रेणियाँ",
        "chart_gauge": "जाँच स्कोर",
        "priority_high": "उच्च प्राथमिकता",
        "priority_medium": "मध्यम प्राथमिकता",
        "priority_low": "कम प्राथमिकता",
        "footer": "यह तकनीकी मार्गदर्शन है, रैंकिंग की गारंटी नहीं।",
        "save": "रिपोर्ट स्वतः सहेजी जाती हैं।",
        "business_name": "व्यवसाय का नाम",
        "phone": "फ़ोन",
        "email": "ईमेल",
        "website_field": "वेबसाइट",
        "no_title": "पेज शीर्षक नहीं मिला।",
        "no_description": "मेटा विवरण नहीं मिला।",
        "no_h1": "H1 शीर्षक नहीं मिला।",
        "long_title": "शीर्षक बहुत लंबा है।",
        "short_title": "शीर्षक छोटा है।",
        "long_desc": "मेटा विवरण लंबा है।",
        "short_desc": "मेटा विवरण छोटा है।",
        "images_missing": "कुछ चित्रों में alt विशेषता नहीं है।",
        "multiple_h1": "कई H1 शीर्षक मिले।",
        "no_canonical": "Canonical लिंक नहीं मिला।",
        "no_viewport": "मोबाइल viewport सेटिंग नहीं है।",
        "no_lang": "HTML lang विशेषता नहीं है।",
        "no_schema": "JSON-LD डेटा नहीं मिला।",
        "no_social": "सोशल मेटाडेटा सीमित या अनुपस्थित है।",
        "no_https": "URL HTTPS का उपयोग नहीं करता।",
        "no_robots": "Robots निर्देश नहीं मिला; यह हमेशा त्रुटि नहीं है।",
        "no_business": "स्पष्ट व्यावसायिक जानकारी नहीं मिली।",
        "site_external": "बाहरी लिंक",
        "site_internal": "आंतरिक लिंक",
        "indexable": "इंडेक्सिंग निर्देश",
        "report_id": "रिपोर्ट",
        "language": "भाषा",
        "pdf_tip": "प्रिंट विंडो में “Save as PDF” चुनें।",
        "security": "सुरक्षा और गोपनीयता",
        "privacy_note": "निजी URL या लॉगिन आवश्यक पेज न भेजें।",
    },
    "tr": {
        "brand": "EAQ SEO Audit",
        "tagline": "Analiz et. Otomatikleştir. Geliştir.",
        "heading": "Web sitenizin SEO durumunu anlayın",
        "intro": "Herkese açık sayfalar için teknik ve içerik kontrolleri.",
        "url": "Web sitesi URL'si",
        "audit": "Siteyi analiz et",
        "placeholder": "https://example.com",
        "results": "Denetim raporu",
        "overall": "Kontrol puanı",
        "not_rank": "Bu bir Google sıralama puanı değildir.",
        "passed": "Başarılı kontroller",
        "issues": "İyileştirme alanları",
        "details": "Ayrıntılı bulgular",
        "priorities": "Önerilen öncelikler",
        "history": "Kaydedilen raporlar",
        "no_history": "Henüz rapor yok.",
        "date": "Tarih",
        "website": "Web sitesi",
        "score": "Puan",
        "actions": "İşlemler",
        "view": "Görüntüle",
        "delete": "Sil",
        "print": "Yazdır / PDF kaydet",
        "back": "Yeni denetim",
        "title": "Sayfa başlığı",
        "description": "Meta açıklama",
        "canonical": "Canonical URL",
        "headings": "Başlık yapısı",
        "images": "Görsel alt metni",
        "links": "Bağlantılar",
        "https": "HTTPS",
        "robots": "Robots yönergesi",
        "viewport": "Mobil görünüm",
        "lang": "HTML dili",
        "schema": "Yapılandırılmış veri",
        "social": "Sosyal meta verileri",
        "business": "İşletme bilgileri",
        "yes": "Bulundu",
        "no": "Eksik veya incelenmeli",
        "warning": "İnceleme önerilir",
        "good": "İyi görünüyor",
        "missing": "Bulunamadı",
        "not_measured": "Ölçülmedi",
        "speed_note": "Sayfa hızı ve Core Web Vitals ölçülmedi.",
        "business_note": "İşletme bilgileri yalnızca sayfa meta verilerinden alınır.",
        "location": "Yayımlanmış işletme adresi",
        "map": "Adresi haritada ara",
        "no_address": "Yayımlanmış adres bulunamadı.",
        "error": "URL analiz edilemedi.",
        "error_detail": "Adresi kontrol edin; site otomatik istekleri engelliyor olabilir.",
        "invalid": "Geçerli bir herkese açık HTTP veya HTTPS URL'si girin.",
        "loading": "Analiz ediliyor…",
        "chart_bars": "Kontrol özeti",
        "chart_donut": "Sonuç dağılımı",
        "chart_radar": "SEO kategorileri",
        "chart_gauge": "Kontrol puanı",
        "priority_high": "Yüksek öncelik",
        "priority_medium": "Orta öncelik",
        "priority_low": "Düşük öncelik",
        "footer": "Teknik rehberlik sağlar; sıralama garantisi vermez.",
        "save": "Raporlar otomatik kaydedilir.",
        "business_name": "İşletme adı",
        "phone": "Telefon",
        "email": "E-posta",
        "website_field": "Web sitesi",
        "no_title": "Sayfa başlığı bulunamadı.",
        "no_description": "Meta açıklama bulunamadı.",
        "no_h1": "H1 başlığı bulunamadı.",
        "long_title": "Başlık oldukça uzun.",
        "short_title": "Başlık kısa.",
        "long_desc": "Meta açıklama uzun.",
        "short_desc": "Meta açıklama kısa.",
        "images_missing": "Bazı görsellerde alt özelliği yok.",
        "multiple_h1": "Birden fazla H1 başlığı bulundu.",
        "no_canonical": "Canonical bağlantısı bulunamadı.",
        "no_viewport": "Mobil viewport ayarı eksik.",
        "no_lang": "HTML lang özelliği eksik.",
        "no_schema": "JSON-LD verisi bulunamadı.",
        "no_social": "Sosyal meta verileri eksik veya sınırlı.",
        "no_https": "URL HTTPS kullanmıyor.",
        "no_robots": "Robots yönergesi bulunamadı; bu her zaman hata değildir.",
        "no_business": "Açık işletme bilgisi bulunamadı.",
        "site_external": "Harici bağlantılar",
        "site_internal": "Dahili bağlantılar",
        "indexable": "Dizinleme yönergeleri",
        "report_id": "Rapor",
        "language": "Dil",
        "pdf_tip": "Yazdırma penceresinde “PDF olarak kaydet” seçeneğini seçin.",
        "security": "Güvenlik ve gizlilik",
        "privacy_note": "Özel URL'ler veya giriş gerektiren sayfalar göndermeyin.",
    },
    "zh": {
        "brand": "EAQ SEO Audit",
        "tagline": "分析。自动化。改进。",
        "heading": "了解网站的 SEO 状况",
        "intro": "检查公开网页的技术和内容项目。",
        "url": "网站 URL",
        "audit": "分析网站",
        "placeholder": "https://example.com",
        "results": "审计报告",
        "overall": "检查清单得分",
        "not_rank": "此分数不是 Google 排名。",
        "passed": "通过的检查",
        "issues": "需要改进的项目",
        "details": "详细结果",
        "priorities": "建议优先事项",
        "history": "已保存报告",
        "no_history": "暂无保存的报告。",
        "date": "日期",
        "website": "网站",
        "score": "得分",
        "actions": "操作",
        "view": "查看",
        "delete": "删除",
        "print": "打印 / 保存 PDF",
        "back": "新建审计",
        "title": "页面标题",
        "description": "元描述",
        "canonical": "规范网址",
        "headings": "标题结构",
        "images": "图片替代文本",
        "links": "链接",
        "https": "HTTPS",
        "robots": "Robots 指令",
        "viewport": "移动端视口",
        "lang": "HTML 语言",
        "schema": "结构化数据",
        "social": "社交分享元数据",
        "business": "企业信息",
        "yes": "已检测",
        "no": "缺失或需检查",
        "warning": "建议检查",
        "good": "看起来正常",
        "missing": "未检测到",
        "not_measured": "未测量",
        "speed_note": "本审计未测量页面速度或 Core Web Vitals。",
        "business_note": "企业信息仅来自页面元数据或结构化数据。",
        "location": "公开的企业地址",
        "map": "在地图中搜索地址",
        "no_address": "未检测到公开地址。",
        "error": "无法审计此 URL。",
        "error_detail": "请检查地址；网站可能阻止自动请求。",
        "invalid": "请输入有效的公开 HTTP 或 HTTPS URL。",
        "loading": "正在分析…",
        "chart_bars": "检查摘要",
        "chart_donut": "结果分布",
        "chart_radar": "SEO 类别",
        "chart_gauge": "检查得分",
        "priority_high": "高优先级",
        "priority_medium": "中优先级",
        "priority_low": "低优先级",
        "footer": "提供技术建议，不保证搜索排名。",
        "save": "报告会自动保存。",
        "business_name": "企业名称",
        "phone": "电话",
        "email": "电子邮件",
        "website_field": "网站",
        "no_title": "未检测到页面标题。",
        "no_description": "未检测到元描述。",
        "no_h1": "未检测到 H1 标题。",
        "long_title": "页面标题过长。",
        "short_title": "页面标题较短。",
        "long_desc": "元描述较长。",
        "short_desc": "元描述较短。",
        "images_missing": "部分图片缺少 alt 属性。",
        "multiple_h1": "检测到多个 H1 标题。",
        "no_canonical": "未检测到规范网址。",
        "no_viewport": "缺少移动端视口设置。",
        "no_lang": "缺少 HTML lang 属性。",
        "no_schema": "未检测到 JSON-LD 数据。",
        "no_social": "社交元数据缺失或有限。",
        "no_https": "该 URL 未使用 HTTPS。",
        "no_robots": "未检测到 robots 指令；这不一定是错误。",
        "no_business": "未检测到明确的企业信息。",
        "site_external": "外部链接",
        "site_internal": "内部链接",
        "indexable": "索引指令",
        "report_id": "报告",
        "language": "语言",
        "pdf_tip": "在打印窗口中选择“另存为 PDF”。",
        "security": "安全与隐私",
        "privacy_note": "请勿提交私有 URL 或需要身份验证的页面。",
    },
}

LANGUAGES = {
    "en": "English",
    "ar": "العربية",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
    "hi": "हिन्दी",
    "tr": "Türkçe",
    "zh": "中文",
}


def tr(lang, key):
    lang = lang if lang in TRANSLATIONS else "en"
    return TRANSLATIONS.get(lang, {}).get(
        key, TRANSLATIONS["en"].get(key, key)
    )


# ------------------------------------------------------------
# URL validation and SSRF protections
# ------------------------------------------------------------

def is_public_ip(address):
    try:
        ip = ipaddress.ip_address(address)
        return (
            ip.is_global
            and not ip.is_private
            and not ip.is_loopback
            and not ip.is_link_local
            and not ip.is_multicast
            and not ip.is_reserved
            and not ip.is_unspecified
        )
    except ValueError:
        return False


def validate_public_url(raw_url):
    if not raw_url or len(raw_url) > MAX_URL_LENGTH:
        raise ValueError("invalid_url")

    raw_url = raw_url.strip()
    parsed = urlparse(raw_url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError("invalid_url")

    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("invalid_url")

    host = parsed.hostname.lower().rstrip(".")

    if host in ("localhost",) or host.endswith(".localhost"):
        raise ValueError("private_host")

    if host.endswith(".local") or host.endswith(".internal"):
        raise ValueError("private_host")

    # Disallow IP-literal URLs; public DNS hostnames are required.
    try:
        ipaddress.ip_address(host)
        raise ValueError("ip_literal_not_allowed")
    except ValueError as exc:
        if str(exc) == "ip_literal_not_allowed":
            raise

    try:
        records = socket.getaddrinfo(
            host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM
        )
    except socket.gaierror:
        raise ValueError("dns_failed")

    addresses = set()
    for record in records:
        address = record[4][0]
        if not is_public_ip(address):
            raise ValueError("private_host")
        addresses.add(address)

    if not addresses:
        raise ValueError("dns_failed")

    return raw_url


def fetch_public_page(raw_url):
    """
    Revalidate every redirect target. Redirects are followed manually.
    The final connection still uses normal TLS certificate validation.
    """
    current = validate_public_url(raw_url)

    headers = {
        "User-Agent": "EAQSEOAudit/1.0 (+public-page technical audit)",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
        "Accept-Encoding": "identity",
    }

    session = requests.Session()
    session.trust_env = False

    try:
        for _ in range(6):
            validate_public_url(current)

            with session.get(
                current,
                headers=headers,
                timeout=(5, REQUEST_TIMEOUT),
                allow_redirects=False,
                stream=True,
                verify=True
            ) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        raise ValueError("redirect_without_location")
                    current = urljoin(current, location)
                    continue

                response.raise_for_status()

                content_type = response.headers.get(
                    "Content-Type", ""
                ).lower()

                if (
                    "text/html" not in content_type
                    and "application/xhtml+xml" not in content_type
                ):
                    raise ValueError("not_html")

                declared_size = response.headers.get("Content-Length")
                if declared_size:
                    try:
                        if int(declared_size) > MAX_HTML_BYTES:
                            raise ValueError("page_too_large")
                    except ValueError as exc:
                        if str(exc) == "page_too_large":
                            raise

                chunks = []
                total = 0
                for chunk in response.iter_content(chunk_size=16384):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_HTML_BYTES:
                        raise ValueError("page_too_large")
                    chunks.append(chunk)

                encoding = response.encoding or "utf-8"
                html = b"".join(chunks).decode(
                    encoding, errors="replace"
                )

                return {
                    "url": current,
                    "status": response.status_code,
                    "html": html,
                    "content_type": content_type,
                }

        raise ValueError("too_many_redirects")
    finally:
        session.close()


# ------------------------------------------------------------
# HTML and SEO audit
# ------------------------------------------------------------

def text_content(node):
    if not node:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def meta_content(soup, *names):
    for name in names:
        node = soup.find(
            "meta",
            attrs={"name": re.compile("^" + re.escape(name) + "$", re.I)}
        )
        if node and node.get("content"):
            return node.get("content", "").strip()

        node = soup.find(
            "meta",
            attrs={"property": re.compile("^" + re.escape(name) + "$", re.I)}
        )
        if node and node.get("content"):
            return node.get("content", "").strip()

    return ""


def extract_business(soup, page_url):
    result = {
        "name": "",
        "address": "",
        "phone": "",
        "email": "",
        "website": "",
    }

    # Read business details only from actual structured data.
    for script in soup.find_all(
        "script", attrs={"type": re.compile("application/ld\\+json", re.I)}
    ):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        queue = data if isinstance(data, list) else [data]

        while queue:
            item = queue.pop(0)
            if not isinstance(item, dict):
                continue

            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)

            item_type = item.get("@type", "")
            if isinstance(item_type, list):
                types = " ".join(str(x) for x in item_type).lower()
            else:
                types = str(item_type).lower()

            if any(
                word in types
                for word in (
                    "organization", "localbusiness", "store",
                    "professionalservice", "corporation",
                    "medicalbusiness", "restaurant"
                )
            ):
                if not result["name"] and isinstance(item.get("name"), str):
                    result["name"] = item["name"][:250]

                if not result["phone"] and isinstance(item.get("telephone"), str):
                    result["phone"] = item["telephone"][:100]

                if not result["email"] and isinstance(item.get("email"), str):
                    result["email"] = item["email"][:250]

                address = item.get("address")
                if isinstance(address, str) and not result["address"]:
                    result["address"] = address[:500]
                elif isinstance(address, dict) and not result["address"]:
                    parts = []
                    for key in (
                        "streetAddress", "addressLocality",
                        "addressRegion", "postalCode", "addressCountry"
                    ):
                        value = address.get(key)
                        if isinstance(value, str) and value.strip():
                            parts.append(value.strip())
                    result["address"] = ", ".join(parts)[:500]

                website = item.get("url")
                if isinstance(website, str) and website.startswith(("http://", "https://")):
                    result["website"] = website[:500]

    if not result["name"]:
        org = meta_content(soup, "og:site_name")
        if org:
            result["name"] = org[:250]

    # Do not infer an address from the website URL.
    return result


def check_item(key, ok, details="", priority="medium"):
    return {
        "key": key,
        "ok": bool(ok),
        "details": details,
        "priority": priority,
    }


def audit_html(page_url, html, status):
    soup = BeautifulSoup(html, "html.parser")

    title_node = soup.find("title")
    title = text_content(title_node)
    description = meta_content(soup, "description")
    canonical_node = soup.find(
        "link",
        attrs={"rel": lambda value: value and "canonical" in [
            x.lower() for x in (
                value if isinstance(value, list) else str(value).split()
            )
        ]}
    )
    canonical = canonical_node.get("href", "").strip() if canonical_node else ""

    h1_nodes = soup.find_all("h1")
    images = soup.find_all("img")
    images_without_alt = [
        image for image in images if image.get("alt") is None
    ]

    viewport = soup.find(
        "meta", attrs={"name": re.compile("^viewport$", re.I)}
    )
    html_node = soup.find("html")
    html_lang = html_node.get("lang", "").strip() if html_node else ""
    robots = meta_content(soup, "robots", "googlebot")

    json_ld = soup.find(
        "script", attrs={"type": re.compile("application/ld\\+json", re.I)}
    )

    og_title = meta_content(soup, "og:title")
    og_description = meta_content(soup, "og:description")
    og_image = meta_content(soup, "og:image")
    twitter_card = meta_content(soup, "twitter:card")

    page_host = (urlparse(page_url).hostname or "").lower()
    internal_links = 0
    external_links = 0

    for node in soup.find_all("a", href=True):
        href = node.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(page_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            continue
        if parsed.hostname.lower() == page_host:
            internal_links += 1
        else:
            external_links += 1

    business = extract_business(soup, page_url)

    checks = []

    checks.append(check_item(
        "title",
        bool(title) and 10 <= len(title) <= 60,
        f"{len(title)} characters" if title else "",
        "high"
    ))

    checks.append(check_item(
        "description",
        bool(description) and 70 <= len(description) <= 160,
        f"{len(description)} characters" if description else "",
        "high"
    ))

    checks.append(check_item(
        "canonical", bool(canonical),
        canonical[:300], "medium"
    ))

    checks.append(check_item(
        "headings", len(h1_nodes) == 1,
        f"{len(h1_nodes)} H1 headings", "medium"
    ))

    checks.append(check_item(
        "images", len(images_without_alt) == 0,
        f"{len(images_without_alt)} of {len(images)} images lack alt",
        "medium"
    ))

    checks.append(check_item(
        "https", urlparse(page_url).scheme == "https",
        urlparse(page_url).scheme.upper(), "high"
    ))

    checks.append(check_item(
        "viewport", bool(viewport),
        viewport.get("content", "")[:200] if viewport else "",
        "high"
    ))

    checks.append(check_item(
        "lang", bool(html_lang),
        html_lang, "low"
    ))

    checks.append(check_item(
        "schema", bool(json_ld),
        "JSON-LD detected" if json_ld else "",
        "medium"
    ))

    checks.append(check_item(
        "social",
        bool(og_title or og_description or og_image or twitter_card),
        "Open Graph / Twitter metadata", "low"
    ))

    checks.append(check_item(
        "robots", True,
        robots or "No robots meta directive detected",
        "low"
    ))

    checks.append(check_item(
        "links", internal_links > 0,
        f"{internal_links} internal, {external_links} external",
        "low"
    ))

    total = len(checks)
    passed = sum(1 for item in checks if item["ok"])
    score = round((passed / total) * 100) if total else 0

    priorities = []
    for item in checks:
        if item["ok"]:
            continue
        priorities.append({
            "key": item["key"],
            "priority": item["priority"],
            "details": item["details"],
        })

    priority_order = {"high": 0, "medium": 1, "low": 2}
    priorities.sort(
        key=lambda item: priority_order.get(item["priority"], 9)
    )

    categories = {
        "on_page": round(
            sum(1 for c in checks if c["key"] in
                ("title", "description", "headings") and c["ok"]) / 3 * 100
        ),
        "technical": round(
            sum(1 for c in checks if c["key"] in
                ("canonical", "https", "robots") and c["ok"]) / 3 * 100
        ),
        "mobile": round(
            sum(1 for c in checks if c["key"] in
                ("viewport", "images") and c["ok"]) / 2 * 100
        ),
        "structured_data": 100 if json_ld else 0,
        "social": 100 if (og_title or og_description or og_image or twitter_card) else 0,
    }

    return {
        "url": page_url,
        "status": status,
        "title": title,
        "description": description,
        "canonical": canonical,
        "h1_count": len(h1_nodes),
        "image_count": len(images),
        "images_missing_alt": len(images_without_alt),
        "internal_links": internal_links,
        "external_links": external_links,
        "html_lang": html_lang,
        "robots": robots,
        "business": business,
        "checks": checks,
        "score": score,
        "passed": passed,
        "total": total,
        "priorities": priorities,
        "categories": categories,
        "speed_measured": False,
    }


# ------------------------------------------------------------
# Persist and retrieve reports
# ------------------------------------------------------------

def save_report(report):
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO reports (url, title, score, report_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                report.get("url", "")[:2048],
                report.get("title", "")[:500],
                int(report.get("score", 0)),
                json.dumps(report, ensure_ascii=False),
                created,
            )
        )
        report_id = cursor.lastrowid

        conn.execute("""
            DELETE FROM reports
            WHERE id NOT IN (
                SELECT id FROM reports ORDER BY id DESC LIMIT ?
            )
        """, (MAX_HISTORY,))

        conn.commit()
        return report_id, created


def get_report(report_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM reports WHERE id = ?",
            (report_id,)
        ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["report_json"])
    except (json.JSONDecodeError, TypeError):
        return None
    data["report_id"] = row["id"]
    data["created_at"] = row["created_at"]
    return data


def get_history():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, url, title, score, created_at
            FROM reports ORDER BY id DESC LIMIT ?
            """,
            (MAX_HISTORY,)
        ).fetchall()
    return [dict(row) for row in rows]


# ------------------------------------------------------------
# SVG charts
# ------------------------------------------------------------

def svg_gauge(score):
    score = max(0, min(100, int(score)))
    radius = 70
    circumference = 2 * 3.141592653589793 * radius
    dash = circumference * score / 100
    return f"""
    <svg viewBox="0 0 180 125" role="img" aria-label="Score {score}">
      <circle cx="90" cy="76" r="{radius}" fill="none"
        stroke="#e5eaf1" stroke-width="13"
        stroke-dasharray="{circumference * 0.75} {circumference}"
        transform="rotate(135 90 76)" stroke-linecap="round"/>
      <circle cx="90" cy="76" r="{radius}" fill="none"
        stroke="#2563eb" stroke-width="13"
        stroke-dasharray="{dash * 0.75} {circumference}"
        transform="rotate(135 90 76)" stroke-linecap="round"/>
      <text x="90" y="78" text-anchor="middle" font-size="31"
        font-weight="700" fill="#172033">{score}</text>
      <text x="90" y="101" text-anchor="middle" font-size="11"
        fill="#64748b">/ 100</text>
    </svg>
    """


def svg_donut(passed, total):
    failed = max(0, total - passed)
    if total <= 0:
        total = 1
    percent = passed / total
    circumference = 2 * 3.141592653589793 * 44
    dash = circumference * percent
    return f"""
    <svg viewBox="0 0 160 130" role="img" aria-label="Check distribution">
      <circle cx="80" cy="61" r="44" fill="none"
        stroke="#fee2e2" stroke-width="15"/>
      <circle cx="80" cy="61" r="44" fill="none"
        stroke="#2563eb" stroke-width="15"
        stroke-dasharray="{dash} {circumference}"
        transform="rotate(-90 80 61)" stroke-linecap="round"/>
      <text x="80" y="59" text-anchor="middle" font-size="22"
        font-weight="700" fill="#172033">{passed}</text>
      <text x="80" y="77" text-anchor="middle" font-size="10"
        fill="#64748b">of {total}</text>
      <text x="80" y="122" text-anchor="middle" font-size="10"
        fill="#64748b">{failed} need review</text>
    </svg>
    """


def svg_bars(report):
    labels = {
        "title": "Title",
        "description": "Description",
        "canonical": "Canonical",
        "headings": "Headings",
        "images": "Images",
        "https": "HTTPS",
        "viewport": "Mobile",
        "lang": "Language",
        "schema": "Schema",
        "social": "Social",
        "robots": "Robots",
        "links": "Links",
    }
    rows = report["checks"]
    height = max(110, len(rows) * 28 + 10)
    parts = [
        f'<svg viewBox="0 0 340 {height}" role="img" aria-label="Check summary">'
    ]
    for i, item in enumerate(rows):
        y = i * 28 + 15
        label = labels.get(item["key"], item["key"])
        color = "#2563eb" if item["ok"] else "#f59e0b"
        width = 150 if item["ok"] else 35
        parts.append(
            f'<text x="4" y="{y + 10}" font-size="10" fill="#475569">{label}</text>'
            f'<rect x="115" y="{y}" width="160" height="13" rx="5" fill="#e8edf4"/>'
            f'<rect x="115" y="{y}" width="{width}" height="13" rx="5" fill="{color}"/>'
            f'<text x="284" y="{y + 10}" font-size="10" fill="#475569">'
            f'{"OK" if item["ok"] else "Review"}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def svg_radar(categories):
    items = list(categories.items())
    center_x = 120
    center_y = 100
    radius = 65
    n = max(1, len(items))
    points = []
    grid = []
    labels = []
    for level in (0.25, 0.5, 0.75, 1):
        coords = []
        for i in range(n):
            angle = -3.141592653589793 / 2 + 2 * 3.141592653589793 * i / n
            coords.append(
                f"{center_x + radius * level * __import__('math').cos(angle):.1f},"
                f"{center_y + radius * level * __import__('math').sin(angle):.1f}"
            )
        grid.append(
            '<polygon points="' + " ".join(coords) +
            '" fill="none" stroke="#e2e8f0" stroke-width="1"/>'
        )
    for i, (key, value) in enumerate(items):
        import math
        angle = -math.pi / 2 + 2 * math.pi * i / n
        x = center_x + radius * (max(0, min(100, value)) / 100) * math.cos(angle)
        y = center_y + radius * (max(0, min(100, value)) / 100) * math.sin(angle)
        points.append(f"{x:.1f},{y:.1f}")
        lx = center_x + (radius + 20) * math.cos(angle)
        ly = center_y + (radius + 20) * math.sin(angle)
        label = key.replace("_", " ")[:14]
        labels.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
            f'font-size="8" fill="#64748b">{label}</text>'
        )
    return (
        '<svg viewBox="0 0 240 200" role="img" aria-label="SEO categories">'
        + "".join(grid)
        + '<polygon points="' + " ".join(points) +
        '" fill="#93c5fd" fill-opacity=".45" stroke="#2563eb" stroke-width="2"/>'
        + "".join(labels)
        + "</svg>"
    )


# ------------------------------------------------------------
# HTML templates
# ------------------------------------------------------------

def esc(value):
    from html import escape
    return escape(str(value or ""), quote=True)


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
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>{esc(title or APP_NAME)}</title>
<style>
:root {{
  --bg:#f5f7fb; --surface:#fff; --text:#172033; --muted:#64748b;
  --border:#e4e9f1; --blue:#2563eb; --blue-dark:#1d4ed8;
  --good:#166534; --good-bg:#dcfce7; --warn:#92400e; --warn-bg:#fef3c7;
  --shadow:0 10px 35px rgba(20,35,70,.06);
}}
* {{box-sizing:border-box}}
body {{margin:0;background:var(--bg);color:var(--text);
  font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;
  line-height:1.6}}
a {{color:var(--blue);text-decoration:none}}
a:hover {{text-decoration:underline}}
button,input,select {{font:inherit}}
.topbar {{background:#101b31;color:white;padding:16px 22px}}
.topbar-inner {{max-width:1120px;margin:auto;display:flex;gap:18px;
  align-items:center;justify-content:space-between;flex-wrap:wrap}}
.logo {{font-size:19px;font-weight:800;letter-spacing:-.3px}}
.logo span {{color:#93c5fd}}
.tagline {{color:#cbd5e1;font-size:12px}}
.lang-form {{display:flex;gap:8px;align-items:center}}
.lang-form select {{background:#fff;color:#172033;border:0;border-radius:9px;padding:8px}}
.wrap {{max-width:1120px;margin:30px auto;padding:0 18px 40px}}
.hero {{background:linear-gradient(135deg,#172b4d,#1d4ed8);color:#fff;
  border-radius:20px;padding:30px;box-shadow:var(--shadow);margin-bottom:22px}}
.hero h1 {{font-size:clamp(25px,4vw,38px);line-height:1.2;margin:0 0 12px}}
.hero p {{margin:0;color:#dbeafe;max-width:720px}}
.panel {{background:var(--surface);border:1px solid var(--border);
  border-radius:16px;padding:22px;margin-bottom:20px;box-shadow:var(--shadow)}}
.panel h2 {{margin:0 0 14px;font-size:20px}}
.form-row {{display:flex;gap:10px;align-items:stretch}}
.url-input {{min-width:0;flex:1;border:1px solid #cbd5e1;border-radius:11px;
  padding:13px 14px;background:#fff;color:var(--text)}}
.btn {{display:inline-flex;justify-content:center;align-items:center;gap:8px;
  border:0;border-radius:10px;padding:12px 16px;cursor:pointer;font-weight:700}}
.btn-primary {{background:var(--blue);color:white}}
.btn-primary:hover {{background:var(--blue-dark)}}
.btn-light {{background:#edf2f9;color:#172033}}
.btn-danger {{background:#fee2e2;color:#991b1b}}
.small {{font-size:13px;color:var(--muted)}}
.grid {{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}}
.metric-grid {{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}}
.metric {{padding:18px;border:1px solid var(--border);border-radius:13px;background:#fff}}
.metric strong {{font-size:27px;display:block}}
.metric span {{font-size:13px;color:var(--muted)}}
.chart {{min-width:0;overflow:hidden}}
.chart svg {{width:100%;height:auto;max-height:320px;display:block}}
.check-list {{display:grid;gap:10px}}
.check {{display:flex;gap:12px;align-items:flex-start;padding:13px;
  border:1px solid var(--border);border-radius:12px;background:#fff}}
.check-icon {{flex:none;width:25px;height:25px;border-radius:50%;display:grid;
  place-items:center;font-size:13px;font-weight:800}}
.check-ok .check-icon {{background:var(--good-bg);color:var(--good)}}
.check-no .check-icon {{background:var(--warn-bg);color:var(--warn)}}
.check h3 {{font-size:15px;margin:0 0 3px}}
.check p {{font-size:13px;color:var(--muted);margin:0;overflow-wrap:anywhere}}
.pill {{display:inline-block;border-radius:999px;padding:4px 9px;
  background:#eef2ff;color:#3730a3;font-size:12px;font-weight:700}}
.priority {{border-inline-start:4px solid #f59e0b;padding:12px 14px;
  background:#fffbeb;border-radius:8px;margin:9px 0}}
.priority.high {{border-color:#dc2626;background:#fef2f2}}
.priority.low {{border-color:#94a3b8;background:#f8fafc}}
.table-wrap {{overflow-x:auto}}
table {{border-collapse:collapse;width:100%;font-size:14px}}
th,td {{padding:12px;text-align:start;border-bottom:1px solid var(--border)}}
th {{color:var(--muted);font-size:12px;text-transform:uppercase}}
.business-row {{padding:10px 0;border-bottom:1px solid var(--border);
  overflow-wrap:anywhere}}
footer {{max-width:1120px;margin:0 auto;padding:0 18px 30px;
  color:var(--muted);font-size:12px}}
.notice {{padding:12px 14px;background:#eff6ff;border:1px solid #bfdbfe;
  color:#1e40af;border-radius:10px;font-size:13px;margin-top:14px}}
.error {{background:#fef2f2;border:1px solid #fecaca;color:#991b1b;
  padding:14px;border-radius:12px;margin:15px 0}}
@media(max-width:720px) {{
  .wrap {{margin-top:18px;padding:0 12px 28px}}
  .hero {{padding:23px 19px;border-radius:15px}}
  .panel {{padding:16px}}
  .grid {{grid-template-columns:1fr}}
  .metric-grid {{grid-template-columns:1fr 1fr}}
  .form-row {{flex-direction:column}}
  .btn {{width:100%}}
  .topbar {{padding:14px}}
}}
@media print {{
  body {{background:#fff}}
  .topbar,.no-print,footer {{display:none!important}}
  .wrap {{max-width:none;margin:0;padding:0}}
  .panel,.hero {{box-shadow:none;break-inside:avoid}}
  .hero {{background:#fff;color:#172033;border:1px solid #ddd}}
  .hero p {{color:#475569}}
  a {{color:#172033}}
  .grid {{grid-template-columns:1fr 1fr}}
}}
</style>
<script src="/app.js" defer></script>
</head>
<body>
<header class="topbar">
 <div class="topbar-inner">
  <div>
   <div class="logo">EAQ <span>SEO Audit</span></div>
   <div class="tagline">{esc(tr(lang, "tagline"))}</div>
  </div>
  <form method="get" action="/" class="lang-form no-print">
   <label for="lang" class="small" style="color:#e2e8f0">{esc(tr(lang, "language"))}</label>
   <select id="lang" name="lang">{language_options(lang)}</select>
   <button class="btn btn-light" type="submit">OK</button>
  </form>
 </div>
</header>
<main class="wrap">{content}</main>
<footer>{esc(tr(lang, "footer"))}</footer>
</body>
</html>"""


def home_html(lang="en", error_key=None):
    content = f"""
    <section class="hero">
      <h1>{esc(tr(lang, "heading"))}</h1>
      <p>{esc(tr(lang, "intro"))}</p>
    </section>
    <section class="panel">
      <h2>{esc(tr(lang, "audit"))}</h2>
      <form method="post" action="/audit">
        <input type="hidden" name="lang" value="{esc(lang)}">
        <label for="url"><strong>{esc(tr(lang, "url"))}</strong></label>
        <div class="form-row" style="margin-top:9px">
          <input class="url-input" type="url" id="url" name="url"
            maxlength="{MAX_URL_LENGTH}" required
            placeholder="{esc(tr(lang, 'placeholder'))}">
          <button class="btn btn-primary" type="submit">
            {esc(tr(lang, "audit"))}
          </button>
        </div>
      </form>
      {f'<div class="error"><strong>{esc(tr(lang, error_key))}</strong><br>{esc(tr(lang, "error_detail"))}</div>' if error_key else ''}
      <div class="notice">{esc(tr(lang, "privacy_note"))}</div>
    </section>
    <section class="panel">
      <h2>{esc(tr(lang, "history"))}</h2>
      {history_html(lang)}
    </section>
    """
    return page_shell(content, lang, tr(lang, "brand"))


def history_html(lang):
    rows = get_history()
    if not rows:
        return f'<p class="small">{esc(tr(lang, "no_history"))}</p>'

    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{esc(row['created_at'][:19].replace('T', ' '))}</td>"
            f'<td><a href="/report/{int(row["id"])}?lang={quote(lang)}">'
            f'{esc(row["title"] or row["url"])}'
            "</a><br><span class=\"small\">"
            f'{esc(row["url"][:120])}</span></td>'
            f"<td><strong>{int(row['score'])}/100</strong></td>"
            "<td>"
            f'<a href="/report/{int(row["id"])}?lang={quote(lang)}">'
            f'{esc(tr(lang, "view"))}</a> · '
            f'<form method="post" action="/delete/{int(row["id"])}" '
            'style="display:inline">'
            f'<input type="hidden" name="lang" value="{esc(lang)}">'
            f'<button class="btn btn-danger" style="padding:4px 8px;font-size:12px" '
            f'type="submit">{esc(tr(lang, "delete"))}</button></form>'
            "</td></tr>"
        )

    return (
        '<div class="table-wrap"><table><thead><tr>'
        f"<th>{esc(tr(lang, 'date'))}</th>"
        f"<th>{esc(tr(lang, 'website'))}</th>"
        f"<th>{esc(tr(lang, 'score'))}</th>"
        f"<th>{esc(tr(lang, 'actions'))}</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def business_html(report, lang):
    b = report.get("business", {})
    items = []

    for key, label_key in (
        ("name", "business_name"),
        ("address", "location"),
        ("phone", "phone"),
        ("email", "email"),
        ("website", "website_field"),
    ):
        value = b.get(key, "")
        if value:
            display = esc(value)
            if key == "website" and value.startswith(("http://", "https://")):
                display = f'<a href="{esc(value)}" rel="nofollow noopener">{esc(value)}</a>'
            if key == "email" and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
                display = f'<a href="mailto:{esc(value)}">{esc(value)}</a>'
            items.append(
                f'<div class="business-row"><strong>{esc(tr(lang, label_key))}:</strong> {display}</div>'
            )

    if not items:
        return f'<p class="small">{esc(tr(lang, "no_business"))}</p>'

    address = b.get("address", "")
    map_link = ""
    if address:
        map_url = "https://www.google.com/maps/search/?api=1&query=" + quote(address)
        map_link = (
            f'<p><a href="{esc(map_url)}" target="_blank" rel="noopener noreferrer">'
            f'{esc(tr(lang, "map"))}</a></p>'
        )

    return "".join(items) + map_link


def render_report(report, lang="en"):
    checks_html = []
    for item in report["checks"]:
        label = tr(lang, item["key"])
        ok = item["ok"]
        state = tr(lang, "good" if ok else "warning")
        details = item.get("details") or state
        checks_html.append(
            f'<article class="check {"check-ok" if ok else "check-no"}">'
            f'<div class="check-icon">{"✓" if ok else "!"}</div>'
            f'<div><h3>{esc(label)}</h3>'
            f'<p>{esc(state)}'
            f'{" · " + esc(details) if details else ""}</p></div>'
            '</article>'
        )

    priority_html = []
    for item in report["priorities"]:
        key = item["key"]
        priority = item["priority"]
        priority_label = {
            "high": tr(lang, "priority_high"),
            "medium": tr(lang, "priority_medium"),
            "low": tr(lang, "priority_low"),
        }.get(priority, tr(lang, "priority_medium"))
        priority_html.append(
            f'<div class="priority {esc(priority)}">'
            f'<span class="pill">{esc(priority_label)}</span> '
            f'<strong>{esc(tr(lang, key))}</strong>'
            f'<div class="small">{esc(item.get("details") or "")}</div></div>'
        )

    score = int(report["score"])
    content = f"""
    <section class="hero">
      <div class="no-print" style="margin-bottom:12px">
        <a href="/?lang={quote(lang)}" style="color:#dbeafe">← {esc(tr(lang, "back"))}</a>
      </div>
      <h1>{esc(tr(lang, "results"))}</h1>
      <p style="overflow-wrap:anywhere">{esc(report["url"])}</p>
      <div class="metric-grid" style="margin-top:20px">
        <div class="metric">
          <strong>{score}/100</strong>
          <span>{esc(tr(lang, "overall"))}</span>
        </div>
        <div class="metric">
          <strong>{int(report["passed"])}/{int(report["total"])}</strong>
          <span>{esc(tr(lang, "passed"))}</span>
        </div>
        <div class="metric">
          <strong>{len(report["priorities"])}</strong>
          <span>{esc(tr(lang, "issues"))}</span>
        </div>
      </div>
      <p style="margin-top:14px;font-size:13px">{esc(tr(lang, "not_rank"))}</p>
    </section>

    <div class="no-print" style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px">
      <button class="btn btn-primary" type="button" id="print-report">
        {esc(tr(lang, "print"))}
      </button>
      <a class="btn btn-light" href="/?lang={quote(lang)}">{esc(tr(lang, "back"))}</a>
    </div>

    <div class="grid">
      <section class="panel chart">
        <h2>{esc(tr(lang, "chart_gauge"))}</h2>
        {svg_gauge(score)}
      </section>
      <section class="panel chart">
        <h2>{esc(tr(lang, "chart_donut"))}</h2>
        {svg_donut(report["passed"], report["total"])}
      </section>
      <section class="panel chart">
        <h2>{esc(tr(lang, "chart_bars"))}</h2>
        {svg_bars(report)}
      </section>
      <section class="panel chart">
        <h2>{esc(tr(lang, "chart_radar"))}</h2>
        {svg_radar(report["categories"])}
      </section>
    </div>

    <section class="panel">
      <h2>{esc(tr(lang, "priorities"))}</h2>
      {''.join(priority_html) if priority_html else '<p class="small">' + esc(tr(lang, "good")) + '</p>'}
    </section>

    <section class="panel">
      <h2>{esc(tr(lang, "details"))}</h2>
      <div class="check-list">{''.join(checks_html)}</div>
    </section>

    <section class="panel">
      <h2>{esc(tr(lang, "business"))}</h2>
      {business_html(report, lang)}
      <p class="small">{esc(tr(lang, "business_note"))}</p>
    </section>

    <section class="panel">
      <h2>{esc(tr(lang, "security"))}</h2>
      <p class="small">{esc(tr(lang, "speed_note"))}</p>
      <p class="small">{esc(tr(lang, "pdf_tip"))}</p>
      <p class="small">{esc(tr(lang, "save"))}</p>
      <p class="small">{esc(tr(lang, "report_id"))}: {esc(report.get("report_id", "—"))}</p>
    </section>
    """
    return page_shell(content, lang, f'{tr(lang, "results")} — {report.get("title") or report["url"]}')


# ------------------------------------------------------------
# JavaScript served separately (compatible with CSP)
# ------------------------------------------------------------

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


# ------------------------------------------------------------
# Routes
# ------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request, lang: str = "en"):
    if lang not in LANGUAGES:
        lang = "en"
    return HTMLResponse(home_html(lang))


@app.post("/audit", response_class=HTMLResponse)
def audit(url: str = Form(...), lang: str = Form("en")):
    if lang not in LANGUAGES:
        lang = "en"

    try:
        url = validate_public_url(url)
    except ValueError:
        return HTMLResponse(
            home_html(lang, "invalid"),
            status_code=400
        )

    try:
        fetched = fetch_public_page(url)
        report = audit_html(
            fetched["url"],
            fetched["html"],
            fetched["status"]
        )
        report_id, created_at = save_report(report)
        report["report_id"] = report_id
        report["created_at"] = created_at
        return HTMLResponse(render_report(report, lang))
    except (requests.RequestException, ValueError, OSError) as exc:
        logger.info("Audit failed: %s", type(exc).__name__)
        return HTMLResponse(
            home_html(lang, "error"),
            status_code=400
        )
    except Exception:
        logger.exception("Unexpected audit error")
        return HTMLResponse(
            home_html(lang, "error"),
            status_code=500
        )


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
        conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
        conn.commit()

    return HTMLResponse(home_html(lang))


@app.get("/health")
def health():
    return JSONResponse({
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=False
    )
