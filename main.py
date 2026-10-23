import os
import re
import json
import time
import socket
import sqlite3
import ipaddress
import threading
import concurrent.futures
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

APP_NAME = "EAQ SEO Audit"
VERSION = "6.0.0"
DB_PATH = os.getenv("EAQ_DB", "eaq_reports.db")
TIMEOUT = 7
MAX_LINKS = 25

app = FastAPI(title=APP_NAME, version=VERSION)
session = requests.Session()
session.headers.update({
    "User-Agent": "EAQ-SEO-Audit/6.0 (+technical SEO checker)"
})
db_lock = threading.Lock()

LANGUAGES = {
    "en": {
        "name": "English", "dir": "ltr", "home": "Home",
        "reports": "Reports", "status": "System status",
        "tagline": "Explore. Automate. Quality.",
        "hero": "Understand your website. Improve your visibility.",
        "sub": "A technical SEO audit with website profile, performance signals and saved reports.",
        "url": "Website URL", "audit": "Start SEO audit",
        "example": "Example: https://example.com",
        "recent": "Recent reports", "run": "Run new audit",
        "technical": "Technical SEO", "profile": "Website profile",
        "performance": "PageSpeed Insights", "history": "Domain history",
        "links": "Link checks", "passed": "Passed",
        "failed": "Needs attention", "info": "Information",
        "score": "Technical score", "title": "Page title",
        "description": "Meta description", "h1": "H1 headings",
        "canonical": "Canonical URL", "https": "HTTPS",
        "viewport": "Mobile viewport", "charset": "Character encoding",
        "images": "Images missing alt text", "robots": "robots.txt",
        "sitemap": "sitemap.xml", "status_code": "HTTP status",
        "content_type": "Content type", "links_count": "Links found",
        "domain": "Domain", "registered": "Registration date",
        "age": "Approximate domain age", "wayback": "Archive history",
        "traffic": "Traffic estimate", "not_configured": "Not configured",
        "blocked": "Rate-limited or blocked by the service",
        "not_found": "Not found", "not_checked": "Not checked",
        "website_name": "Website / business name",
        "site_description": "Website description",
        "services": "Services / topics", "address": "Address",
        "email": "Public email", "phone": "Public phone",
        "no_data": "Not detected on the page",
        "save_pdf": "Print / Save as PDF", "new": "New audit",
        "details": "Open report", "date": "Date",
        "empty": "No saved reports yet.",
        "health_text": "The application is running. External services may limit requests.",
        "error": "Could not audit this URL. Check the address and try again.",
        "invalid": "Enter a valid public website URL beginning with http:// or https://.",
        "loading": "Auditing website…",
        "note": "The technical score measures the checks below. It is not a Google ranking prediction.",
        "page_speed": "Run PageSpeed test", "mobile": "Mobile",
        "desktop": "Desktop", "http_note": "A 403/429 response can indicate access restrictions, not a broken page.",
        "back": "Back to reports", "language": "Language",
        "checked": "Audit completed", "http": "HTTP response",
        "length": "characters", "no_title": "Missing page title",
        "no_desc": "Missing meta description", "multiple_h1": "Multiple H1 headings",
        "single_h1": "One H1 heading", "redirect": "Final URL",
        "canonical_missing": "Missing canonical URL",
        "canonical_ok": "Canonical URL found",
        "secure": "Secure HTTPS connection", "insecure": "Website does not use HTTPS",
        "alt_ok": "All checked images have alt text",
        "robots_ok": "robots.txt found", "sitemap_ok": "sitemap.xml found",
    },
    "ar": {
        "name": "العربية", "dir": "rtl", "home": "الرئيسية",
        "reports": "التقارير", "status": "حالة النظام",
        "tagline": "استكشف. أتمت. الجودة.",
        "hero": "افهم موقعك الإلكتروني وحسّن ظهوره.",
        "sub": "فحص SEO تقني، معلومات الموقع، مؤشرات الأداء وحفظ التقارير.",
        "url": "رابط الموقع", "audit": "ابدأ فحص SEO",
        "example": "مثال: https://example.com",
        "recent": "أحدث التقارير", "run": "فحص جديد",
        "technical": "تحسين محركات البحث التقني", "profile": "ملف الموقع",
        "performance": "PageSpeed Insights", "history": "تاريخ النطاق",
        "links": "فحص الروابط", "passed": "ناجح",
        "failed": "يحتاج إلى مراجعة", "info": "معلومات",
        "score": "النتيجة التقنية", "title": "عنوان الصفحة",
        "description": "وصف الصفحة Meta Description", "h1": "عناوين H1",
        "canonical": "الرابط الأساسي Canonical", "https": "HTTPS",
        "viewport": "دعم عرض الهاتف", "charset": "ترميز الأحرف",
        "images": "صور بلا نص بديل ALT", "robots": "ملف robots.txt",
        "sitemap": "ملف sitemap.xml", "status_code": "حالة HTTP",
        "content_type": "نوع المحتوى", "links_count": "عدد الروابط المكتشفة",
        "domain": "النطاق", "registered": "تاريخ تسجيل النطاق",
        "age": "عمر النطاق التقريبي", "wayback": "أرشيف الموقع",
        "traffic": "تقدير الزيارات", "not_configured": "غير مهيأ",
        "blocked": "الخدمة فرضت قيودًا أو حجبت الطلب",
        "not_found": "غير موجود", "not_checked": "لم يتم الفحص",
        "website_name": "اسم الموقع أو المؤسسة",
        "site_description": "وصف الموقع",
        "services": "الخدمات أو المواضيع", "address": "العنوان",
        "email": "البريد الإلكتروني المنشور", "phone": "الهاتف المنشور",
        "no_data": "لم يتم العثور عليه في الصفحة",
        "save_pdf": "طباعة / حفظ PDF", "new": "فحص جديد",
        "details": "عرض التقرير", "date": "التاريخ",
        "empty": "لا توجد تقارير محفوظة بعد.",
        "health_text": "التطبيق يعمل. قد تفرض الخدمات الخارجية قيودًا على الطلبات.",
        "error": "تعذر فحص الرابط. تحقق من العنوان وحاول مجددًا.",
        "invalid": "أدخل رابطًا عامًا صحيحًا يبدأ بـ http:// أو https://.",
        "loading": "جارٍ فحص الموقع…",
        "note": "النتيجة تقيس الفحوصات التقنية أدناه، ولا تتنبأ بترتيب الموقع في Google.",
        "page_speed": "فحص PageSpeed", "mobile": "الهاتف",
        "desktop": "الحاسوب", "http_note": "حالة 403 أو 429 قد تعني تقييد الوصول، وليس بالضرورة أن الصفحة معطلة.",
        "back": "العودة إلى التقارير", "language": "اللغة",
        "checked": "اكتمل الفحص", "http": "استجابة HTTP",
        "length": "حرفًا", "no_title": "عنوان الصفحة مفقود",
        "no_desc": "وصف الصفحة مفقود", "multiple_h1": "يوجد أكثر من عنوان H1",
        "single_h1": "يوجد عنوان H1 واحد", "redirect": "الرابط النهائي",
        "canonical_missing": "الرابط الأساسي Canonical مفقود",
        "canonical_ok": "تم العثور على الرابط الأساسي",
        "secure": "اتصال HTTPS آمن", "insecure": "الموقع لا يستخدم HTTPS",
        "alt_ok": "الصور المفحوصة تحتوي على نص بديل",
        "robots_ok": "تم العثور على robots.txt", "sitemap_ok": "تم العثور على sitemap.xml",
    },
    "fr": {
        "name": "Français", "dir": "ltr", "home": "Accueil",
        "reports": "Rapports", "status": "État du système",
        "tagline": "Explore. Automate. Quality.",
        "hero": "Comprenez votre site et améliorez sa visibilité.",
        "sub": "Audit SEO technique, profil du site, performances et rapports enregistrés.",
        "url": "URL du site", "audit": "Lancer l’audit SEO",
        "example": "Exemple : https://example.com",
        "recent": "Rapports récents", "run": "Nouvel audit",
        "technical": "SEO technique", "profile": "Profil du site",
        "performance": "PageSpeed Insights", "history": "Historique du domaine",
        "links": "Vérification des liens", "passed": "Réussi",
        "failed": "À améliorer", "info": "Information",
        "score": "Score technique", "title": "Titre de page",
        "description": "Meta description", "h1": "Titres H1",
        "canonical": "URL canonique", "https": "HTTPS",
        "viewport": "Affichage mobile", "charset": "Encodage",
        "images": "Images sans texte ALT", "robots": "robots.txt",
        "sitemap": "sitemap.xml", "status_code": "Statut HTTP",
        "content_type": "Type de contenu", "links_count": "Liens trouvés",
        "domain": "Domaine", "registered": "Date d’enregistrement",
        "age": "Âge approximatif", "wayback": "Historique d’archives",
        "traffic": "Estimation du trafic", "not_configured": "Non configuré",
        "blocked": "Service limité ou bloqué",
        "not_found": "Introuvable", "not_checked": "Non vérifié",
        "website_name": "Nom du site / entreprise",
        "site_description": "Description du site",
        "services": "Services / sujets", "address": "Adresse",
        "email": "E-mail public", "phone": "Téléphone public",
        "no_data": "Non détecté sur la page",
        "save_pdf": "Imprimer / Enregistrer PDF", "new": "Nouvel audit",
        "details": "Ouvrir le rapport", "date": "Date",
        "empty": "Aucun rapport enregistré.",
        "health_text": "L’application fonctionne. Les services externes peuvent limiter les requêtes.",
        "error": "Audit impossible. Vérifiez l’URL.",
        "invalid": "Saisissez une URL publique valide en http:// ou https://.",
        "loading": "Audit en cours…",
        "note": "Le score mesure les contrôles techniques, pas le classement Google.",
        "page_speed": "Tester PageSpeed", "mobile": "Mobile",
        "desktop": "Ordinateur", "http_note": "403/429 peut indiquer une restriction, pas une page cassée.",
        "back": "Retour aux rapports", "language": "Langue",
        "checked": "Audit terminé", "http": "Réponse HTTP",
        "length": "caractères", "no_title": "Titre absent",
        "no_desc": "Meta description absente", "multiple_h1": "Plusieurs titres H1",
        "single_h1": "Un titre H1", "redirect": "URL finale",
        "canonical_missing": "URL canonique absente",
        "canonical_ok": "URL canonique trouvée",
        "secure": "Connexion HTTPS", "insecure": "HTTPS non utilisé",
        "alt_ok": "Images vérifiées avec texte ALT",
        "robots_ok": "robots.txt trouvé", "sitemap_ok": "sitemap.xml trouvé",
    },
    "es": {
        "name": "Español", "dir": "ltr", "home": "Inicio",
        "reports": "Informes", "status": "Estado del sistema",
        "tagline": "Explore. Automate. Quality.",
        "hero": "Comprende tu sitio web y mejora su visibilidad.",
        "sub": "Auditoría SEO técnica, perfil web, rendimiento e informes guardados.",
        "url": "URL del sitio", "audit": "Iniciar auditoría SEO",
        "example": "Ejemplo: https://example.com",
        "recent": "Informes recientes", "run": "Nueva auditoría",
        "technical": "SEO técnico", "profile": "Perfil del sitio",
        "performance": "PageSpeed Insights", "history": "Historial del dominio",
        "links": "Comprobación de enlaces", "passed": "Correcto",
        "failed": "Necesita atención", "info": "Información",
        "score": "Puntuación técnica", "title": "Título de página",
        "description": "Meta descripción", "h1": "Encabezados H1",
        "canonical": "URL canónica", "https": "HTTPS",
        "viewport": "Vista móvil", "charset": "Codificación",
        "images": "Imágenes sin ALT", "robots": "robots.txt",
        "sitemap": "sitemap.xml", "status_code": "Estado HTTP",
        "content_type": "Tipo de contenido", "links_count": "Enlaces encontrados",
        "domain": "Dominio", "registered": "Fecha de registro",
        "age": "Antigüedad aproximada", "wayback": "Historial de archivo",
        "traffic": "Estimación de tráfico", "not_configured": "No configurado",
        "blocked": "Servicio limitado o bloqueado",
        "not_found": "No encontrado", "not_checked": "Sin comprobar",
        "website_name": "Nombre del sitio / empresa",
        "site_description": "Descripción del sitio",
        "services": "Servicios / temas", "address": "Dirección",
        "email": "Correo público", "phone": "Teléfono público",
        "no_data": "No detectado en la página",
        "save_pdf": "Imprimir / Guardar PDF", "new": "Nueva auditoría",
        "details": "Abrir informe", "date": "Fecha",
        "empty": "Todavía no hay informes guardados.",
        "health_text": "La aplicación funciona. Los servicios externos pueden limitar solicitudes.",
        "error": "No se pudo auditar la URL.",
        "invalid": "Introduce una URL pública válida con http:// o https://.",
        "loading": "Analizando sitio…",
        "note": "La puntuación mide comprobaciones técnicas, no el ranking de Google.",
        "page_speed": "Probar PageSpeed", "mobile": "Móvil",
        "desktop": "Escritorio", "http_note": "403/429 puede indicar restricciones, no un sitio roto.",
        "back": "Volver a informes", "language": "Idioma",
        "checked": "Auditoría completada", "http": "Respuesta HTTP",
        "length": "caracteres", "no_title": "Falta el título",
        "no_desc": "Falta la meta descripción", "multiple_h1": "Varios encabezados H1",
        "single_h1": "Un encabezado H1", "redirect": "URL final",
        "canonical_missing": "Falta URL canónica",
        "canonical_ok": "URL canónica encontrada",
        "secure": "Conexión HTTPS", "insecure": "No usa HTTPS",
        "alt_ok": "Imágenes revisadas con ALT",
        "robots_ok": "robots.txt encontrado", "sitemap_ok": "sitemap.xml encontrado",
    },
    "de": {
        "name": "Deutsch", "dir": "ltr", "home": "Startseite",
        "reports": "Berichte", "status": "Systemstatus",
        "tagline": "Explore. Automate. Quality.",
        "hero": "Verstehen Sie Ihre Website und verbessern Sie ihre Sichtbarkeit.",
        "sub": "Technisches SEO-Audit, Website-Profil, Leistung und gespeicherte Berichte.",
        "url": "Website-URL", "audit": "SEO-Audit starten",
        "example": "Beispiel: https://example.com",
        "recent": "Neueste Berichte", "run": "Neues Audit",
        "technical": "Technisches SEO", "profile": "Website-Profil",
        "performance": "PageSpeed Insights", "history": "Domainverlauf",
        "links": "Linkprüfung", "passed": "Bestanden",
        "failed": "Zu verbessern", "info": "Information",
        "score": "Technischer Score", "title": "Seitentitel",
        "description": "Meta-Beschreibung", "h1": "H1-Überschriften",
        "canonical": "Kanonische URL", "https": "HTTPS",
        "viewport": "Mobile Ansicht", "charset": "Zeichenkodierung",
        "images": "Bilder ohne ALT-Text", "robots": "robots.txt",
        "sitemap": "sitemap.xml", "status_code": "HTTP-Status",
        "content_type": "Inhaltstyp", "links_count": "Gefundene Links",
        "domain": "Domain", "registered": "Registrierungsdatum",
        "age": "Ungefähres Domainalter", "wayback": "Archivverlauf",
        "traffic": "Traffic-Schätzung", "not_configured": "Nicht konfiguriert",
        "blocked": "Dienst eingeschränkt oder blockiert",
        "not_found": "Nicht gefunden", "not_checked": "Nicht geprüft",
        "website_name": "Website-/Firmenname",
        "site_description": "Website-Beschreibung",
        "services": "Dienste / Themen", "address": "Adresse",
        "email": "Öffentliche E-Mail", "phone": "Öffentliche Telefonnummer",
        "no_data": "Auf der Seite nicht erkannt",
        "save_pdf": "Drucken / PDF speichern", "new": "Neues Audit",
        "details": "Bericht öffnen", "date": "Datum",
        "empty": "Noch keine gespeicherten Berichte.",
        "health_text": "Die Anwendung läuft. Externe Dienste können Anfragen begrenzen.",
        "error": "Die URL konnte nicht geprüft werden.",
        "invalid": "Geben Sie eine gültige öffentliche HTTP(S)-URL ein.",
        "loading": "Website wird geprüft…",
        "note": "Der Score misst technische Prüfungen, nicht das Google-Ranking.",
        "page_speed": "PageSpeed testen", "mobile": "Mobil",
        "desktop": "Desktop", "http_note": "403/429 kann Zugriffsbeschränkungen bedeuten.",
        "back": "Zurück zu Berichten", "language": "Sprache",
        "checked": "Audit abgeschlossen", "http": "HTTP-Antwort",
        "length": "Zeichen", "no_title": "Seitentitel fehlt",
        "no_desc": "Meta-Beschreibung fehlt", "multiple_h1": "Mehrere H1-Überschriften",
        "single_h1": "Eine H1-Überschrift", "redirect": "Endgültige URL",
        "canonical_missing": "Kanonische URL fehlt",
        "canonical_ok": "Kanonische URL gefunden",
        "secure": "Sichere HTTPS-Verbindung", "insecure": "HTTPS wird nicht verwendet",
        "alt_ok": "Geprüfte Bilder mit ALT-Text",
        "robots_ok": "robots.txt gefunden", "sitemap_ok": "sitemap.xml gefunden",
    },
    "zh": {
        "name": "中文", "dir": "ltr", "home": "首页",
        "reports": "报告", "status": "系统状态",
        "tagline": "探索 · 自动化 · 品质",
        "hero": "了解您的网站，提升网站可见度。",
        "sub": "技术 SEO 审计、网站资料、性能指标与已保存报告。",
        "url": "网站网址", "audit": "开始 SEO 审计",
        "example": "示例：https://example.com",
        "recent": "最近报告", "run": "新建审计",
        "technical": "技术 SEO", "profile": "网站资料",
        "performance": "PageSpeed Insights", "history": "域名历史",
        "links": "链接检查", "passed": "通过",
        "failed": "需要改进", "info": "信息",
        "score": "技术评分", "title": "页面标题",
        "description": "Meta 描述", "h1": "H1 标题",
        "canonical": "规范网址", "https": "HTTPS",
        "viewport": "移动端视口", "charset": "字符编码",
        "images": "缺少 ALT 的图片", "robots": "robots.txt",
        "sitemap": "sitemap.xml", "status_code": "HTTP 状态",
        "content_type": "内容类型", "links_count": "发现的链接",
        "domain": "域名", "registered": "注册日期",
        "age": "域名大致年龄", "wayback": "网页存档历史",
        "traffic": "流量估算", "not_configured": "未配置",
        "blocked": "服务受到限制或被拦截",
        "not_found": "未找到", "not_checked": "未检查",
        "website_name": "网站 / 企业名称",
        "site_description": "网站描述", "services": "服务 / 主题",
        "address": "地址", "email": "公开邮箱", "phone": "公开电话",
        "no_data": "页面中未检测到",
        "save_pdf": "打印 / 保存 PDF", "new": "新建审计",
        "details": "打开报告", "date": "日期",
        "empty": "尚无已保存报告。",
        "health_text": "应用正在运行。外部服务可能限制请求。",
        "error": "无法审计该网址，请检查网址。",
        "invalid": "请输入以 http:// 或 https:// 开头的有效公共网址。",
        "loading": "正在审计网站…",
        "note": "评分衡量技术检查结果，不代表 Google 排名预测。",
        "page_speed": "运行 PageSpeed 测试", "mobile": "移动端",
        "desktop": "桌面端", "http_note": "403/429 可能表示访问受限，不一定是网站故障。",
        "back": "返回报告", "language": "语言",
        "checked": "审计完成", "http": "HTTP 响应",
        "length": "字符", "no_title": "缺少页面标题",
        "no_desc": "缺少 Meta 描述", "multiple_h1": "存在多个 H1 标题",
        "single_h1": "存在一个 H1 标题", "redirect": "最终网址",
        "canonical_missing": "缺少规范网址",
        "canonical_ok": "已找到规范网址",
        "secure": "HTTPS 安全连接", "insecure": "网站未使用 HTTPS",
        "alt_ok": "已检查图片均含 ALT 文本",
        "robots_ok": "已找到 robots.txt", "sitemap_ok": "已找到 sitemap.xml",
    },
}


def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_lock:
        conn = db()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                created_at TEXT NOT NULL,
                score INTEGER NOT NULL,
                data TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()


init_db()


def tr(lang, key):
    lang = lang if lang in LANGUAGES else "en"
    return LANGUAGES[lang].get(key, LANGUAGES["en"].get(key, key))


def esc(value):
    import html
    return html.escape(str(value if value is not None else ""))


def public_url(url):
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        if parsed.username or pa
