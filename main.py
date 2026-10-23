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
header:before,header:after{{content:"";position:absolute;border-radius:50%;pointer-events:none}}
header:before{{width:290px;height:290px;border:48px solid rgba(255,255,255,.06);
 top:-160px;right:-55px}}
header:after{{width:180px;height:180px;border:28px solid rgba(125,177,255,.18);
 bottom:-130px;left:12%}}
nav,.container{{max-width:1160px;margin:auto}}
nav{{position:relative;z-index:1;display:flex;align-items:center;justify-content:space-between;
 gap:16px;flex-wrap:wrap}}
.brand{{font-size:22px;font-weight:900;letter-spacing:.4px;color:#fff;text-decoration:none}}
.brand span{{color:#9fc3ff}}
.navlinks{{display:flex;align-items:center;gap:14px;flex-wrap:wrap}}
.navlinks a{{color:#fff;text-decoration:none;font-size:14px;font-weight:700}}
.langbox{{display:flex;align-items:center;gap:7px;font-size:12px;color:#dbe8ff}}
.langbox select{{width:auto;min-width:108px;padding:7px 9px;border:1px solid #ffffff55;
 border-radius:9px;background:#132e5c;color:white;font-size:13px}}
.container{{padding:27px 17px 55px}}
.card{{position:relative;background:var(--card);border:1px solid var(--border);
 border-radius:19px;padding:clamp(17px,3vw,27px);margin-bottom:19px;
 box-shadow:0 9px 28px rgba(21,42,86,.055);overflow:hidden}}
.hero{{background:linear-gradient(145deg,#fff 0%,#f1f5ff 100%);}}
.hero:after{{content:"";position:absolute;width:210px;height:210px;border-radius:50%;
 border:35px solid rgba(66,99,235,.07);right:-95px;bottom:-115px;pointer-events:none}}
h1,h2,h3{{line-height:1.3;letter-spacing:-.25px}}
h1{{font-size:clamp(26px,4vw,42px);margin:12px 0}}
h2{{font-size:22px;margin:0 0 16px}}
h3{{font-size:17px;margin-top:0}}
p{{overflow-wrap:anywhere}}
.muted{{color:var(--muted)}}
.small{{font-size:13px}}
label{{display:block;font-weight:700;margin:12px 0 6px}}
input[type=url],input[type=text],input[type=number],select:not(.language-select){{
 width:100%;border:1px solid #cbd5e1;border-radius:11px;padding:13px;
 background:#fff;font-size:16px;color:var(--text);max-width:100%}}
input:focus,select:focus{{outline:3px solid #4263eb22;border-color:var(--primary)}}
button,.button{{border:0;border-radius:11px;background:linear-gradient(110deg,#4263eb,#2852c7);
 color:#fff;padding:12px 19px;font-size:15px;font-weight:800;cursor:pointer;
 text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:8px}}
button:hover,.button:hover{{filter:brightness(1.06);transform:translateY(-1px)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:15px}}
.metric{{background:linear-gradient(145deg,#f9fbff,#f2f6ff);border:1px solid var(--border);
 padding:17px;border-radius:14px;min-width:0}}
.metric strong{{font-size:27px;display:block;overflow-wrap:anywhere}}
.iconcircle{{width:43px;height:43px;display:flex;align-items:center;justify-content:center;
 border-radius:14px;background:#e9efff;color:#3154cf;font-size:21px;margin-bottom:12px}}
.pill{{display:inline-block;padding:5px 10px;border-radius:30px;background:#e8efff;
 color:#234bb5;font-size:12px;font-weight:800;letter-spacing:.3px}}
table{{width:100%;border-collapse:collapse}}
th,td{{padding:11px 9px;border-bottom:1px solid var(--border);text-align:start;
 vertical-align:top;overflow-wrap:anywhere}}
th{{background:#f2f5fb;font-size:13px}}
.table-wrap{{overflow-x:auto;border-radius:10px}}
.status-pass{{color:var(--green);font-weight:800}}
.status-fail{{color:var(--red);font-weight:800}}
.status-warn{{color:var(--orange);font-weight:800}}
.notice{{background:#fff8e7;border:1px solid #f1d28a;border-radius:12px;padding:13px 15px}}
footer{{position:relative;overflow:hidden;text-align:center;color:var(--muted);padding:25px 14px}}
a{{color:var(--primary)}}
.feature-card{{transition:transform .2s,box-shadow .2s}}
.feature-card:hover{{transform:translateY(-3px);box-shadow:0 13px 28px rgba(21,42,86,.09)}}
@media(max-width:620px){{
 header{{padding:17px 14px 27px}}
 nav{{align-items:flex-start}}
 .navlinks{{gap:11px}}
 .navlinks a{{font-size:13px}}
 .container{{padding:17px 12px 35px}}
 .card{{border-radius:15px}}
}}
@media print{{
 header,.no-print,footer{{display:none!important}}
 body{{background:white}}
 .card{{box-shadow:none;break-inside:avoid}}
 .container{{max-width:none;padding:0}}
}}
</style>
</head>
<body>
<header>
<nav>
 <a class="brand" href="/?lang={lang}">EAQ <span>SEO AUDIT</span></a>
 <div class="navlinks">
  <a href="/?lang={lang}">{e(tr(lang,"home"))}</a>
  <a href="/reports?lang={lang}">{e(tr(lang,"reports"))}</a>
  <span class="langbox">
   <label for="language-select" style="margin:0;font-weight:400">{e(tr(lang,"language"))}</label>
   <select id="language-select" class="language-select" aria-label="{e(tr(lang,"language"))}"
    onchange="if(this.value)location.href='?lang='+encodeURIComponent(this.value)">
    {options}
   </select>
  </span>
 </div>
</nav>
</header>
<main class="container">{body}</main>
<footer>EAQ SEO Audit v{APP_VERSION} · {e(tr(lang,"footer"))}</footer>
</body>
</html>"""


# ============================================================
# SAFE URL FETCHING
# ============================================================

def normalize_url(raw_url):
    raw_url = (raw_url or "").strip()
    if not raw_url:
        raise ValueError("Please enter a website URL.")
    if len(raw_url) > 2048:
        raise ValueError("The URL is too long.")
    if not re.match(r"^https?://", raw_url, re.I):
        raw_url = "https://" + raw_url

    parsed = urlparse(raw_url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise ValueError("Only valid HTTP and HTTPS URLs are supported.")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing username or password are not allowed.")
    if parsed.port and parsed.port not in (
        (80,) if parsed.scheme.lower() == "http" else (443,)
    ):
        raise ValueError("Only standard HTTP/HTTPS ports are allowed.")

    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Local or private hostnames are not allowed.")

    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            raise ValueError("Private or reserved IP addresses are not allowed.")
    except ValueError as exc:
        if "not allowed" in str(exc):
            raise

    return raw_url


def hostname_is_public(host):
    host = (host or "").rstrip(".").lower()
    if not host or host.endswith((".localhost", ".local", ".internal")):
        return False

    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        pass

    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError):
        return False

    if not addresses:
        return False

    for item in addresses:
        try:
            if not ipaddress.ip_address(item[4][0]).is_global:
                return False
        except ValueError:
            return False
    return True


def safe_get(raw_url, timeout=REQUEST_TIMEOUT, max_bytes=MAX_HTML_BYTES):
    current_url = normalize_url(raw_url)
    session = requests.Session()
    session.trust_env = False

    try:
        for _ in range(MAX_REDIRECTS + 1):
            parsed = urlparse(current_url)
            if not hostname_is_public(parsed.hostname):
                raise ValueError("The hostname is private, reserved, or cannot be safely resolved.")

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
                current_url = normalize_url(next_url)
                continue

            content = bytearray()
            for chunk in response.iter_content(chunk_size=16384):
                if not chunk:
                    continue
                remaining = max_bytes - len(content)
                content.extend(chunk[:remaining])
                if len(content) >= max_bytes:
                    break

            response._content = bytes(content)
            response._content_consumed = True
            return response

        raise ValueError("Too many redirects.")
    finally:
        session.close()


def fetch_text(url, timeout=8, max_bytes=300000):
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
# WEBSITE PROFILE: DESCRIPTION, NAME, ADDRESS, SERVICES
# ============================================================

def extract_website_profile(soup, page_url):
    title_tag = soup.find("title")
    page_title = title_tag.get_text(" ", strip=True) if title_tag else ""

    meta_desc = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    description = meta_desc.get("content", "").strip() if meta_desc else ""

    og_title = soup.find("meta", property="og:title")
    og_desc = soup.find("meta", property="og:description")
    site_name = og_title.get("content", "").strip() if og_title else ""
    if not site_name:
        site_name = page_title

    if not description and og_desc:
        description = og_desc.get("content", "").strip()

    if not description:
        meta_about = soup.find(
            "meta",
            attrs={"name": re.compile("^(application-name|og:site_name)$", re.I)}
        )
        if meta_about:
            site_name = site_name or meta_about.get("content", "").strip()

    address_parts = []
    services = []
    organizations = []
    jsonld_names = []
    jsonld_descriptions = []

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw or len(raw) > 500000:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        objects = data if isinstance(data, list) else [data]
        queue = list(objects)

        while queue:
            item = queue.pop(0)
            if isinstance(item, list):
                queue.extend(item)
                continue
            if not isinstance(item, dict):
                continue

            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)

            types = item.get("@type", [])
            if isinstance(types, str):
                types = [types]

            name = item.get("name")
            desc = item.get("description")
            if name and isinstance(name, str):
                jsonld_names.append(name.strip())
            if desc and isinstance(desc, str):
                jsonld_descriptions.append(desc.strip())

            if any(t in str(types) for t in (
                "Organization", "LocalBusiness", "Corporation",
                "ProfessionalService", "Store", "MedicalOrganization"
            )):
                if name:
                    organizations.append(name.strip())

                address = item.get("address")
                if isinstance(address, dict):
                    fields = [
                        address.get("streetAddress"),
                        address.get("addressLocality"),
                        address.get("addressRegion"),
                        address.get("postalCode"),
                        address.get("addressCountry")
                    ]
                    value = ", ".join(str(x).strip() for x in fields if x)
                    if value:
                        address_parts.append(value)
                elif isinstance(address, str) and address.strip():
                    address_parts.append(address.strip())

            for key in ("makesOffer", "hasOfferCatalog", "serviceType"):
                value = item.get(key)
                if isinstance(value, str):
                    services.append(value.strip())
                elif isinstance(value, dict):
                    if value.get("name"):
                        services.append(str(value["name"]).strip())
                    elements = value.get("itemListElement", [])
                    if isinstance(elements, list):
                        for element in elements:
                            if isinstance(element, dict) and element.get("name"):
                                services.append(str(element["name"]).strip())

    if not site_name and organizations:
        site_name = organizations[0]
    if not site_name and jsonld_names:
        site_name = jsonld_names[0]
    if not description and jsonld_descriptions:
        description = jsonld_descriptions[0]

    headings = []
    for tag in soup.find_all(["h1", "h2", "h3"]):
        text = tag.get_text(" ", strip=True)
        if text and text not in headings:
            headings.append(text[:180])
        if len(headings) >= 12:
            break

    # Fallback: use meaningful visible text only when metadata is absent.
    if not description:
        paragraphs = []
        for p in soup.find_all("p"):
            value = p.get_text(" ", strip=True)
            if len(value) >= 55:
                paragraphs.append(value)
            if len(paragraphs) >= 2:
                break
        if paragraphs:
            description = " ".join(paragraphs)[:700]

    return {
        "url": page_url,
        "name": site_name[:250],
        "description": description[:1200],
        "address": address_parts[0][:500] if address_parts else "",
        "headings": headings,
        "services": list(dict.fromkeys(services))[:12],
        "address_source": "Structured data (Schema.org)" if address_parts else "",
        "note": (
            "Information extracted from public page metadata, visible text and structured data. "
            "Missing details are not inferred."
        )
    }


# ============================================================
# TECHNICAL SEO AUDIT
# ============================================================

def add_check(checks, name, passed, details, severity="warning"):
    checks.append({
        "name": name,
        "passed": bool(passed),
        "details": str(details),
        "severity": severity
    })


def run_technical_audit(url):
    response = safe_get(url)
    try:
        final_url = response.url
        status = response.status_code
        content_type = response.headers.get("Content-Type", "")
        html = response.text[:MAX_HTML_BYTES]
    finally:
        response.close()

    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else ""

    desc_tag = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    description = desc_tag.get("content", "").strip() if desc_tag else ""

    canonical_tag = soup.find(
        "link",
        attrs={"rel": lambda value: value and "canonical" in value}
    )
    canonical = canonical_tag.get("href", "").strip() if canonical_tag else ""

    h1s = soup.find_all("h1")
    images = soup.find_all("img")
    missing_alt = [img for img in images if not img.has_attr("alt")]
    viewport = soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)})
    charset = soup.find("meta", attrs={"charset": True})
    charset_value = charset.get("charset", "") if charset else ""

    if not charset_value:
        content_meta = soup.find(
            "meta", attrs={"http-equiv": re.compile("^content-type$", re.I)}
        )
        if content_meta:
            charset_value = content_meta.get("content", "")

    links = []
    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue
        absolute = urljoin(final_url, href)
        if urlparse(absolute).scheme in ("http", "https"):
            links.append({
                "url": absolute,
                "text": tag.get_text(" ", strip=True)[:160]
            })

    robots_url = urljoin(final_url, "/robots.txt")
    sitemap_url = urljoin(final_url, "/sitemap.xml")
    robots = {"url": robots_url, "status": None, "text": ""}
    sitemap = {"url": sitemap_url, "status": None, "text": ""}

    for item, target in ((robots, robots_url), (sitemap, sitemap_url)):
        try:
            result = fetch_text(target, timeout=8, max_bytes=300000)
            item.update({
                "url": result["url"],
                "status": result["status"],
                "text": result["text"][:100000]
            })
        except Exception as exc:
            item["error"] = str(exc)[:200]

    sitemap_valid = False
    if sitemap["text"].strip():
        try:
            ElementTree.fromstring(sitemap["text"])
            sitemap_valid = True
        except ElementTree.ParseError:
            pass

    checks = []
    add_check(checks, "HTTP response", 200 <= status < 400, f"HTTP {status}", "critical")
    add_check(checks, "HTML content type", "html" in content_type.lower(), content_type or "Missing")
    add_check(checks, "Page title", bool(title), title or "No title tag")
    add_check(checks, "Title length", 30 <= len(title) <= 60,
              f"{len(title)} characters; common guideline: 30–60")
    add_check(checks, "Meta description", bool(description), description or "Not found")
    add_check(checks, "Meta description length", 70 <= len(description) <= 160,
              f"{len(description)} characters; common guideline: 70–160")
    add_check(checks, "H1 heading", len(h1s) >= 1, f"{len(h1s)} H1 heading(s)")
    add_check(checks, "Single H1", len(h1s) == 1,
              f"{len(h1s)} H1 heading(s); multiple H1s are not automatically an error")
    add_check(checks, "Canonical URL", bool(canonical), canonical or "Not found")
    add_check(checks, "Viewport meta", viewport is not None,
              "Found" if viewport else "Not found")
    add_check(checks, "Character encoding",
              bool(charset_value) or "charset=" in content_type.lower(),
              charset_value or content_type or "Not detected")
    add_check(checks, "Image alt attributes", len(missing_alt) == 0,
              f"{len(missing_alt)} of {len(images)} images lack alt attributes")
    add_check(checks, "HTTPS", urlparse(final_url).scheme.lower() == "https", final_url)
    add_check(checks, "robots.txt", robots["status"] == 200,
              f"HTTP {robots['status']}" if robots["status"] else robots.get("error", "Unavailable"))
    add_check(checks, "Sitemap XML", sitemap_valid,
              f"HTTP {sitemap['status']}; valid XML: {sitemap_valid}")

    passed = sum(1 for check in checks if check["passed"])
    score = round((passed / len(checks)) * 100) if checks else 0

    profile = extract_website_profile(soup, final_url)

    return {
        "final_url": final_url,
        "http_status": status,
        "score": score,
        "passed_checks": passed,
        "total_checks": len(checks),
        "checks": checks,
        "profile": profile,
        "details": {
            "title": title,
            "title_length": len(title),
            "description": description,
            "description_length": len(description),
            "canonical": canonical,
            "image_count": len(images),
            "images_missing_alt": len(missing_alt),
            "h1": [h.get_text(" ", strip=True)[:180] for h in h1s[:10]],
            "links": links,
            "robots": {
                "url": robots["url"], "status": robots["status"],
                "error": robots.get("error"), "preview": robots["text"][:1000]
            },
            "sitemap": {
                "url": sitemap["url"], "status": sitemap["status"],
                "error": sitemap.get("error"), "valid_xml": sitemap_valid
            }
        }
    }


# ============================================================
# LINK CHECKING
# ============================================================

def check_links(links):
    results = []
    seen = set()

    for link in links[:MAX_LINKS_TO_CHECK]:
        target = link["url"]
        if target in seen:
            continue
        seen.add(target)

        item = {"url": target, "text": link.get("text", ""), "status": None}
        try:
            response = safe_get(target, timeout=8, max_bytes=1000)
            item["status"] = response.status_code
            response.close()

            if 200 <= item["status"] < 400:
                item["category"] = "ok"
                item["result"] = "Reachable"
            elif item["status"] in (401, 403, 429):
                item["category"] = "unknown"
                item["result"] = "Access restricted / rate limited; verify manually"
            else:
                item["category"] = "broken"
                item["result"] = "HTTP response requires review"
        except Exception as exc:
            item["category"] = "unknown"
            item["result"] = "Could not verify: " + str(exc)[:160]

        results.append(item)

        # Avoid hammering external sites.
        time.sleep(0.15)

    return results


# ============================================================
# EXTERNAL DATA
# ============================================================

def get_pagespeed(url, strategy):
    endpoint = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    try:
        response = requests.get(
            endpoint,
            params={"url": url, "strategy": strategy, "category": "performance"},
            timeout=35,
            headers={"User-Agent": USER_AGENT}
        )

        if response.status_code != 200:
            if response.status_code == 429:
                message = "Google PageSpeed rate limit reached (HTTP 429). Try again later."
            elif response.status_code in (401, 403):
                message = f"Google PageSpeed denied this request (HTTP {response.status_code})."
            else:
                message = f"PageSpeed returned HTTP {response.status_code}."
            return {"available": False, "error": message}

        data = response.json()
        lighthouse = data.get("lighthouseResult", {})
        categories = lighthouse.get("categories", {})
        audits = lighthouse.get("audits", {})

        scores = {}
        for key, category in categories.items():
            value = category.get("score")
            scores[key] = round(value * 100) if isinstance(value, (int, float)) else None

        metrics = {}
        for key in (
            "first-contentful-paint", "largest-contentful-paint",
            "speed-index", "total-blocking-time", "cumulative-layout-shift"
        ):
            item = audits.get(key, {})
            metrics[key] = {
                "title": item.get("title", key),
                "display_value": item.get("displayValue", "Not reported")
            }

        return {
            "available": True,
            "strategy": strategy,
            "scores": scores,
            "metrics": metrics
        }

    except Exception as exc:
        return {"available": False, "error": "PageSpeed request failed: " + str(exc)[:220]}


def get_domain_age(url):
    domain = urlparse(url).hostname or ""
    try:
        response = requests.get(
            f"https://rdap.org/domain/{quote(domain)}",
            timeout=12,
            headers={"User-Agent": USER_AGENT, "Accept": "application/rdap+json"}
        )
        if response.status_code != 200:
            return {"available": False, "domain": domain,
                    "error": f"RDAP returned HTTP {response.status_code}"}

        data = response.json()
        created = None
        for event in data.get("events", []):
            if event.get("eventAction", "").lower() in ("registration", "registered"):
                created = event.get("eventDate")
                break

        if not created:
            return {"available": False, "domain": domain,
                    "error": "Registration date was not returned by RDAP."}

        date = datetime.fromisoformat(created.replace("Z", "+00:00"))
        days = max(0, (datetime.now(timezone.utc) - date).days)
        return {
            "available": True, "domain": domain,
            "created_at": date.date().isoformat(),
            "age_days": days, "age_years": round(days / 365.2425, 2)
        }
    except Exception as exc:
        return {"available": False, "domain": domain, "error": str(exc)[:220]}


def get_wayback_history(url):
    domain = urlparse(url).hostname or ""
    endpoint = "https://web.archive.org/cdx/search/cdx"

    try:
        response = requests.get(
            endpoint,
            params={
                "url": domain,
                "matchType": "domain",
                "output": "json",
                "fl": "timestamp",
                "filter": "statuscode:200",
                "collapse": "timestamp:4",
                "limit": "5000"
            },
            timeout=20,
            headers={"User-Agent": USER_AGENT}
        )

        if response.status_code != 200:
            return {"available": False, "error": f"Wayback returned HTTP {response.status_code}"}

        rows = response.json()
        years = {}
        for row in rows[1:]:
            if row and len(row[0]) >= 4 and row[0][:4].isdigit():
                year = row[0][:4]
                years[year] = years.get(year, 0) + 1

        return {
            "available": True, "domain": domain,
            "years": dict(sorted(years.items())),
            "note": "Counts reflect returned snapshots and may not include every archive record."
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)[:220]}


def get_traffic_estimate(url):
    domain = urlparse(url).hostname or ""
    if not os.getenv("SIMILARWEB_API_KEY"):
        return {
            "available": False,
            "domain": domain,
            "message": (
                "Traffic estimates are not configured. A valid traffic-data API "
                "subscription and a verified endpoint are required. No estimate is invented."
            )
        }

    return {
        "available": False,
        "domain": domain,
        "message": (
            "An API key is configured, but this version does not assume an endpoint "
            "or invent traffic figures. Configure the endpoint for the specific subscription."
        )
    }


# ============================================================
# REPORT GENERATION AND STORAGE
# ============================================================

def run_full_audit(url, do_pagespeed=True, do_links=True):
    technical = run_technical_audit(url)
    links = check_links(technical["details"].get("links", [])) if do_links else []

    pagespeed = {
        "mobile": get_pagespeed(technical["final_url"], "mobile") if do_pagespeed
                  else {"available": False, "error": "Not requested"},
        "desktop": get_pagespeed(technical["final_url"], "desktop") if do_pagespeed
                   else {"available": False, "error": "Not requested"}
    }

    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "requested_url": url,
        "final_url": technical["final_url"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "score": technical["score"],
        "technical": technical,
        "links": links,
        "pagespeed": pagespeed,
        "domain_age": get_domain_age(technical["final_url"]),
        "wayback": get_wayback_history(technical["final_url"]),
        "traffic": get_traffic_estimate(technical["final_url"])
    }


def save_report(report):
    with db_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO reports (url, created_at, score, report_json) VALUES (?, ?, ?, ?)",
            (
                report.get("final_url", report.get("requested_url", "")),
                report.get("created_at", datetime.now(timezone.utc).isoformat()),
                int(report.get("score", 0)),
                json.dumps(report, ensure_ascii=False)
            )
        )
        connection.commit()
        return cursor.lastrowid


# ============================================================
# LOCALIZED REPORT RENDERING
# ============================================================

def render_checks(checks, lang):
    rows = []
    for item in checks:
        label = tr(lang, "pass") if item.get("passed") else tr(lang, "review")
        css = "status-pass" if item.get("passed") else "status-warn"
        rows.append(
            f"<tr><td>{e(item.get('name'))}</td>"
            f"<td class='{css}'>{e(label)}</td>"
            f"<td>{e(item.get('details'))}</td></tr>"
        )

    return (
        "<div class='table-wrap'><table><thead><tr>"
        f"<th>{e(tr(lang,'check'))}</th><th>{e(tr(lang,'result'))}</th>"
        f"<th>{e(tr(lang,'details'))}</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table></div>"
    )


def render_profile(profile, lang):
    headings = profile.get("headings", [])
    services = profile.get("services", [])

    heading_html = (
        "<ul>" + "".join(f"<li>{e(x)}</li>" for x in headings) + "</ul>"
        if headings else f"<p class='muted'>{e(tr(lang,'not_found'))}</p>"
    )
    services_html = (
        "<ul>" + "".join(f"<li>{e(x)}</li>" for x in services) + "</ul>"
        if services else f"<p class='muted'>{e(tr(lang,'not_found'))}</p>"
    )

    name = profile.get("name") or tr(lang, "not_found")
    description = profile.get("description") or tr(lang, "not_found")
    address = profile.get("address") or tr(lang, "not_found")
    address_source = profile.get("address_source", "")

    return f"""
    <div class="grid">
      <div class="metric"><h3>{e(tr(lang,'site_title'))}</h3><p>{e(name)}</p></div>
      <div class="metric"><h3>{e(tr(lang,'address'))}</h3><p>{e(address)}</p>
        <p class="muted small">{e(address_source)}</p></div>
    </div>
    <h3>{e(tr(lang,'description'))}</h3><p>{e(description)}</p>
    <h3>Topics / Services</h3>{services_html}
    <h3>Visible headings</h3>{heading_html}
    <p class="muted small">{e(profile.get('note',''))}</p>
    """


def render_pagespeed(data, lang):
    cards = []
    for device in ("mobile", "desktop"):
        result = data.get(device, {})
        title = device.title()

        if not result.get("available"):
            cards.append(
                f"<div class='metric'><h3>{e(title)}</h3>"
                f"<p class='muted'>{e(result.get('error','Unavailable'))}</p></div>"
            )
            continue

        scores = result.get("scores", {})
        score_html = "".join(
            f"<p>{e(key.replace('_',' ').title())}: "
            f"<strong>{e(value if value is not None else 'N/A')}</strong></p>"
            for key, value in scores.items()
        )
        metrics_html = "".join(
            f"<p>{e(value.get('title',key))}: {e(value.get('display_value','Not reported'))}</p>"
            for key, value in result.get("metrics", {}).items()
        )
        cards.append(f"<div class='metric'><h3>{e(title)}</h3>{score_html}{metrics_html}</div>")

    return "<div class='grid'>" + "".join(cards) + "</div>"


def render_links(links, lang):
    if not links:
        return f"<p class='muted'>{e(tr(lang,'no_links'))}</p>"

    rows = []
    for item in links:
        category = item.get("category", "unknown")
        css = "status-pass" if category == "ok" else (
            "status-fail" if category == "broken" else "status-warn"
        )
        status = item.get("status")
        status = status if status is not None else tr(lang, "not_available")
        rows.append(
            f"<tr><td>{e(item.get('text') or '(no anchor text)')}</td>"
            f"<td><a href='{e(item.get('url'))}' target='_blank' rel='noopener noreferrer'>"
            f"{e(item.get('url'))}</a></td><td>{e(status)}</td>"
            f"<td class='{css}'>{e(item.get('result'))}</td></tr>"
        )

    return (
        "<div class='table-wrap'><table><thead><tr>"
        f"<th>{e(tr(lang,'anchor'))}</th><th>URL</th>"
        f"<th>{e(tr(lang,'status'))}</th><th>{e(tr(lang,'result'))}</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def render_domain_age(data, lang):
    if not data.get("available"):
        return f"<p class='status-warn'>{e(tr(lang,'not_available'))}: {e(data.get('error',''))}</p>"
    return (
        f"<p><strong>{e(tr(lang,'website'))}:</strong> {e(data.get('domain'))}</p>"
        f"<p><strong>{e(tr(lang,'creation_date'))}:</strong> {e(data.get('created_at'))}</p>"
        f"<p><strong>{e(tr(lang,'estimated_age'))}:</strong> "
        f"{e(data.get('age_years'))} years ({e(data.get('age_days'))} days)</p>"
    )


def render_wayback(data, lang):
    if not data.get("available"):
        return f"<p class='status-warn'>{e(tr(lang,'not_available'))}: {e(data.get('error',''))}</p>"

    years = data.get("years", {})
    if not years:
        return f"<p class='muted'>{e(tr(lang,'not_found'))}</p>"

    rows = "".join(
        f"<tr><td>{e(year)}</td><td>{e(count)}</td></tr>"
        for year, count in years.items()
    )
    return (
        "<div class='table-wrap'><table><thead><tr>"
        f"<th>{e(tr(lang,'year'))}</th><th>{e(tr(lang,'records'))}</th>"
        "</tr></thead><tbody>" + rows + "</tbody></table></div>"
        f"<p class='muted small'>{e(data.get('note',''))}</p>"
    )


def render_report(report, report_id=None, lang="en"):
    lang = lang if lang in LANGUAGES else "en"
    technical = report.get("technical", {})
    details = technical.get("details", {})
    profile = technical.get("profile", {})

    report_id_html = (
        f"<p class='muted'>Report ID: {e(report_id)}</p>" if report_id is not None else ""
    )

    body = f"""
    <div class="card">
      <div class="no-print" style="display:flex;gap:10px;flex-wrap:wrap">
        <button onclick="window.print()">▣ {e(tr(lang,'print'))}</button>
        <a class="button" href="/?lang={lang}">{e(tr(lang,'new_audit'))}</a>
        <a class="button" href="/reports?lang={lang}">{e(tr(lang,'saved_reports'))}</a>
      </div>
      <span class="pill">EAQ · SEO AUDIT</span>
      <h1>{e(tr(lang,'audit_report'))}</h1>
      {report_id_html}
      <p><strong>{e(tr(lang,'website'))}:</strong>
        <a href="{e(report.get('final_url'))}" target="_blank" rel="noopener noreferrer">
        {e(report.get('final_url'))}</a></p>
      <p><strong>{e(tr(lang,'generated'))}:</strong> {e(report.get('created_at'))}</p>
      <div class="grid">
        <div class="metric"><span class="muted">{e(tr(lang,'score'))}</span>
          <strong>{e(report.get('score',0))}/100</strong></div>
        <div class="metric"><span class="muted">{e(tr(lang,'passed'))}</span>
          <strong>{e(technical.get('passed_checks',0))}/{e(technical.get('total_checks',0))}</strong></div>
        <div class="metric"><span class="muted">{e(tr(lang,'http'))}</span>
          <strong>{e(technical.get('http_status','N/A'))}</strong></div>
        <div class="metric"><span class="muted">{e(tr(lang,'checked_links'))}</span>
          <strong>{e(len(report.get('links',[])))}</strong></div>
      </div>
      <p class="notice">{e(tr(lang,'disclaimer'))}</p>
    </div>

    <div class="card">
      <h2>◎ {e(tr(lang,'profile'))}</h2>
      {render_profile(profile, lang)}
    </div>

    <div class="card">
      <h2>✓ {e(tr(lang,'checks'))}</h2>
      {render_checks(technical.get('checks',[]), lang)}
    </div>

    <div class="card">
      <h2>▤ {e(tr(lang,'page_info'))}</h2>
      <div class="grid">
        <div class="metric"><h3>{e(tr(lang,'title'))}</h3>
          <p>{e(details.get('title') or tr(lang,'not_found'))}</p>
          <p class="muted">{e(details.get('title_length',0))} characters</p></div>
        <div class="metric"><h3>{e(tr(lang,'meta_description'))}</h3>
          <p>{e(details.get('description') or tr(lang,'not_found'))}</p>
          <p class="muted">{e(details.get('description_length',0))} characters</p></div>
        <div class="metric"><h3>{e(tr(lang,'canonical'))}</h3>
          <p>{e(details.get('canonical') or tr(lang,'not_found'))}</p></div>
        <div class="metric"><h3>{e(tr(lang,'images'))}</h3>
          <p>Total: {e(details.get('image_count',0))}</p>
          <p>{e(tr(lang,'missing_alt'))}: {e(details.get('images_missing_alt',0))}</p></div>
      </div>
    </div>

    <div class="card">
      <h2>⚡ {e(tr(lang,'pagespeed_title'))}</h2>
      <p class="muted">Scores are provided by Google when its service accepts the request.</p>
      {render_pagespeed(report.get('pagespeed',{}), lang)}
    </div>

    <div class="card">
      <h2>↗ {e(tr(lang,'link_check'))}</h2>
      <p class="muted">HTTP 403, 429, access restrictions and timeouts do not necessarily mean a link is broken.</p>
      {render_links(report.get('links',[]), lang)}
    </div>

    <div class="card">
      <h2>◷ {e(tr(lang,'domain_age'))}</h2>
      {render_domain_age(report.get('domain_age',{}), lang)}
    </div>

    <div class="card">
      <h2>◌ {e(tr(lang,'wayback'))}</h2>
      {render_wayback(report.get('wayback',{}), lang)}
    </div>

    <div class="card">
      <h2>▥ {e(tr(lang,'traffic'))}</h2>
      <p>{e(report.get('traffic',{}).get('message','No traffic data available.'))}</p>
    </div>
    """
    return page_template(tr(lang, "audit_report"), body, lang)


# ============================================================
# ROUTES
# ============================================================

@app.get("/", response_class=HTMLResponse)
def home(lang: str = "en"):
    lang = lang if lang in LANGUAGES else "en"

    body = f"""
    <section class="card hero">
      <span class="pill">TECHNICAL WEBSITE ANALYSIS</span>
      <h1>{e(tr(lang,'hero'))}</h1>
      <p class="muted">{e(tr(lang,'intro'))}</p>
      <form action="/audit" method="post">
        <input type="hidden" name="lang" value="{lang}">
        <label for="url">{e(tr(lang,'url'))}</label>
        <input id="url" name="url" type="url" required maxlength="2048"
          placeholder="{e(tr(lang,'placeholder'))}" autocomplete="url">
        <label style="font-weight:500">
          <input type="checkbox" name="do_pagespeed" value="yes" checked>
          {e(tr(lang,'pagespeed'))}
        </label>
        <label style="font-weight:500">
          <input type="checkbox" name="do_links" value="yes" checked>
          {e(tr(lang,'links'))}
        </label>
        <p><button type="submit">⌕ {e(tr(lang,'start'))}</button></p>
      </form>
      <p class="small muted">{e(tr(lang,'disclaimer'))}</p>
    </section>

    <h2>{e(tr(lang,'features'))}</h2>
    <div class="grid">
      <div class="card feature-card">
        <div class="iconcircle">⌕</div>
        <h3>{e(tr(lang,'technical'))}</h3>
        <p class="muted">{e(tr(lang,'technical_desc'))}</p>
      </div>
      <div class="card feature-card">
        <div class="iconcircle">⚡</div>
        <h3>{e(tr(lang,'speed'))}</h3>
        <p class="muted">{e(tr(lang,'speed_desc'))}</p>
      </div>
      <div class="card feature-card">
        <div class="iconcircle">◷</div>
        <h3>{e(tr(lang,'history'))}</h3>
        <p class="muted">{e(tr(lang,'history_desc'))}</p>
      </div>
    </div>

    <div class="card">
      <h2>{e(tr(lang,'saved_reports'))}</h2>
      <p class="muted">{e(tr(lang,'latest_reports'))}</p>
      <a class="button" href="/reports?lang={lang}">{e(tr(lang,'saved_reports'))} →</a>
    </div>
    """
    return page_template(APP_NAME, body, lang)


@app.post("/audit", response_class=HTMLResponse)
def audit(
    url: str = Form(...),
    lang: str = Form("en"),
    do_pagespeed: str = Form("yes"),
    do_links: str = Form("yes")
):
    lang = lang if lang in LANGUAGES else "en"

    try:
        normalized = normalize_url(url)
        report = run_full_audit(
            normalized,
            do_pagespeed=(do_pagespeed == "yes"),
            do_links=(do_links == "yes")
        )
        report_id = save_report(report)
        return HTMLResponse(render_report(report, report_id, lang))

    except ValueError as exc:
        body = f"""
        <div class="card">
          <h1>{e(tr(lang,'invalid'))}</h1>
          <p>{e(str(exc))}</p>
          <a class="button" href="/?lang={lang}">{e(tr(lang,'try_again'))}</a>
        </div>
        """
        return HTMLResponse(page_template(tr(lang, "invalid"), body, lang), status_code=400)

    except requests.RequestException as exc:
        body = f"""
        <div class="card">
          <h1>{e(tr(lang,'fetch_error'))}</h1>
          <p>{e(str(exc)[:400])}</p>
          <a class="button" href="/?lang={lang}">{e(tr(lang,'try_again'))}</a>
        </div>
        """
        return HTMLResponse(page_template(tr(lang, "fetch_error"), body, lang), status_code=502)

    except Exception as exc:
        body = f"""
        <div class="card">
          <h1>Audit error</h1>
          <p>An unexpected error interrupted the audit.</p>
          <p class="muted">{e(str(exc)[:400])}</p>
          <a class="button" href="/?lang={lang}">{e(tr(lang,'try_again'))}</a>
        </div>
        """
        return HTMLResponse(page_template("Audit error", body, lang), status_code=500)


@app.get("/reports", response_class=HTMLResponse)
def reports(lang: str = "en"):
    lang = lang if lang in LANGUAGES else "en"

    with db_connection() as connection:
        rows = connection.execute("""
            SELECT id, url, created_at, score FROM reports
            ORDER BY id DESC LIMIT 100
        """).fetchall()

    if rows:
        table_rows = "".join(
            "<tr>"
            f"<td>{e(row['id'])}</td>"
            f"<td><a href='/reports/{e(row['id'])}?lang={lang}'>{e(row['url'])}</a></td>"
            f"<td>{e(row['created_at'])}</td>"
            f"<td>{e(row['score'])}/100</td>"
            "</tr>"
            for row in rows
        )
        table = (
            "<div class='table-wrap'><table><thead><tr>"
            f"<th>ID</th><th>{e(tr(lang,'website'))}</th>"
            f"<th>{e(tr(lang,'date'))} (UTC)</th><th>{e(tr(lang,'score'))}</th>"
            "</tr></thead><tbody>" + table_rows + "</tbody></table></div>"
        )
    else:
        table = f"<p class='muted'>{e(tr(lang,'no_reports'))}</p>"

    body = f"""
    <div class="card">
      <h1>{e(tr(lang,'saved_reports'))}</h1>
      <p class="muted">{e(tr(lang,'latest_reports'))}</p>
      {table}
      <p><a class="button" href="/?lang={lang}">{e(tr(lang,'start_new'))}</a></p>
    </div>
    """
    return page_template(tr(lang, "saved_reports"), body, lang)


@app.get("/reports/{report_id}", response_class=HTMLResponse)
def report_detail(report_id: int, lang: str = "en"):
    lang = lang if lang in LANGUAGES else "en"

    with db_connection() as connection:
        row = connection.execute(
            "SELECT report_json FROM reports WHERE id = ?",
            (report_id,)
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Report not found")

    try:
        report = json.loads(row["report_json"])
    except (TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=500, detail="Saved report could not be read")

    return HTMLResponse(render_report(report, report_id, lang))


@app.get("/health")
def health():
    return JSONResponse({
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "time_utc": datetime.now(timezone.utc).isoformat()
    })


@app.get("/robots.txt", include_in_schema=False)
def app_robots():
    return HTMLResponse(
        "User-agent: *\nAllow: /\nDisallow: /health\n",
        media_type="text/plain"
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return RedirectResponse(
        url="https://www.google.com/s2/favicons?domain=github.com"
    )


@app.get("/api/report/{report_id}")
def report_json(report_id: int):
    with db_connection() as connection:
        row = connection.execute(
            "SELECT report_json FROM reports WHERE id = ?",
            (report_id,)
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Report not found")

    try:
        return JSONResponse(json.loads(row["report_json"]))
    except (TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=500, detail="Saved report could not be read")
