
import http.client
import ipaddress
import json
import socket
import ssl
import threading
import time
from collections import deque
from html import escape
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

APP_NAME = "EAQ SEO Audit"
APP_VERSION = "2.0.0"

MAX_URL_LENGTH = 2048
MAX_HTML_BYTES = 1_000_000
REQUEST_TIMEOUT = 8
MAX_REDIRECTS = 3
RATE_LIMIT = 5
RATE_WINDOW = 60
MAX_RATE_KEYS = 5000

app = FastAPI(title=APP_NAME, docs_url=None, redoc_url=None)
rate_history = {}
rate_lock = threading.Lock()

TEXT = {
    "en": {
        "tagline": "Analyze. Automate. Improve.",
        "heading": "Free Website SEO Checker",
        "intro": "Check important on-page SEO elements without creating an account.",
        "website": "Website URL",
        "location": "Business location (optional)",
        "location_hint": "Enter the real street address or city if you know it.",
        "manual": "Enter business location manually",
        "analyze": "Analyze Website",
        "rate_note": "Audits are rate-limited. This checklist is not a Google ranking score.",
        "report": "SEO Audit Report",
        "checks": "Detailed Checks",
        "passed": "checks passed",
        "score_note": "EAQ checklist score — not a Google ranking score.",
        "title": "Page title",
        "words": "Approximate word count",
        "internal": "Internal links",
        "external": "External links",
        "pass": "PASS",
        "review": "REVIEW",
        "priority": "Priority",
        "critical": "Important",
        "recommendation": "Recommendation",
        "http": "HTTP response",
        "https": "HTTPS",
        "description": "Meta description",
        "h1": "H1 heading",
        "alt": "Image alt attributes",
        "canonical": "Canonical URL",
        "viewport": "Mobile viewport",
        "robots": "Robots directive",
        "content": "Text content",
        "schema": "Structured data",
        "social": "Social sharing metadata",
        "lang_check": "HTML language",
        "links_check": "Link quality",
        "map": "Business Location",
        "no_location": "No verified business location was found. Enter the real address or city and run the audit again. A website URL is not a business address.",
        "location_used": "Location searched",
        "location_source": "Location source",
        "manual_source": "Manually entered location",
        "schema_source": "Structured data on the website",
        "metadata_source": "Geographic metadata on the website",
        "not_found": "Not found",
        "summary": "This audit checks selected on-page SEO elements only. It does not measure actual page speed, backlinks, search traffic, or Google rankings.",
        "rate_error": "Rate limit reached. Wait one minute before trying again.",
        "url_error": "Unable to analyze this URL",
        "generic_error": "The audit could not be completed. Please try again later.",
        "invalid_url": "Please enter a valid public website URL.",
        "download": "Print / Save as PDF",
        "print_hint": "To save this report as PDF, use your browser menu and choose Print or Save as PDF.",
        "score_explain": "The score reflects this limited checklist, not search-engine performance.",
        "yes": "Yes",
        "no": "No",
    },
    "ar": {
        "tagline": "حلّل. أتمت. حسّن.",
        "heading": "فحص SEO مجاني للمواقع",
        "intro": "افحص عناصر تحسين محركات البحث داخل الصفحة دون إنشاء حساب.",
        "website": "رابط الموقع",
        "location": "موقع النشاط التجاري (اختياري)",
        "location_hint": "أدخل العنوان الحقيقي أو المدينة إن كنت تعرفهما.",
        "manual": "إدخال موقع النشاط التجاري يدويًا",
        "analyze": "تحليل الموقع",
        "rate_note": "عدد عمليات الفحص محدود. هذه النتيجة ليست ترتيبًا من Google.",
        "report": "تقرير فحص SEO",
        "checks": "الفحوصات التفصيلية",
        "passed": "فحوصات ناجحة",
        "score_note": "نتيجة قائمة فحص EAQ وليست ترتيبًا من Google.",
        "title": "عنوان الصفحة",
        "words": "عدد الكلمات التقريبي",
        "internal": "الروابط الداخلية",
        "external": "الروابط الخارجية",
        "pass": "ناجح",
        "review": "يحتاج مراجعة",
        "priority": "الأولوية",
        "critical": "مهم",
        "recommendation": "التوصية",
        "http": "استجابة HTTP",
        "https": "اتصال HTTPS",
        "description": "وصف الصفحة",
        "h1": "عنوان H1",
        "alt": "النص البديل للصور",
        "canonical": "الرابط الأساسي Canonical",
        "viewport": "إعداد عرض الهاتف",
        "robots": "تعليمات Robots",
        "content": "محتوى النص",
        "schema": "البيانات المنظمة",
        "social": "بيانات المشاركة الاجتماعية",
        "lang_check": "لغة صفحة HTML",
        "links_check": "الروابط",
        "map": "موقع النشاط التجاري",
        "no_location": "لم يُعثر على موقع تجاري موثوق. أدخل العنوان الحقيقي أو المدينة وأعد الفحص. رابط الموقع الإلكتروني ليس عنوانًا تجاريًا.",
        "location_used": "الموقع المستخدم للبحث",
        "location_source": "مصدر الموقع",
        "manual_source": "موقع أدخله المستخدم",
        "schema_source": "بيانات منظمة داخل الموقع",
        "metadata_source": "بيانات جغرافية داخل الموقع",
        "not_found": "غير موجود",
        "summary": "يفحص هذا التقرير بعض عناصر SEO داخل الصفحة فقط. ولا يقيس سرعة الموقع الفعلية أو الروابط الخلفية أو الزيارات أو ترتيب Google.",
        "rate_error": "تم بلوغ حد الفحص. انتظر دقيقة ثم حاول مجددًا.",
        "url_error": "تعذر تحليل هذا الرابط",
        "generic_error": "تعذر إكمال الفحص. حاول مرة أخرى لاحقًا.",
        "invalid_url": "أدخل رابط موقع عام وصحيح.",
        "download": "طباعة / حفظ PDF",
        "print_hint": "لحفظ التقرير بصيغة PDF، افتح قائمة المتصفح واختر الطباعة أو الحفظ بصيغة PDF.",
        "score_explain": "تعكس النتيجة قائمة الفحص المحدودة هذه، وليس أداء الموقع في محركات البحث.",
        "yes": "نعم",
        "no": "لا",
    },
    "es": {
        "tagline": "Analiza. Automatiza. Mejora.",
        "heading": "Comprobador SEO gratuito",
        "intro": "Comprueba elementos SEO de la página sin crear una cuenta.",
        "website": "URL del sitio web",
        "location": "Ubicación del negocio (opcional)",
        "location_hint": "Introduce la dirección real o la ciudad si la conoces.",
        "manual": "Introducir ubicación manualmente",
        "analyze": "Analizar sitio web",
        "rate_note": "Los análisis tienen límites. Esta puntuación no es una clasificación de Google.",
        "report": "Informe de auditoría SEO",
        "checks": "Comprobaciones detalladas",
        "passed": "comprobaciones superadas",
        "score_note": "Puntuación de la lista EAQ; no es una clasificación de Google.",
        "title": "Título de página",
        "words": "Recuento aproximado de palabras",
        "internal": "Enlaces internos",
        "external": "Enlaces externos",
        "pass": "CORRECTO",
        "review": "REVISAR",
        "priority": "Prioridad",
        "critical": "Importante",
        "recommendation": "Recomendación",
        "http": "Respuesta HTTP",
        "https": "HTTPS",
        "description": "Meta descripción",
        "h1": "Encabezado H1",
        "alt": "Texto alternativo de imágenes",
        "canonical": "URL canónica",
        "viewport": "Vista móvil",
        "robots": "Directiva Robots",
        "content": "Contenido de texto",
        "schema": "Datos estructurados",
        "social": "Metadatos sociales",
        "lang_check": "Idioma HTML",
        "links_check": "Enlaces",
        "map": "Ubicación del negocio",
        "no_location": "No se encontró una ubicación comercial verificada. Introduce la dirección real o la ciudad y vuelve a analizar. La URL del sitio no es una dirección comercial.",
        "location_used": "Ubicación buscada",
        "location_source": "Fuente de ubicación",
        "manual_source": "Ubicación introducida manualmente",
        "schema_source": "Datos estructurados del sitio",
        "metadata_source": "Metadatos geográficos del sitio",
        "not_found": "No encontrado",
        "summary": "Este informe comprueba algunos elementos SEO de la página. No mide velocidad real, enlaces entrantes, tráfico ni posiciones en Google.",
        "rate_error": "Límite alcanzado. Espera un minuto e inténtalo de nuevo.",
        "url_error": "No se pudo analizar esta URL",
        "generic_error": "No se pudo completar el análisis. Inténtalo más tarde.",
        "invalid_url": "Introduce una URL pública válida.",
        "download": "Imprimir / Guardar PDF",
        "print_hint": "Para guardar el informe como PDF, abre el menú del navegador y selecciona Imprimir o Guardar como PDF.",
        "score_explain": "La puntuación refleja esta lista limitada, no el rendimiento en buscadores.",
        "yes": "Sí",
        "no": "No",
    },
    "fr": {
        "tagline": "Analysez. Automatisez. Améliorez.",
        "heading": "Vérificateur SEO gratuit",
        "intro": "Vérifiez les éléments SEO de la page sans créer de compte.",
        "website": "URL du site web",
        "location": "Emplacement de l’entreprise (facultatif)",
        "location_hint": "Saisissez l’adresse réelle ou la ville si vous la connaissez.",
        "manual": "Saisir manuellement l’emplacement",
        "analyze": "Analyser le site",
        "rate_note": "Les analyses sont limitées. Ce score n’est pas un classement Google.",
        "report": "Rapport d’audit SEO",
        "checks": "Contrôles détaillés",
        "passed": "contrôles réussis",
        "score_note": "Score de la liste EAQ, pas un classement Google.",
        "title": "Titre de page",
        "words": "Nombre approximatif de mots",
        "internal": "Liens internes",
        "external": "Liens externes",
        "pass": "RÉUSSI",
        "review": "À VÉRIFIER",
        "priority": "Priorité",
        "critical": "Important",
        "recommendation": "Recommandation",
        "http": "Réponse HTTP",
        "https": "HTTPS",
        "description": "Méta-description",
        "h1": "Titre H1",
        "alt": "Textes alternatifs des images",
        "canonical": "URL canonique",
        "viewport": "Affichage mobile",
        "robots": "Directive Robots",
        "content": "Contenu textuel",
        "schema": "Données structurées",
        "social": "Métadonnées sociales",
        "lang_check": "Langue HTML",
        "links_check": "Liens",
        "map": "Emplacement de l’entreprise",
        "no_location": "Aucune adresse professionnelle vérifiée n’a été trouvée. Saisissez l’adresse réelle ou la ville puis relancez l’analyse. L’URL du site n’est pas une adresse.",
        "location_used": "Emplacement recherché",
        "location_source": "Source de l’emplacement",
        "manual_source": "Emplacement saisi manuellement",
        "schema_source": "Données structurées du site",
        "metadata_source": "Métadonnées géographiques du site",
        "not_found": "Introuvable",
        "summary": "Ce rapport vérifie certains éléments SEO de la page. Il ne mesure ni la vitesse réelle, ni les backlinks, ni le trafic, ni le classement Google.",
        "rate_error": "Limite atteinte. Attendez une minute avant de réessayer.",
        "url_error": "Impossible d’analyser cette URL",
        "generic_error": "L’analyse a échoué. Veuillez réessayer plus tard.",
        "invalid_url": "Saisissez une URL publique valide.",
        "download": "Imprimer / Enregistrer en PDF",
        "print_hint": "Pour enregistrer en PDF, ouvrez le menu du navigateur et choisissez Imprimer ou Enregistrer en PDF.",
        "score_explain": "Le score reflète cette liste limitée, pas les performances dans les moteurs de recherche.",
        "yes": "Oui",
        "no": "Non",
    },
    "de": {
        "tagline": "Analysieren. Automatisieren. Verbessern.",
        "heading": "Kostenloser SEO-Website-Check",
        "intro": "Prüfen Sie wichtige Onpage-SEO-Elemente ohne Konto.",
        "website": "Website-URL",
        "location": "Standort des Unternehmens (optional)",
        "location_hint": "Geben Sie die tatsächliche Adresse oder Stadt ein.",
        "manual": "Unternehmensstandort manuell eingeben",
        "analyze": "Website analysieren",
        "rate_note": "Analysen sind begrenzt. Dies ist kein Google-Ranking.",
        "report": "SEO-Prüfbericht",
        "checks": "Detaillierte Prüfungen",
        "passed": "Prüfungen bestanden",
        "score_note": "EAQ-Checklistenwert, kein Google-Ranking.",
        "title": "Seitentitel",
        "words": "Ungefähre Wortzahl",
        "internal": "Interne Links",
        "external": "Externe Links",
        "pass": "BESTANDEN",
        "review": "PRÜFEN",
        "priority": "Priorität",
        "critical": "Wichtig",
        "recommendation": "Empfehlung",
        "http": "HTTP-Antwort",
        "https": "HTTPS",
        "description": "Meta-Beschreibung",
        "h1": "H1-Überschrift",
        "alt": "Alt-Texte der Bilder",
        "canonical": "Kanonische URL",
        "viewport": "Mobile Ansicht",
        "robots": "Robots-Anweisung",
        "content": "Textinhalt",
        "schema": "Strukturierte Daten",
        "social": "Social-Metadaten",
        "lang_check": "HTML-Sprache",
        "links_check": "Links",
        "map": "Unternehmensstandort",
        "no_location": "Kein verifizierter Unternehmensstandort gefunden. Geben Sie die tatsächliche Adresse oder Stadt ein und starten Sie die Prüfung erneut. Die Website-URL ist keine Adresse.",
        "location_used": "Gesuchter Standort",
        "location_source": "Standortquelle",
        "manual_source": "Manuell eingegebener Standort",
        "schema_source": "Strukturierte Daten der Website",
        "metadata_source": "Geografische Metadaten der Website",
        "not_found": "Nicht gefunden",
        "summary": "Dieser Bericht prüft ausgewählte Onpage-SEO-Elemente. Er misst weder echte Ladezeit noch Backlinks, Traffic oder Google-Rankings.",
        "rate_error": "Limit erreicht. Warten Sie eine Minute und versuchen Sie es erneut.",
        "url_error": "Diese URL konnte nicht analysiert werden",
        "generic_error": "Die Analyse konnte nicht abgeschlossen werden. Bitte später erneut versuchen.",
        "invalid_url": "Geben Sie eine gültige öffentliche Website-URL ein.",
        "download": "Drucken / Als PDF speichern",
        "print_hint": "Zum Speichern als PDF öffnen Sie das Browsermenü und wählen Drucken oder Als PDF speichern.",
        "score_explain": "Der Wert beschreibt diese begrenzte Checkliste, nicht die Suchmaschinenleistung.",
        "yes": "Ja",
        "no": "Nein",
    },
    "hi": {
        "tagline": "विश्लेषण करें। स्वचालित करें। सुधारें।",
        "heading": "मुफ़्त वेबसाइट SEO जाँच",
        "intro": "खाता बनाए बिना पेज के महत्वपूर्ण SEO तत्व जाँचें।",
        "website": "वेबसाइट URL",
        "location": "व्यवसाय का स्थान (वैकल्पिक)",
        "location_hint": "वास्तविक पता या शहर दर्ज करें।",
        "manual": "व्यवसाय का स्थान स्वयं दर्ज करें",
        "analyze": "वेबसाइट का विश्लेषण करें",
        "rate_note": "जाँच सीमित हैं। यह Google रैंकिंग स्कोर नहीं है।",
        "report": "SEO ऑडिट रिपोर्ट",
        "checks": "विस्तृत जाँच",
        "passed": "जाँच सफल",
        "score_note": "EAQ चेकलिस्ट स्कोर, Google रैंकिंग नहीं।",
        "title": "पेज शीर्षक",
        "words": "अनुमानित शब्द संख्या",
        "internal": "आंतरिक लिंक",
        "external": "बाहरी लिंक",
        "pass": "सफल",
        "review": "जाँचें",
        "priority": "प्राथमिकता",
        "critical": "महत्वपूर्ण",
        "recommendation": "सुझाव",
        "http": "HTTP प्रतिक्रिया",
        "https": "HTTPS",
        "description": "मेटा विवरण",
        "h1": "H1 शीर्षक",
        "alt": "चित्र वैकल्पिक टेक्स्ट",
        "canonical": "Canonical URL",
        "viewport": "मोबाइल व्यूपोर्ट",
        "robots": "Robots निर्देश",
        "content": "टेक्स्ट सामग्री",
        "schema": "संरचित डेटा",
        "social": "सोशल मेटाडेटा",
        "lang_check": "HTML भाषा",
        "links_check": "लिंक",
        "map": "व्यवसाय का स्थान",
        "no_location": "सत्यापित व्यवसाय स्थान नहीं मिला। वास्तविक पता या शहर दर्ज करके फिर जाँचें। वेबसाइट URL व्यवसाय का पता नहीं है।",
        "location_used": "खोजा गया स्थान",
        "location_source": "स्थान का स्रोत",
        "manual_source": "स्वयं दर्ज किया गया स्थान",
        "schema_source": "वेबसाइट का संरचित डेटा",
        "metadata_source": "वेबसाइट का भौगोलिक मेटाडेटा",
        "not_found": "नहीं मिला",
        "summary": "यह रिपोर्ट केवल कुछ ऑन-पेज SEO तत्व जाँचती है। यह वास्तविक गति, बैकलिंक, ट्रैफ़िक या Google रैंकिंग नहीं मापती।",
        "rate_error": "सीमा पूरी हुई। एक मिनट बाद फिर प्रयास करें।",
        "url_error": "इस URL का विश्लेषण नहीं हो सका",
        "generic_error": "जाँच पूरी नहीं हुई। बाद में फिर प्रयास करें।",
        "invalid_url": "मान्य सार्वजनिक वेबसाइट URL दर्ज करें।",
        "download": "प्रिंट / PDF में सहेजें",
        "print_hint": "PDF के लिए ब्राउज़र मेनू खोलें और Print या Save as PDF चुनें।",
        "score_explain": "यह स्कोर सीमित चेकलिस्ट दर्शाता है, खोज इंजन प्रदर्शन नहीं।",
        "yes": "हाँ",
        "no": "नहीं",
    },
    "tr": {
        "tagline": "Analiz et. Otomatikleştir. Geliştir.",
        "heading": "Ücretsiz Web Sitesi SEO Kontrolü",
        "intro": "Hesap oluşturmadan temel sayfa içi SEO öğelerini kontrol edin.",
        "website": "Web sitesi URL'si",
        "location": "İşletme konumu (isteğe bağlı)",
        "location_hint": "Gerçek adresi veya şehri girin.",
        "manual": "İşletme konumunu elle gir",
        "analyze": "Web sitesini analiz et",
        "rate_note": "Analiz sayısı sınırlıdır. Bu, Google sıralama puanı değildir.",
        "report": "SEO Denetim Raporu",
        "checks": "Ayrıntılı Kontroller",
        "passed": "kontrol başarılı",
        "score_note": "EAQ kontrol listesi puanı; Google sıralaması değildir.",
        "title": "Sayfa başlığı",
        "words": "Yaklaşık kelime sayısı",
        "internal": "Dahili bağlantılar",
        "external": "Harici bağlantılar",
        "pass": "BAŞARILI",
        "review": "İNCELE",
        "priority": "Öncelik",
        "critical": "Önemli",
        "recommendation": "Öneri",
        "http": "HTTP yanıtı",
        "https": "HTTPS",
        "description": "Meta açıklaması",
        "h1": "H1 başlığı",
        "alt": "Görsel alt metinleri",
        "canonical": "Canonical URL",
        "viewport": "Mobil görünüm",
        "robots": "Robots yönergesi",
        "content": "Metin içeriği",
        "schema": "Yapılandırılmış veri",
        "social": "Sosyal paylaşım meta verileri",
        "lang_check": "HTML dili",
        "links_check": "Bağlantılar",
        "map": "İşletme konumu",
        "no_location": "Doğrulanmış işletme konumu bulunamadı. Gerçek adresi veya şehri girip yeniden analiz edin. Web sitesi URL'si bir işletme adresi değildir.",
        "location_used": "Aranan konum",
        "location_source": "Konum kaynağı",
        "manual_source": "Elle girilen konum",
        "schema_source": "Web sitesindeki yapılandırılmış veri",
        "metadata_source": "Web sitesindeki coğrafi meta veriler",
        "not_found": "Bulunamadı",
        "summary": "Bu rapor seçili sayfa içi SEO öğelerini kontrol eder. Gerçek hızı, backlinkleri, trafiği veya Google sıralamasını ölçmez.",
        "rate_error": "Sınır aşıldı. Bir dakika bekleyip tekrar deneyin.",
        "url_error": "Bu URL analiz edilemedi",
        "generic_error": "Analiz tamamlanamadı. Daha sonra tekrar deneyin.",
        "invalid_url": "Geçerli bir herkese açık web sitesi URL'si girin.",
        "download": "Yazdır / PDF olarak kaydet",
        "print_hint": "PDF için tarayıcı menüsünden Yazdır veya PDF olarak kaydet seçeneğini seçin.",
        "score_explain": "Puan bu sınırlı kontrol listesini gösterir, arama motoru performansını değil.",
        "yes": "Evet",
        "no": "Hayır",
    },
    "zh": {
        "tagline": "分析。自动化。优化。",
        "heading": "免费网站 SEO 检查",
        "intro": "无需注册即可检查重要的页面 SEO 项目。",
        "website": "网站 URL",
        "location": "企业地址（可选）",
        "location_hint": "请输入真实地址或城市。",
        "manual": "手动输入企业地址",
        "analyze": "分析网站",
        "rate_note": "检查次数有限。本评分不是 Google 排名。",
        "report": "SEO 审核报告",
        "checks": "详细检查",
        "passed": "项检查通过",
        "score_note": "EAQ 检查清单评分，不是 Google 排名。",
        "title": "页面标题",
        "words": "估算字数",
        "internal": "内部链接",
        "external": "外部链接",
        "pass": "通过",
        "review": "需要检查",
        "priority": "优先级",
        "critical": "重要",
        "recommendation": "建议",
        "http": "HTTP 响应",
        "https": "HTTPS",
        "description": "Meta 描述",
        "h1": "H1 标题",
        "alt": "图片替代文本",
        "canonical": "规范网址",
        "viewport": "移动设备视口",
        "robots": "Robots 指令",
        "content": "文本内容",
        "schema": "结构化数据",
        "social": "社交分享元数据",
        "lang_check": "HTML 语言",
        "links_check": "链接",
        "map": "企业位置",
        "no_location": "未找到经过验证的企业位置。请输入真实地址或城市后重新分析。网站 URL 不是企业地址。",
        "location_used": "搜索位置",
        "location_source": "位置来源",
        "manual_source": "手动输入的位置",
        "schema_source": "网站结构化数据",
        "metadata_source": "网站地理元数据",
        "not_found": "未找到",
        "summary": "本报告仅检查部分页面 SEO 项目，不测量实际速度、反向链接、流量或 Google 排名。",
        "rate_error": "已达到限制。请等待一分钟后重试。",
        "url_error": "无法分析此 URL",
        "generic_error": "分析未能完成，请稍后重试。",
        "invalid_url": "请输入有效的公开网站 URL。",
        "download": "打印 / 保存为 PDF",
        "print_hint": "要保存为 PDF，请打开浏览器菜单并选择打印或保存为 PDF。",
        "score_explain": "此分数反映有限的检查清单，而不是搜索引擎表现。",
        "yes": "是",
        "no": "否",
    },
}

