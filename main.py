import os
import re
import json
import time
import socket
import ipaddress
import sqlite3
import requests

from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin, quote
from html import escape
from xml.etree import ElementTree

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from bs4 import BeautifulSoup


# ============================================================
# EAQ SEO AUDIT — VERSION 6.0.0
# ============================================================

APP_NAME = "EAQ SEO Audit"
APP_VERSION = "6.0.0"

DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "eaq_audit.sqlite3")
)

REQUEST_TIMEOUT = 12
MAX_REDIRECTS = 5
MAX_LINKS_TO_CHECK = 25
MAX_HTML_BYTES = 2_000_000

USER_AGENT = (
    "EAQSEOAudit/6.0 "
    "(Technical SEO diagnostics; respectful automated requests)"
)

LANGUAGES = {
    "ar": "العربية",
    "en": "English",
    "fr": "Français",
    "es": "Español",
    "de": "Deutsch",
    "zh": "中文",
}

TEXT = {
    "ar": {
        "home": "الرئيسية", "reports": "التقارير", "health": "حالة الخدمة",
        "tagline": "استكشف. أتمت. حسّن الجودة.",
        "hero": "افحص موقعك واكتشف فرص تحسينه",
        "intro": "تحليل تقني للموقع يشمل عناصر SEO الأساسية والروابط والسرعة ومعلومات النطاق المتاحة.",
        "url": "رابط الموقع", "placeholder": "https://example.com",
        "start": "ابدأ الفحص", "pagespeed": "فحص PageSpeed على الهاتف والحاسوب",
        "links": "فحص عينة من الروابط", "features": "ماذا يقدم EAQ؟",
        "technical": "تدقيق SEO التقني",
        "technical_desc": "فحص العنوان والوصف والعناوين الرئيسية وCanonical وHTTPS وملفات robots وsitemap.",
        "speed": "الأداء والسرعة",
        "speed_desc": "استرجاع مؤشرات Google PageSpeed Insights عند توفر الخدمة.",
        "history": "تاريخ النطاق",
        "history_desc": "محاولة استرجاع بيانات التسجيل وسجل Wayback Machine.",
        "profile": "ملف الموقع التعريفي",
        "description": "وصف الموقع", "address": "العنوان",
        "site_title": "اسم الموقع", "not_found": "لم يتم العثور على بيانات منشورة.",
        "audit_report": "تقرير تدقيق SEO", "score": "نتيجة الفحص التقني",
        "passed": "الفحوصات الناجحة", "http": "حالة HTTP",
        "checked_links": "الروابط المفحوصة", "checks": "الفحوصات التقنية",
        "page_info": "معلومات الصفحة", "title": "العنوان",
        "meta_description": "وصف Meta", "canonical": "الرابط Canonical",
        "images": "الصور", "missing_alt": "صور دون وصف alt",
        "print": "طباعة / حفظ PDF", "new_audit": "فحص جديد",
        "saved_reports": "التقارير المحفوظة", "pagespeed_title": "Google PageSpeed Insights",
        "link_check": "فحص الروابط", "domain_age": "عمر النطاق",
        "wayback": "سجل Wayback Machine", "traffic": "تقديرات الزيارات",
        "check": "الفحص", "result": "النتيجة", "details": "التفاصيل",
        "pass": "ناجح", "review": "مراجعة", "anchor": "نص الرابط",
        "status": "حالة HTTP", "date": "التاريخ", "website": "الموقع",
        "no_reports": "لا توجد تقارير محفوظة بعد.",
        "latest_reports": "تظهر هنا أحدث 100 تقرير محفوظ.",
        "start_new": "بدء فحص جديد",
        "disclaimer": "هذه النتيجة ليست درجة Google ولا تضمن ترتيب الموقع في نتائج البحث.",
        "invalid": "رابط غير صالح", "fetch_error": "تعذر الوصول إلى الموقع",
        "try_again": "حاول مجددًا", "generated": "تاريخ إنشاء التقرير",
        "creation_date": "تاريخ إنشاء النطاق", "estimated_age": "العمر التقديري",
        "year": "السنة", "records": "السجلات المسترجعة",
        "no_links": "لم يتم فحص روابط.", "not_available": "غير متاح",
        "footer": "أداة تشخيص تقني؛ النتائج الخارجية قد تكون غير متاحة مؤقتًا.",
        "language": "اللغة", "robots": "ملف robots.txt", "sitemap": "خريطة الموقع",
    },
    "en": {
        "home": "Home", "reports": "Reports", "health": "Service status",
        "tagline": "Explore. Automate. Quality.",
        "hero": "Audit your website and find improvement opportunities",
        "intro": "Technical analysis covering core SEO checks, links, performance and available domain information.",
        "url": "Website URL", "placeholder": "https://example.com",
        "start": "Start audit", "pagespeed": "Check PageSpeed on mobile and desktop",
        "links": "Check a sample of links", "features": "What does EAQ provide?",
        "technical": "Technical SEO audit",
        "technical_desc": "Checks titles, descriptions, headings, canonical, HTTPS, robots and sitemap.",
        "speed": "Performance and speed",
        "speed_desc": "Retrieves Google PageSpeed Insights metrics when available.",
        "history": "Domain history",
        "history_desc": "Attempts to retrieve registration details and Wayback Machine history.",
        "profile": "Website profile", "description": "Website description",
        "address": "Address", "site_title": "Website name",
        "not_found": "No published information was found.",
        "audit_report": "SEO Audit Report", "score": "Technical checklist score",
        "passed": "Checks passed", "http": "HTTP status",
        "checked_links": "Links checked", "checks": "Technical checks",
        "page_info": "Page information", "title": "Title",
        "meta_description": "Meta description", "canonical": "Canonical URL",
        "images": "Images", "missing_alt": "Images missing alt",
        "print": "Print / Save PDF", "new_audit": "New audit",
        "saved_reports": "Saved reports", "pagespeed_title": "Google PageSpeed Insights",
        "link_check": "Link check", "domain_age": "Domain registration age",
        "wayback": "Wayback Machine history", "traffic": "Traffic estimates",
        "check": "Check", "result": "Result", "details": "Details",
        "pass": "PASS", "review": "REVIEW", "anchor": "Anchor text",
        "status": "HTTP status", "date": "Date", "website": "Website",
        "no_reports": "No saved reports yet.",
        "latest_reports": "The latest 100 saved reports are listed here.",
        "start_new": "Start a new audit",
        "disclaimer": "This score is not a Google score and does not guarantee search rankings.",
        "invalid": "Invalid URL", "fetch_error": "Could not access website",
        "try_again": "Try again", "generated": "Report generated",
        "creation_date": "Domain creation date", "estimated_age": "Estimated age",
        "year": "Year", "records": "Returned records",
        "no_links": "No links were checked.", "not_available": "Unavailable",
        "footer": "Technical diagnostics only; external services may be temporarily unavailable.",
        "language": "Language", "robots": "robots.txt", "sitemap": "Sitemap",
    },
    "fr": {
        "home": "Accueil", "reports": "Rapports", "health": "État du service",
        "tagline": "Explorer. Automatiser. Qualité.",
        "hero": "Analysez votre site et identifiez les améliorations",
        "intro": "Analyse technique du SEO, des liens, des performances et des données de domaine disponibles.",
        "url": "URL du site", "placeholder": "https://example.com",
        "start": "Lancer l’audit", "pagespeed": "Analyser PageSpeed sur mobile et ordinateur",
        "links": "Vérifier un échantillon de liens", "features": "Fonctionnalités d’EAQ",
        "technical": "Audit SEO technique",
        "technical_desc": "Vérification des titres, descriptions, en-têtes, canonical, HTTPS, robots et sitemap.",
        "speed": "Performances et vitesse",
        "speed_desc": "Données Google PageSpeed Insights lorsque disponibles.",
        "history": "Historique du domaine",
        "history_desc": "Recherche des données d’enregistrement et de l’historique Wayback Machine.",
        "profile": "Profil du site", "description": "Description du site",
        "address": "Adresse", "site_title": "Nom du site",
        "not_found": "Aucune information publiée trouvée.",
        "audit_report": "Rapport d’audit SEO", "score": "Score technique",
        "passed": "Contrôles réussis", "http": "Statut HTTP",
        "checked_links": "Liens vérifiés", "checks": "Contrôles techniques",
        "page_info": "Informations de la page", "title": "Titre",
        "meta_description": "Méta-description", "canonical": "URL canonique",
        "images": "Images", "missing_alt": "Images sans texte alt",
        "print": "Imprimer / Enregistrer en PDF", "new_audit": "Nouvel audit",
        "saved_reports": "Rapports enregistrés", "pagespeed_title": "Google PageSpeed Insights",
        "link_check": "Vérification des liens", "domain_age": "Âge du domaine",
        "wayback": "Historique Wayback Machine", "traffic": "Estimations du trafic",
        "check": "Contrôle", "result": "Résultat", "details": "Détails",
        "pass": "RÉUSSI", "review": "À VÉRIFIER", "anchor": "Texte du lien",
        "status": "Statut HTTP", "date": "Date", "website": "Site web",
        "no_reports": "Aucun rapport enregistré.", "latest_reports": "Les 100 derniers rapports sont affichés.",
        "start_new": "Nouvel audit", "disclaimer": "Ce score n’est pas celui de Google et ne garantit pas le classement.",
        "invalid": "URL invalide", "fetch_error": "Site inaccessible", "try_again": "Réessayer",
        "generated": "Rapport généré", "creation_date": "Date de création du domaine",
        "estimated_age": "Âge estimé", "year": "Année", "records": "Enregistrements",
        "no_links": "Aucun lien vérifié.", "not_available": "Indisponible",
        "footer": "Diagnostic technique uniquement ; les services externes peuvent être temporairement indisponibles.",
        "language": "Langue", "robots": "robots.txt", "sitemap": "Plan du site",
    },
    "es": {
        "home": "Inicio", "reports": "Informes", "health": "Estado del servicio",
        "tagline": "Explorar. Automatizar. Calidad.",
        "hero": "Audita tu sitio web y descubre mejoras",
        "intro": "Análisis técnico SEO, enlaces, rendimiento e información de dominio disponible.",
        "url": "URL del sitio web", "placeholder": "https://example.com",
        "start": "Iniciar auditoría", "pagespeed": "Analizar PageSpeed en móvil y escritorio",
        "links": "Comprobar una muestra de enlaces", "features": "¿Qué ofrece EAQ?",
        "technical": "Auditoría SEO técnica",
        "technical_desc": "Revisa títulos, descripciones, encabezados, canonical, HTTPS, robots y sitemap.",
        "speed": "Rendimiento y velocidad",
        "speed_desc": "Métricas de Google PageSpeed Insights cuando estén disponibles.",
        "history": "Historial del dominio",
        "history_desc": "Intenta recuperar datos de registro e historial de Wayback Machine.",
        "profile": "Perfil del sitio", "description": "Descripción del sitio",
        "address": "Dirección", "site_title": "Nombre del sitio",
        "not_found": "No se encontró información publicada.",
        "audit_report": "Informe de auditoría SEO", "score": "Puntuación técnica",
        "passed": "Comprobaciones correctas", "http": "Estado HTTP",
        "checked_links": "Enlaces comprobados", "checks": "Comprobaciones técnicas",
        "page_info": "Información de la página", "title": "Título",
        "meta_description": "Meta descripción", "canonical": "URL canónica",
        "images": "Imágenes", "missing_alt": "Imágenes sin texto alt",
        "print": "Imprimir / Guardar PDF", "new_audit": "Nueva auditoría",
        "saved_reports": "Informes guardados", "pagespeed_title": "Google PageSpeed Insights",
        "link_check": "Comprobación de enlaces", "domain_age": "Antigüedad del dominio",
        "wayback": "Historial de Wayback Machine", "traffic": "Estimaciones de tráfico",
        "check": "Comprobación", "result": "Resultado", "details": "Detalles",
        "pass": "CORRECTO", "review": "REVISAR", "anchor": "Texto del enlace",
        "status": "Estado HTTP", "date": "Fecha", "website": "Sitio web",
        "no_reports": "Aún no hay informes guardados.", "latest_reports": "Se muestran los últimos 100 informes.",
        "start_new": "Nueva auditoría", "disclaimer": "Esta puntuación no es de Google ni garantiza posiciones.",
        "invalid": "URL no válida", "fetch_error": "No se pudo acceder al sitio", "try_again": "Intentar de nuevo",
        "generated": "Informe generado", "creation_date": "Fecha de creación del dominio",
        "estimated_age": "Antigüedad estimada", "year": "Año", "records": "Registros devueltos",
        "no_links": "No se comprobaron enlaces.", "not_available": "No disponible",
        "footer": "Diagnóstico técnico; los servicios externos pueden no estar disponibles temporalmente.",
        "language": "Idioma", "robots": "robots.txt", "sitemap": "Mapa del sitio",
    },
    "de": {
        "home": "Startseite", "reports": "Berichte", "health": "Dienststatus",
        "tagline": "Entdecken. Automatisieren. Qualität.",
        "hero": "Website prüfen und Verbesserungen erkennen",
        "intro": "Technische SEO-Analyse, Links, Leistung und verfügbare Domaininformationen.",
        "url": "Website-URL", "placeholder": "https://example.com",
        "start": "Prüfung starten", "pagespeed": "PageSpeed auf Mobilgeräten und Desktop prüfen",
        "links": "Stichprobe von Links prüfen", "features": "Was bietet EAQ?",
        "technical": "Technisches SEO-Audit",
        "technical_desc": "Prüft Titel, Beschreibungen, Überschriften, Canonical, HTTPS, robots und Sitemap.",
        "speed": "Leistung und Geschwindigkeit",
        "speed_desc": "Google-PageSpeed-Insights-Daten, sofern verfügbar.",
        "history": "Domainverlauf",
        "history_desc": "Versucht Registrierungsdaten und Wayback-Machine-Verlauf abzurufen.",
        "profile": "Website-Profil", "description": "Website-Beschreibung",
        "address": "Adresse", "site_title": "Website-Name",
        "not_found": "Keine veröffentlichten Informationen gefunden.",
        "audit_report": "SEO-Prüfbericht", "score": "Technische Punktzahl",
        "passed": "Bestandene Prüfungen", "http": "HTTP-Status",
        "checked_links": "Geprüfte Links", "checks": "Technische Prüfungen",
        "page_info": "Seiteninformationen", "title": "Titel",
        "meta_description": "Meta-Beschreibung", "canonical": "Kanonische URL",
        "images": "Bilder", "missing_alt": "Bilder ohne Alt-Text",
        "print": "Drucken / Als PDF speichern", "new_audit": "Neue Prüfung",
        "saved_reports": "Gespeicherte Berichte", "pagespeed_title": "Google PageSpeed Insights",
        "link_check": "Linkprüfung", "domain_age": "Domainalter",
        "wayback": "Wayback-Machine-Verlauf", "traffic": "Traffic-Schätzungen",
        "check": "Prüfung", "result": "Ergebnis", "details": "Details",
        "pass": "BESTANDEN", "review": "PRÜFEN", "anchor": "Linktext",
        "status": "HTTP-Status", "date": "Datum", "website": "Website",
        "no_reports": "Noch keine Berichte gespeichert.", "latest_reports": "Die letzten 100 Berichte werden angezeigt.",
        "start_new": "Neue Prüfung", "disclaimer": "Diese Punktzahl stammt nicht von Google und garantiert keine Rankings.",
        "invalid": "Ungültige URL", "fetch_error": "Website nicht erreichbar", "try_again": "Erneut versuchen",
        "generated": "Bericht erstellt", "creation_date": "Domain-Erstellungsdatum",
        "estimated_age": "Geschätztes Alter", "year": "Jahr", "records": "Gefundene Einträge",
        "no_links": "Keine Links geprüft.", "not_available": "Nicht verfügbar",
        "footer": "Technische Diagnose; externe Dienste können vorübergehend nicht verfügbar sein.",
        "language": "Sprache", "robots": "robots.txt", "sitemap": "Sitemap",
    },
    "zh": {
        "home": "首页", "reports": "报告", "health": "服务状态",
        "tagline": "探索 · 自动化 · 品质",
        "hero": "检测网站并发现优化机会",
        "intro": "技术 SEO、链接、性能以及可获取的域名信息分析。",
        "url": "网站网址", "placeholder": "https://example.com",
        "start": "开始检测", "pagespeed": "检测移动端和桌面端 PageSpeed",
        "links": "抽样检查链接", "features": "EAQ 提供什么？",
        "technical": "技术 SEO 检测",
        "technical_desc": "检查标题、描述、标题标签、Canonical、HTTPS、robots 和 sitemap。",
        "speed": "性能与速度",
        "speed_desc": "在服务可用时获取 Google PageSpeed Insights 指标。",
        "history": "域名历史",
        "history_desc": "尝试获取域名注册信息和 Wayback Machine 历史记录。",
        "profile": "网站资料", "description": "网站描述",
        "address": "地址", "site_title": "网站名称",
        "not_found": "未找到公开发布的信息。",
        "audit_report": "SEO 检测报告", "score": "技术检测得分",
        "passed": "通过的检测", "http": "HTTP 状态",
        "checked_links": "已检查链接", "checks": "技术检查",
        "page_info": "页面信息", "title": "标题",
        "meta_description": "Meta 描述", "canonical": "规范网址",
        "images": "图片", "missing_alt": "缺少 alt 的图片",
        "print": "打印 / 保存为 PDF", "new_audit": "新检测",
        "saved_reports": "已保存的报告", "pagespeed_title": "Google PageSpeed Insights",
        "link_check": "链接检查", "domain_age": "域名注册时间",
        "wayback": "Wayback Machine 历史", "traffic": "流量估算",
        "check": "项目", "result": "结果", "details": "详情",
        "pass": "通过", "review": "需检查", "anchor": "链接文本",
        "status": "HTTP 状态", "date": "日期", "website": "网站",
        "no_reports": "暂无已保存报告。", "latest_reports": "此处显示最近 100 份报告。",
        "start_new": "开始新检测", "disclaimer": "此分数不是 Google 评分，也不保证搜索排名。",
        "invalid": "网址无效", "fetch_error": "无法访问网站", "try_again": "重试",
        "generated": "报告生成时间", "creation_date": "域名创建日期",
        "estimated_age": "估算年龄", "year": "年份", "records": "返回记录数",
        "no_links": "未检查链接。", "not_available": "不可用",
        "footer": "技术诊断工具；外部服务可能暂时不可用。",
        "language": "语言", "robots": "robots.txt", "sitemap": "站点地图",
    },
}