LANG_OPTIONS = [
    ("en", "English"),
    ("ar", "العربية"),
    ("es", "Español"),
    ("fr", "Français"),
    ("de", "Deutsch"),
    ("hi", "हिन्दी"),
    ("tr", "Türkçe"),
    ("zh", "中文"),
]


def tr(lang, key):
    return TEXT.get(lang, TEXT["en"]).get(key, TEXT["en"].get(key, key))


def render_page(result_html="", map_html="", lang="en", status_code=200):
    lang = lang if lang in TEXT else "en"
    direction = "rtl" if lang == "ar" else "ltr"
    options = "".join(
        f'<option value="{code}"{" selected" if code == lang else ""}>{escape(label)}</option>'
        for code, label in LANG_OPTIONS
    )
    page = f"""<!doctype html>
<html lang="{lang}" dir="{direction}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#10243e">
<title>EAQ.io SEO Audit</title>
<meta name="description" content="Free website SEO audit in eight languages.">
<style>
*{{box-sizing:border-box}}
:root{{--navy:#10243e;--teal:#087e8b;--mint:#48d4c2;--text:#182b43;--muted:#617187;--border:#e0e8f0;--bg:#f3f7fb}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:Arial,Helvetica,sans-serif;line-height:1.65}}
header{{background:var(--navy);color:white;padding:23px 18px}}
.wrap{{max-width:1000px;margin:auto;padding:0 18px}}
.brand{{font-size:25px;font-weight:800;letter-spacing:-.4px}}
.brand span{{color:var(--mint)}}
header p{{margin:5px 0 0;color:#d2deeb}}
main{{padding:30px 0}}
.card{{background:white;border:1px solid var(--border);border-radius:15px;padding:24px;margin-bottom:20px;box-shadow:0 5px 22px #142a4310;overflow-wrap:anywhere}}
h1{{font-size:clamp(24px,4vw,32px);line-height:1.25;margin:0 0 12px}}
h2{{font-size:21px;margin:0 0 14px}}
h3{{font-size:17px;margin:0 0 8px}}
.muted{{color:var(--muted)}}
label{{display:block;font-weight:700;margin:15px 0 7px}}
input,select{{width:100%;padding:13px;border:1px solid #cbd7e4;border-radius:9px;font-size:16px;background:white;color:var(--text)}}
button,.button{{display:inline-block;margin-top:14px;background:var(--teal);color:white;border:0;padding:12px 19px;border-radius:9px;font-size:16px;font-weight:700;cursor:pointer;text-decoration:none}}
button:focus-visible,input:focus-visible,select:focus-visible{{outline:3px solid var(--mint);outline-offset:2px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,230px),1fr));gap:13px}}
.metric{{padding:15px;border-radius:10px;background:#f7f9fc;border:1px solid #e5ebf2;overflow-wrap:anywhere;min-width:0}}
.metric strong{{display:block;margin-bottom:5px}}
.status{{font-weight:800}}
.pass{{color:#087a53}}
.fail{{color:#b45309}}
.score{{font-size:38px;font-weight:800;color:var(--teal)}}
.notice{{background:#edf8f7;padding:13px;border-radius:9px}}
.map-frame{{display:block;width:100%;height:360px;border:0;border-radius:10px;background:var(--bg)}}
.lang-row{{max-width:1000px;margin:0 auto;padding:0 18px;display:flex;justify-content:flex-end}}
.lang-row form{{display:flex;gap:8px;align-items:center;width:min(100%,280px)}}
.lang-row label{{margin:0;white-space:nowrap}}
.lang-row select{{padding:8px}}
.small{{font-size:13px}}
.badge{{display:inline-block;padding:3px 8px;border-radius:6px;font-size:12px;font-weight:700;background:#fff0d9;color:#925500}}
.manual-location-fields{{display:none}}
#manual-location-toggle:checked + .manual-location-fields{{display:block}}
.print-hint{{font-size:13px;color:var(--muted)}}
footer{{text-align:center;padding:24px;color:var(--muted);font-size:13px}}
@media(max-width:600px){{
 main{{padding:18px 0}}
 .card{{padding:17px;border-radius:12px}}
 .map-frame{{height:280px}}
 .lang-row{{justify-content:stretch}}
 .lang-row form{{width:100%}}
}}
@media print{{
 body{{background:white;color:#111}}
 header{{background:white;color:#111;padding:10px 0}}
 header p{{color:#333}}
 .no-print,form,footer{{display:none!important}}
 main{{padding:0}}
 .card{{box-shadow:none;break-inside:avoid;border:1px solid #bbb;padding:12px}}
 .map-frame{{height:250px}}
}}
</style>
</head>
<body>
<header><div class="wrap"><div class="brand">EAQ<span>.io</span> SEO Audit</div><p>{escape(tr(lang,"tagline"))}</p></div></header>
<div class="lang-row no-print"><form method="get" action="/" aria-label="Language selector"><label for="lang">{'اللغة' if lang=='ar' else 'Language'}</label><select id="lang" name="lang" onchange="this.form.submit()">{options}</select></form></div>
<main class="wrap">
<section class="card no-print">
<h1>{escape(tr(lang,"heading"))}</h1>
<p class="muted">{escape(tr(lang,"intro"))}</p>
<form method="post" action="/audit">
<input type="hidden" name="lang" value="{lang}">
<label for="url">{escape(tr(lang,"website"))}</label>
<input id="url" name="url" type="text" maxlength="2048" placeholder="https://example.com" required autocomplete="url">
<label><input id="manual-location-toggle" type="checkbox" style="width:auto;margin-inline-end:7px">{escape(tr(lang,"manual"))}</label>
<div class="manual-location-fields">
<label for="location">{escape(tr(lang,"location"))}</label>
<input id="location" name="location" type="text" maxlength="300" placeholder="{escape(tr(lang,'location_hint'),quote=True)}">
</div>
<button type="submit">{escape(tr(lang,"analyze"))}</button>
</form>
<p class="muted small">{escape(tr(lang,"rate_note"))}</p>
</section>
{result_html}
{map_html}
</main>
<footer>EAQ.io SEO Audit · {escape(tr(lang,"score_note"))}</footer>
</body></html>"""
    return HTMLResponse(page, status_code=status_code)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; "
        "style-src 'unsafe-inline'; "
        "frame-src https://www.google.com https://maps.google.com; "
        "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def check_rate_limit(client_ip):
    now = time.monotonic()
    with rate_lock:
        history = rate_history.get(client_ip)
        if history is None:
            if len(rate_history) >= MAX_RATE_KEYS:
                stale = [
                    key for key, entries in rate_history.items()
                    if not entries or now - entries[-1] >= RATE_WINDOW
                ]
                for key in stale:
                    rate_history.pop(key, None)
                if len(rate_history) >= MAX_RATE_KEYS:
                    return False
            history = deque()
            rate_history[client_ip] = history
        while history and now - history[0] >= RATE_WINDOW:
            history.popleft()
        if len(history) >= RATE_LIMIT:
            return False
        history.append(now)
        return True


def normalize_url(raw_url):
    if not raw_url or len(raw_url) > MAX_URL_LENGTH:
        raise ValueError("Please enter a valid website URL.")
    raw_url = raw_url.strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw_url):
        raise ValueError("The URL contains invalid characters.")
    if "://" not in raw_url:
        raw_url = "https://" + raw_url
    try:
        parsed = urlsplit(raw_url)
        scheme, hostname, port = parsed.scheme.lower(), parsed.hostname, parsed.port
    except ValueError as exc:
        raise ValueError("The URL format is invalid.") from exc
    if scheme not in ("http", "https"):
        raise ValueError("Only HTTP and HTTPS websites are supported.")
    if not hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("Enter a public website URL without credentials.")
    if port is not None and port != (443 if scheme == "https" else 80):
        raise ValueError("Only standard HTTP and HTTPS ports are allowed.")
    hostname = hostname.rstrip(".").lower()
    if not hostname or "%" in hostname:
        raise ValueError("The hostname is invalid.")
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("The hostname is invalid.") from exc
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("Enter a public domain name, not an IP address.")
    blocked_names = {
        "localhost", "metadata", "metadata.google.internal",
        "metadata.goog", "instance-data", "kubernetes.default",
    }
    blocked_suffixes = (
        ".localhost", ".local", ".internal", ".localdomain",
        ".home.arpa", ".cluster.local", ".svc",
    )
    if "." not in hostname or hostname in blocked_names or any(
        hostname.endswith(suffix) for suffix in blocked_suffixes
    ):
        raise ValueError("Local and private hostnames are not allowed.")
    path, query = parsed.path or "/", parsed.query
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in path + query):
        raise ValueError("The URL contains invalid characters.")
    normalized = urlunsplit((scheme, hostname, path, query, ""))
    if len(normalized) > MAX_URL_LENGTH:
        raise ValueError("The URL is too long.")
    return normalized