def tr(lang, key):
    return TEXT.get(lang, TEXT["en"]).get(key, TEXT["en"].get(key, key))


def e(value):
    return escape(str(value if value is not None else ""), quote=True)


# ============================================================
# DATABASE
# ============================================================

def db_connection():
    connection = sqlite3.connect(DATABASE_PATH, timeout=20)
    connection.row_factory = sqlite3.Row
    return connection


def init_database():
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
# MODERN DESIGN / LANGUAGE SELECTOR
# ============================================================

def page_template(title, body, lang="en"):
    lang = lang if lang in LANGUAGES else "en"
    direction = "rtl" if lang == "ar" else "ltr"
    options = "".join(
        f'<option value="{code}" {"selected" if code == lang else ""}>{e(name)}</option>'
        for code, name in LANGUAGES.items()
    )

    return f"""<!doctype html>
<html lang="{lang}" dir="{direction}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#101b38">
<meta name="description" content="EAQ SEO Audit: technical website diagnostics, SEO checks, links and performance.">
<title>{e(title)} | EAQ SEO Audit</title>
<style>
:root {{
 --bg:#f4f7fc;--card:#fff;--text:#18243c;--muted:#68758b;
 --primary:#4263eb;--border:#e1e8f2;--green:#16804a;
 --red:#bd3434;--orange:#a45a00;
}}
*{{box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{margin:0;font-family:Inter,Arial,Helvetica,sans-serif;background:var(--bg);
 color:var(--text);line-height:1.7;overflow-x:hidden}}
header{{position:relative;overflow:hidden;color:white;
 background:linear-gradient(125deg,#101b38 0%,#173b75 55%,#3d5be8 100%);
 padding:20px 18px 35px}}
header:be