def is_public_ip(address):
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return is_public_ip(address.ipv4_mapped)
        if address.sixtofour is not None or address.teredo is not None:
            return False
        for network in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16"):
            if address in ipaddress.ip_network(network):
                return False
        return address.is_global and not any((
            address.is_multicast, address.is_unspecified,
            address.is_loopback, address.is_link_local,
        ))
    blocked = (
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10",
        "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
        "192.0.0.0/24", "192.0.2.0/24", "192.168.0.0/16",
        "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24",
        "224.0.0.0/4", "240.0.0.0/4",
    )
    return address.is_global and not any((
        address.is_multicast, address.is_unspecified,
        address.is_loopback, address.is_link_local,
    )) and not any(address in ipaddress.ip_network(net) for net in blocked)


def resolve_public_addresses(hostname, port):
    try:
        records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError) as exc:
        raise ValueError("The website hostname could not be resolved.") from exc
    addresses = []
    for record in records:
        ip_text = record[4][0]
        if "%" in ip_text:
            raise ValueError("Scoped IP addresses are not allowed.")
        try:
            address = ipaddress.ip_address(ip_text)
        except ValueError as exc:
            raise ValueError("The website resolved to an invalid address.") from exc
        if not is_public_ip(address):
            raise ValueError("The website resolves to a non-public or reserved IP address.")
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise ValueError("No public IP address was found for this website.")
    return addresses


def open_pinned_connection(hostname, scheme, port):
    last_error = None
    for address in resolve_public_addresses(hostname, port):
        sock = None
        try:
            family = socket.AF_INET if address.version == 4 else socket.AF_INET6
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(REQUEST_TIMEOUT)
            if address.version == 4:
                sock.connect((str(address), port))
            else:
                sock.connect((str(address), port, 0, 0))
            if scheme == "https":
                context = ssl.create_default_context()
                sock = context.wrap_socket(sock, server_hostname=hostname)
                sock.settimeout(REQUEST_TIMEOUT)
            return sock
        except (OSError, ssl.SSLError, socket.timeout) as exc:
            last_error = exc
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
    raise ValueError("Could not establish a secure connection to the website.") from last_error


def fetch_public_page(raw_url):
    current_url = normalize_url(raw_url)
    for redirect_number in range(MAX_REDIRECTS + 1):
        current_url = normalize_url(current_url)
        parsed = urlsplit(current_url)
        scheme, hostname = parsed.scheme, parsed.hostname
        port = 443 if scheme == "https" else 80
        path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
        query = quote(parsed.query, safe="=&;%:@!$'()*+,-._~/?")
        target = path + (("?" + query) if query else "")
        sock = open_pinned_connection(hostname, scheme, port)
        response = None
        try:
            request_bytes = (
                f"GET {target} HTTP/1.1\r\nHost: {hostname}\r\n"
                f"User-Agent: EAQSEOAudit/{APP_VERSION}\r\n"
                "Accept: text/html,application/xhtml+xml\r\n"
                "Accept-Encoding: identity\r\nConnection: close\r\n\r\n"
            ).encode("ascii")
            sock.sendall(request_bytes)
            response = http.client.HTTPResponse(sock)
            response.begin()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise ValueError("The website returned an invalid redirect.")
                if redirect_number >= MAX_REDIRECTS:
                    raise ValueError("Too many website redirects.")
                current_url = urljoin(current_url, location)
                continue
            mime = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            if mime not in ("text/html", "application/xhtml+xml"):
                raise ValueError("The URL did not return an HTML page.")
            encoding = response.getheader("Content-Encoding", "identity").strip().lower()
            if encoding not in ("", "identity"):
                raise ValueError("Compressed content is not supported by this basic audit.")
            length = response.getheader("Content-Length")
            if length is not None:
                try:
                    size = int(length)
                except (TypeError, ValueError) as exc:
                    raise ValueError("The website returned an invalid response length.") from exc
                if size < 0 or size > MAX_HTML_BYTES:
                    raise ValueError("The webpage is too large to analyze.")
            body = response.read(MAX_HTML_BYTES + 1)
            if len(body) > MAX_HTML_BYTES:
                raise ValueError("The webpage exceeds the 1 MB analysis limit.")
            charset = response.headers.get_content_charset() or "utf-8"
            try:
                html = body.decode(charset, errors="replace")
            except LookupError:
                html = body.decode("utf-8", errors="replace")
            return current_url, html, response.status
        except (OSError, ssl.SSLError, socket.timeout, http.client.HTTPException) as exc:
            raise ValueError("The website could not be fetched safely or timed out.") from exc
        finally:
            if response is not None:
                try:
                    response.close()
                except OSError:
                    pass
            try:
                sock.close()
            except OSError:
                pass
    raise ValueError("The website could not be reached.")


def extract_location_from_schema(soup):
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw or len(raw) > 200_000:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("@graph"), list):
                stack.extend(item["@graph"])
            geo = item.get("geo")
            if isinstance(geo, dict):
                try:
                    lat, lon = float(geo.get("latitude")), float(geo.get("longitude"))
                    if -90 <= lat <= 90 and -180 <= lon <= 180:
                        return f"{lat},{lon}", "schema"
                except (TypeError, ValueError):
                    pass
            address = item.get("address")
            if isinstance(address, dict):
                keys = ("streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry")
                parts = [str(address.get(k, "")).strip() for k in keys if address.get(k)]
                if parts:
                    return ", ".join(parts), "schema"
            elif isinstance(address, str) and address.strip():
                return address.strip(), "schema"
    return "", ""


def extract_location_from_metadata(soup):
    for attrs in (
        {"property": "og:street-address"},
        {"property": "business:contact_data:street_address"},
        {"name": "address"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content", "").strip():
            return tag["content"].strip(), "metadata"
    geo = soup.find("meta", attrs={"name": "geo.position"})
    if geo and geo.get("content"):
        parts = geo["content"].strip().replace(";", ",").split(",")
        if len(parts) >= 2:
            try:
                lat, lon = float(parts[0].strip()), float(parts[1].strip())
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    return f"{lat},{lon}", "metadata"
            except ValueError:
                pass
    return "", ""


def clean_location(value, website_url=""):
    value = (value or "").strip()
    if not value or len(value) > 300:
        return ""
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return ""
    # Reject URLs and hostnames entered in place of a real address.
    if "://" in value or value.lower().startswith(("www.", "mailto:", "javascript:")):
        return ""
    host = (urlsplit(website_url).hostname or "").lower() if website_url else ""
    normalized = value.lower().strip().rstrip("/")
    if host and normalized in {host, "www." + host, "https://" + host, "http://" + host}:
        return ""
    return value


def build_map_html(html, location_override="", website_url="", lang="en"):
    soup = BeautifulSoup(html, "html.parser")
    query = clean_location(location_override, website_url)
    source = "manual" if query else ""
    if not query:
        query, source = extract_location_from_schema(soup)
    if not query:
        query, source = extract_location_from_metadata(soup)
    if not query:
        return (
            '<section class="card"><h2>' + escape(tr(lang, "map")) + '</h2><p class="muted">'
            + escape(tr(lang, "no_location")) + '</p></section>'
        )
    source_label = {
        "manual": tr(lang, "manual_source"),
        "schema": tr(lang, "schema_source"),
        "metadata": tr(lang, "metadata_source"),
    }.get(source, "")
    maps_url = "https://www.google.com/maps?q=" + quote(query, safe=",") + "&output=embed"
    return (
        '<section class="card"><h2>' + escape(tr(lang, "map")) + '</h2>'
        '<p class="muted">' + escape(tr(lang, "location_used")) + ': <strong>'
        + escape(query) + '</strong></p><p class="muted small">'
        + escape(tr(lang, "location_source")) + ': ' + escape(source_label)
        + '</p><iframe class="map-frame" title="Business location map" src="'
        + escape(maps_url, quote=True)
        + '" loading="lazy" referrerpolicy="no-referrer-when-downgrade" allowfullscreen></iframe></section>'
    )


def analyze_page(url, html, status_code):
    soup = BeautifulSoup(html, "html.parser")
    # Keep JSON-LD available for structured-data checks before removing active content.
    structured_data_found = bool(soup.find("script", attrs={"type": "application/ld+json"}))
    for element in soup(["script", "style", "noscript", "svg", "template"]):
        element.decompose()

    checks = []

    def add(key, passed, detail, recommendation="", priority="normal"):
        checks.append({
            "key": key,
            "passed": bool(passed),
            "detail": detail,
            "recommendation": recommendation,
            "priority": priority,
        })

    add("http", status_code == 200, f"HTTP status: {status_code}",
        "Investigate the response code and server configuration." if status_code != 200 else "",
        "important" if status_code != 200 else "normal")

    secure = urlsplit(url).scheme == "https"
    add("https", secure, "The page uses HTTPS." if secure else "The page uses HTTP.",
        "Use HTTPS with a valid certificate and redirect HTTP to HTTPS." if not secure else "",
        "important" if not secure else "normal")

    title_tag = soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else ""
    add("title", bool(title), title or "No title tag found.",
        "Add a unique descriptive title, usually around 30–60 characters." if not title else
        ("Review the title length; 30–60 characters is a common guideline." if not 30 <= len(title) <= 60 else ""))

    desc_tag = soup.find("meta", attrs={"name": lambda v: v and v.lower() == "description"})
    description = desc_tag.get("content", "").strip() if desc_tag else ""
    add("description", bool(description), description or "No meta description found.",
        "Add a unique useful meta description; 120–160 characters is a common guideline." if not description else
        ("Review description length; 120–160 characters is a common guideline." if not 120 <= len(description) <= 160 else ""))

    h1_count = len(soup.find_all("h1"))
    add("h1", h1_count == 1, f"Found {h1_count} H1 heading(s).",
        "Use one clear primary H1 heading." if h1_count != 1 else "")

    images = soup.find_all("img")
    missing_alt = sum(1 for image in images if not image.has_attr("alt"))
    add("alt", missing_alt == 0, f"{missing_alt} of {len(images)} images lack an alt attribute.",
        'Add meaningful alt text to informative images; use alt="" for decorative images.' if missing_alt else "")

    canonical_tag = soup.find("link", attrs={"rel": lambda v: v and "canonical" in (v if isinstance(v, list) else [v])})
    canonical = canonical_tag.get("href", "").strip() if canonical_tag else ""
    valid_canonical = False
    if canonical:
        try:
            c = urlsplit(urljoin(url, canonical))
            valid_canonical = c.scheme in ("http", "https") and bool(c.hostname)
        except ValueError:
            valid_canonical = False
    add("canonical", valid_canonical, canonical or "No valid canonical link found.",
        "Add a valid absolute or relative canonical URL when appropriate." if not valid_canonical else "")

    viewport = soup.find("meta", attrs={"name": lambda v: v and v.lower() == "viewport"})
    add("viewport", viewport is not None, "Viewport meta tag found." if viewport else "Viewport meta tag missing.",
        "Add a responsive viewport meta tag." if viewport is None else "")

    robots_tag = soup.find("meta", attrs={"name": lambda v: v and v.lower() == "robots"})
    robots = robots_tag.get("content", "").lower() if robots_tag else ""
    noindex = "noindex" in robots
    add("robots", not noindex, "A noindex directive was found." if noindex else "No meta robots noindex directive detected.",
        "Remove noindex if this page should appear in search results." if noindex else "",
        "important" if noindex else "normal")

    words = soup.get_text(" ", strip=True).split()
    add("content", len(words) >= 300, f"Approximately {len(words)} words detected.",
        "Review whether the page provides enough useful content for its purpose." if len(words) < 300 else "")

    internal = external = 0
    host = (urlsplit(url).hostname or "").lower()
    for link in soup.find_all("a", href=True):
        href = link.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        try:
            target = urlsplit(urljoin(url, href))
            target_host = (target.hostname or "").lower()
        except ValueError:
            continue
        if not target_host:
            continue
        if target_host == host:
            internal += 1
        else:
            external += 1
    add("internal", internal > 0, f"{internal} internal link(s) detected.",
        "Add relevant internal links where useful." if internal == 0 else "")

    add("schema", structured_data_found,
        "JSON-LD structured data found." if structured_data_found else "No JSON-LD structured data detected.",
        "Consider appropriate Schema.org structured data if relevant to this page." if not structured_data_found else "")

    og_title = soup.find("meta", attrs={"property": "og:title"})
    og_desc = soup.find("meta", attrs={"property": "og:description"})
    social_ok = bool(og_title and og_title.get("content", "").strip()) and bool(og_desc and og_desc.get("content", "").strip())
    add("social", social_ok, "Open Graph title and description found." if social_ok else "Open Graph title and/or description missing.",
        "Add suitable og:title and og:description metadata to improve link previews." if not social_ok else "")

    html_tag = BeautifulSoup(html, "html.parser").find("html")
    html_lang = (html_tag.get("lang", "").strip() if html_tag else "")
    add("lang_check", bool(html_lang), f"HTML lang attribute: {html_lang}" if html_lang else "HTML lang attribute missing.",
        'Set the correct language, for example lang="en".' if not html_lang else "")

    passed = sum(1 for item in checks if item["passed"])
    total = len(checks)
    score = round(passed * 100 / total) if total else 0
    return {
        "url": url, "status_code": status_code, "title": title,
        "description": description, "word_count": len(words),
        "internal_links": internal, "external_links": external,
        "passed": passed, "total": total, "score": score, "checks": checks,
    }


def result_html(report, lang):
    labels = {key: tr(lang, key) for key in (
        "http", "https", "title", "description", "h1", "alt", "canonical",
        "viewport", "robots", "content", "internal", "schema", "social", "lang_check"
    )}
    cards = []
    for item in report["checks"]:
        key = item["key"]
        passed = item["passed"]
        state = tr(lang, "pass") if passed else tr(lang, "review")
        css = "pass" if passed else "fail"
        priority = ""
        if not passed:
            priority = (
                '<p><span class="badge">' + escape(tr(lang, "critical") if item["priority"] == "important" else tr(lang, "recommendation")) + '</span></p>'
            )
        recommendation = (
            '<p class="muted"><strong>' + escape(tr(lang, "recommendation")) + ':</strong> '
            + escape(item["recommendation"]) + '</p>'
        ) if item["recommendation"] else ""
        cards.append(
            '<div class="metric"><strong>' + escape(labels.get(key, key))
            + '</strong><span class="status ' + css + '">' + escape(state)
            + '</span><p>' + escape(item["detail"]) + '</p>' + priority
            + recommendation + '</div>'
        )

    return (
        '<section class="card" id="report"><h2>' + escape(tr(lang, "report")) + '</h2>'
        '<p><strong>' + escape(tr(lang, "website")) + ':</strong> ' + escape(report["url"]) + '</p>'
        '<div class="score">' + str(report["score"]) + '/100</div>'
        '<p class="muted">' + escape(tr(lang, "score_note")) + '</p>'
        '<p>' + str(report["passed"]) + ' / ' + str(report["total"]) + ' '
        + escape(tr(lang, "passed")) + '</p>'
        '<div class="grid"><div class="metric"><strong>' + escape(tr(lang, "title"))
        + '</strong>' + escape(report["title"] or tr(lang, "not_found")) + '</div>'
        '<div class="metric"><strong>' + escape(tr(lang, "words")) + '</strong>'
        + str(report["word_count"]) + '</div><div class="metric"><strong>'
        + escape(tr(lang, "internal")) + '</strong>' + str(report["internal_links"])
        + '</div><div class="metric"><strong>' + escape(tr(lang, "external"))
        + '</strong>' + str(report["external_links"]) + '</div></div></section>'
        '<section class="card"><h2>' + escape(tr(lang, "checks")) + '</h2><div class="grid">'
        + "".join(cards) + '</div></section>'
        '<section class="card"><p class="notice">' + escape(tr(lang, "summary"))
        + '</p><p class="print-hint">' + escape(tr(lang, "print_hint"))
        + '</p><button class="no-print" type="button" onclick="window.print()" '
        'style="display:none">Print</button></section>'
    )


@app.get("/", response_class=HTMLResponse)
def home(lang: str = "en"):
    if lang not in TEXT:
        lang = "en"
    return render_page(lang=lang)


@app.get("/health")
def health():
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION}


@app.post("/audit", response_class=HTMLResponse)
def audit(
    request: Request,
    url: str = Form(...),
    location: str = Form(""),
    lang: str = Form("en"),
):
    if lang not in TEXT:
        lang = "en"
    client_ip = request.client.host if request.client and request.client.host else "unknown"
    if not check_rate_limit(client_ip):
        result = (
            '<section class="card"><h2>' + escape(tr(lang, "rate_error"))
            + '</h2></section>'
        )
        return render_page(result, lang=lang, status_code=429)

    try:
        final_url, html, status = fetch_public_page(url)
        report = analyze_page(final_url, html, status)
        map_result = build_map_html(html, location, final_url, lang)
        return render_page(result_html(report, lang), map_result, lang)
    except ValueError as exc:
        result = (
            '<section class="card"><h2>' + escape(tr(lang, "url_error"))
            + '</h2><p>' + escape(str(exc)) + '</p><p class="muted">'
            + escape(tr(lang, "invalid_url")) + '</p></section>'
        )
        return render_page(result, lang=lang, status_code=400)
    except Exception:
        result = (
            '<section class="card"><h2>' + escape(tr(lang, "generic_error"))
            + '</h2></section>'
        )
        return render_page(result, lang=lang, status_code=500)
