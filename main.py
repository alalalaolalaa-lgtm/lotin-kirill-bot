import telebot
from telebot import types
import sqlite3
import re
import time
import os
import html
import tempfile
import traceback
import functools
import threading
import copy
import shutil
import urllib.request
from io import BytesIO

# ============================================================
#   SOZLAMALAR - FAQAT SHUНИ O'ZGARTIRING
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")   # @BotFather dan olgan token
ADMIN_ID = 8504719505                          # Sizning Telegram ID raqamingiz
ADMIN_USERNAME = "opensimHelp"                  # Sizning Telegram username (@ siz)
# ============================================================

# ============================================================
#   XATOLIKLAR: faqat adminga yuboriladi
# ============================================================
GENERIC_ERROR_TEXT = "⚠️ Vaqtincha texnik nosozlik yuz berdi. Iltimos, birozdan so'ng qayta urinib ko'ring."
ERROR_COOLDOWN = 60          # bir xil xato adminga 60 soniyada bir martadan ko'p yuborilmaydi
_error_last_sent = {}

def _is_network_noise(exc):
    """Vaqtincha internet uzilishlari o'zi tuzaladi - adminni bezovta qilmaymiz."""
    try:
        import requests
        return isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout))
    except Exception:
        return False

def notify_admin(where, exc, message=None, extra="", cooldown=None):
    """Xatoni (traceback bilan) faqat adminga yuboradi. Hech qachon xato ko'tarmaydi."""
    try:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(f"[XATOLIK] {where}\n{tb}")                    # server logida ham qoladi
        if _is_network_noise(exc):
            return
        key = (where, type(exc).__name__, str(exc)[:120])
        now = time.time()
        if now - _error_last_sent.get(key, 0) < (ERROR_COOLDOWN if cooldown is None else cooldown):
            return
        if len(_error_last_sent) > 500:
            _error_last_sent.clear()
        _error_last_sent[key] = now

        head = f"🚨 <b>Bot xatoligi</b>\n📍 {html.escape(str(where))}\n"
        u = getattr(message, "from_user", None) if message is not None else None
        if u:
            uname = f"@{u.username}" if u.username else "username yo'q"
            head += f"👤 {html.escape(u.first_name or '')} ({html.escape(uname)}), ID: <code>{u.id}</code>\n"
        if extra:
            head += f"📎 {html.escape(extra)}\n"
        body = tb[-2500:]
        text = head + "\n<pre>" + html.escape(body) + "</pre>"
        while len(text) > 4096 and body:                    # Telegram limiti
            body = body[len(body) // 4 + 1:]
            text = head + "\n<pre>" + html.escape(body) + "</pre>"
        bot.send_message(ADMIN_ID, text, parse_mode="HTML")
    except Exception as e:
        print("Adminga xabar yuborib bo'lmadi:", repr(e))

def safe_handler(func):
    """Handler ichida kutilmagan xato bo'lsa: admin ma'lumot oladi, foydalanuvchi esa faqat
    qisqa, texnik tafsilotsiz xabar ko'radi."""
    @functools.wraps(func)
    def wrapper(message, *args, **kwargs):
        try:
            return func(message, *args, **kwargs)
        except Exception as e:
            notify_admin(func.__name__, e, message)
            try:
                bot.send_message(message.chat.id, GENERIC_ERROR_TEXT,
                                 reply_markup=main_menu(message.from_user.id, message.from_user.username))
            except Exception:
                pass
    return wrapper

def admin_say(text, key=None, cooldown=0):
    """Adminga qisqa matn yuboradi (traceback'siz). Hech qachon xato ko'tarmaydi."""
    try:
        print(text)
        now = time.time()
        if key is not None:
            if now - _error_last_sent.get(("say", key), 0) < cooldown:
                return
            _error_last_sent[("say", key)] = now
        bot.send_message(ADMIN_ID, text, parse_mode="HTML")
    except Exception as e:
        print("Adminga xabar yuborib bo'lmadi:", repr(e))

CONFLICT_TEXT = (
    "⚠️ <b>Botning boshqa nusxasi ham ishlayapti (409 Conflict)</b>\n\n"
    "Bir xil token bilan bir vaqtda faqat BITTA joyda bot ishlashi mumkin. Aks holda xabarlar nusxalar orasida "
    "bo'linib ketadi va ba'zilari ESKI versiyaga tushadi.\n\n"
    "<b>Nima qilish kerak:</b>\n"
    "1. Colab: boshqa daftar/oynalarni va ishlab turgan katakchalarni to'xtating (yoki Runtime → Disconnect and delete runtime).\n"
    "2. Kompyuter yoki hostingda ham botni to'xtating.\n"
    "3. Qaysi nusxa borligini bilmasangiz: @BotFather → /mybots → botingiz → API Token → Revoke current token. "
    "Eski token bilan ishlayotgan hamma nusxalar to'xtaydi. Keyin yangi tokenni faqat bitta joyga yozing."
)

class AdminExceptionHandler(telebot.ExceptionHandler):
    """Polling paytidagi umumiy xatolar ham adminga boradi."""
    def handle(self, exception):
        if getattr(exception, "error_code", None) == 409:      # boshqa nusxa ishlayapti
            admin_say(CONFLICT_TEXT, key="409", cooldown=1800)
            return True
        notify_admin("polling", exception)
        return True

bot = telebot.TeleBot(BOT_TOKEN, num_threads=8, exception_handler=AdminExceptionHandler())

# Admin xabarlarini vaqtinchalik saqlash uchun lug'at
admin_broadcast_data = {}

# --- ALIFBO MANTIQLARI ---
def to_cyrillic(text):
    text = re.sub(r"['`´ʼʻ‘’‛]", "'", text)   # barcha apostrof turlari (Word: ’)
    replacements = {
        "O'": "Ў", "o'": "ў", "G'": "Ғ", "g'": "ғ",
        "Sh": "Ш", "SH": "Ш", "sh": "ш", "Ch": "Ч", "CH": "Ч", "ch": "ч",
        "Yo": "Ё", "YO": "Ё", "yo": "ё", "Yu": "Ю", "YU": "Ю", "yu": "ю",
        "Ya": "Я", "YA": "Я", "ya": "я", "Ts": "Ц", "TS": "Ц", "ts": "ц",
        "Ye": "Е", "YE": "Е", "ye": "е"
    }
    for lat, cyr in replacements.items(): text = text.replace(lat, cyr)
    text = re.sub(r'(^|\s|\n)E', r'\1Э', text)
    text = re.sub(r'(^|\s|\n)e', r'\1э', text)
    text = text.replace('E', 'Е').replace('e', 'е').replace("'", "ъ")
    latin_to_cyr = {'A': 'А', 'a': 'а', 'B': 'Б', 'b': 'б', 'V': 'В', 'v': 'в', 'G': 'Г', 'g': 'г', 'D': 'Д', 'd': 'д', 'J': 'Ж', 'j': 'ж', 'Z': 'З', 'z': 'з', 'I': 'И', 'i': 'и', 'Y': 'Й', 'y': 'й', 'K': 'К', 'k': 'к', 'L': 'Л', 'l': 'л', 'M': 'М', 'm': 'м', 'N': 'Н', 'n': 'н', 'O': 'О', 'o': 'о', 'P': 'П', 'p': 'п', 'R': 'Р', 'r': 'р', 'S': 'С', 's': 'с', 'T': 'Т', 't': 'т', 'U': 'У', 'u': 'у', 'F': 'Ф', 'f': 'ф', 'X': 'Х', 'x': 'х', 'Q': 'Қ', 'q': 'қ', 'H': 'Ҳ', 'h': 'ҳ'}
    res = ""
    for char in text: res += latin_to_cyr.get(char, char)
    return res

def to_latin(text):
    cyr_to_latin = {'А': 'A', 'а': 'a', 'Б': 'B', 'б': 'b', 'В': 'V', 'в': 'v', 'Г': 'G', 'г': 'g', 'Д': 'D', 'д': 'd', 'Ё': 'Yo', 'ё': 'yo', 'Ж': 'J', 'ж': 'j', 'З': 'Z', 'з': 'z', 'И': 'I', 'и': 'i', 'Й': 'Y', 'й': 'y', 'К': 'K', 'к': 'k', 'Л': 'L', 'л': 'l', 'М': 'M', 'м': 'm', 'Н': 'N', 'н': 'n', 'О': 'O', 'о': 'o', 'П': 'P', 'п': 'p', 'Р': 'R', 'р': 'r', 'С': 'S', 'с': 's', 'Т': 'T', 'т': 't', 'У': 'U', 'у': 'u', 'Ф': 'F', 'ф': 'f', 'Х': 'X', 'х': 'x', 'Ц': 'Ts', 'ц': 'ts', 'Ч': 'Ch', 'ч': 'ch', 'Ш': 'Sh', 'ш': 'sh', 'Ъ': "'", 'ъ': "'", 'Ь': "", 'ь': "", 'Э': 'E', 'э': 'e', 'Ю': 'Yu', 'ю': 'yu', 'Я': 'Ya', 'я': 'ya', 'Ў': "O'", 'ў': "o'", 'Қ': 'Q', 'қ': 'q', 'Ғ': "G'", 'ғ': "g'", 'Ҳ': 'H', 'ҳ': 'h', 'Щ': 'Shch', 'щ': 'shch', 'Ы': 'Y', 'ы': 'y'}
    res = ""
    for i, char in enumerate(text):
        if char == 'Е':
            res += "Ye" if (i == 0 or text[i-1] in "АЕЁИОУЭЮЯаеёиоуэюя \n\t\"'([") else "E"
        elif char == 'е':
            res += "ye" if (i == 0 or text[i-1] in "АЕЁИОУЭЮЯаеёиоуэюя \n\t\"'([") else "e"
        else:
            res += cyr_to_latin.get(char, char)
    return res

# --- PDF BILAN ISHLASH (dizayn saqlanadi) ---
try:
    import pymupdf as fitz
except ImportError:  # eski PyMuPDF versiyalari
    import fitz

# ------------------------------------------------------------
#  SHRIFTLAR: kirill va o'zbek harflarini (Ў Қ Ғ Ҳ) qo'llaydigan shriftlar
# ------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIRS = [
    _HERE, os.path.join(_HERE, "fonts"),
    "/usr/share/fonts/truetype/liberation", "/usr/share/fonts/truetype/liberation2",
    "/usr/share/fonts/liberation", "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu",
    "C:\\Windows\\Fonts", "/Library/Fonts", "/System/Library/Fonts/Supplemental",
]
# (oddiy, qalin, kursiv, qalin+kursiv) fayl nomlari; chapdagisi afzal
FONT_FAMILIES = {
        "sans": [
        ("JosefinSans-Regular.ttf", "JosefinSans-Bold.ttf", "JosefinSans-Italic.ttf", "JosefinSans-BoldItalic.ttf"), # <-- Josefin Sans
        ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf", "LiberationSans-Italic.ttf", "LiberationSans-BoldItalic.ttf"),
        ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
        ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf"),
    ],
}
_font_cache = {}

def _find_font_file(name):
    for d in FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None

def _load_font(path):
    if path not in _font_cache:
        try:
            _font_cache[path] = fitz.Font(fontfile=path)
        except Exception:
            _font_cache[path] = None
    return _font_cache[path]

def _covers(font, text):
    return all(ch.isspace() or font.has_glyph(ord(ch)) for ch in text)

def pick_fallback_font(span, text):
    """Span uslubiga (serif/mono, qalin, kursiv) mos va barcha harflarni qo'llaydigan shrift."""
    flags, name = span["flags"], span["font"].lower()
    bold = bool(flags & 16) or any(k in name for k in ("bold", "black", "heavy", "semibold"))
    italic = bool(flags & 2) or any(k in name for k in ("italic", "oblique"))
    sans_hint = any(k in name for k in ("sans", "arial", "helvet", "calibri", "verdana", "tahoma", "segoe", "roboto", "opensans"))
    if flags & 8 or any(k in name for k in ("mono", "courier", "consolas")):
        fam = "mono"
    elif not sans_hint and (flags & 4 or any(k in name for k in ("times", "serif", "georgia", "garamond", "cambria", "book"))):
        fam = "serif"
    else:
        fam = "sans"
    idx = (1 if bold else 0) + (2 if italic else 0)
    for family in (fam, "sans", "serif"):
        for files in FONT_FAMILIES[family]:
            path = _find_font_file(files[idx])
            if path:
                font = _load_font(path)
                if font and _covers(font, text):
                    return font
    return None

def fonts_available():
    return pick_fallback_font({"flags": 0, "font": ""}, "АаЎўҚқҒғҲҳ") is not None

def _original_font(doc, page_fonts, span, text):
    """Asl shrift to'liq joylangan bo'lsa va kerakli harflari bo'lsa - o'shani ishlatamiz."""
    xref = page_fonts.get(span["font"])
    if not xref:
        return None
    key = ("orig", xref)
    if key not in _font_cache:
        font = None
        try:
            _, ext, _, content = doc.extract_font(xref)
            if content and ext in ("ttf", "otf", "ttc"):
                font = fitz.Font(fontbuffer=content)
        except Exception:
            font = None
        _font_cache[key] = font
    font = _font_cache[key]
    if font and _covers(font, text):
        return font
    return None

def _rgb(color_int):
    return (((color_int >> 16) & 255) / 255, ((color_int >> 8) & 255) / 255, (color_int & 255) / 255)

# ------------------------------------------------------------
#  ASOSIY FUNKSIYALAR
# ------------------------------------------------------------
def count_pdf_scripts(path):
    import re
    lat = cyr = 0
    with fitz.open(path) as doc:
        for page in doc:
            t = page.get_text()
            lat += len(re.findall(r'[a-zA-Z]', t))
            cyr += len(re.findall(r'[а-яА-ЯёЁўқғҳЎҚҒҲ]', t))
    return lat, cyr

def convert_pdf_inplace(in_path, out_path, convert, progress=None):
    """PDF dizaynini (rasm, jadval, rang, joylashuv) saqlab, faqat matnni almashtiradi.
    Qaytaradi: o'zgartirilgan span soni."""
    doc = fitz.open(in_path)
    changed = 0
    total = len(doc)
    for pno, page in enumerate(doc):
        if progress:
            progress(pno, total)
        page_fonts = {f[3]: f[0] for f in page.get_fonts(full=True)}
        items = []  # (rect, new_text, origin, size, color, font)
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                dx, dy = line["dir"]
                if abs(dx - 1) > 0.01 or abs(dy) > 0.01:   # gorizontal bo'lmagan matnni tegmaymiz
                    continue
                spans = line["spans"]
                for si, span in enumerate(spans):
                    text = span["text"]
                    if not text.strip():
                        continue
                    new_text = convert(text)
                    if new_text == text:
                        continue
                    # shu matn sig'ishi mumkin bo'lgan kenglik
                    x0, x1 = span["bbox"][0], span["bbox"][2]
                    nxt = next((sp for sp in spans[si + 1:] if sp["text"].strip()), None)
                    if nxt:
                        limit = max(x1 - x0, nxt["bbox"][0] - x0 - 2)
                    else:
                        limit = min((x1 - x0) * 1.25 + 2, page.rect.x1 - 30 - x0)
                        limit = max(limit, x1 - x0)
                    font = _original_font(doc, page_fonts, span, new_text) or pick_fallback_font(span, new_text)
                    if font is None:
                        raise RuntimeError("FONT_NOT_FOUND")
                    items.append((fitz.Rect(span["bbox"]), new_text, span["origin"], span["size"], span["color"], font, limit))
        if not items:
            continue

        # 1) eski matnni olib tashlaymiz (rasm va chiziqlar tegilmaydi)
        for rect, *_ in items:
            r = fitz.Rect(rect.x0 + 0.3, rect.y0 + 0.8, rect.x1 - 0.3, rect.y1 - 0.8)
            if r.is_empty:
                r = rect
            page.add_redact_annot(r, fill=False)
        try:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
        except TypeError:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        # 2) yangi matnni xuddi shu joyga, shu rang va o'lchamda yozamiz
        writers = {}
        for rect, new_text, origin, size, color, font, width in items:
            text_w = font.text_length(new_text, fontsize=size)
            fs = size
            if width > 0 and text_w > width:
                fs = max(size * width / text_w, size * 0.6)   # sig'maydigan bo'lsa kichraytiramiz
            tw = writers.setdefault(color, fitz.TextWriter(page.rect))
            tw.append(origin, new_text, font=font, fontsize=fs)
            changed += 1
        for color, tw in writers.items():
            tw.write_text(page, color=_rgb(color))

    doc.save(out_path, garbage=3, deflate=True)
    doc.close()
    return changed


# ============================================================
#  BOSHQA FORMATLAR: TXT, DOCX, XLSX, PPTX, EPUB, FB2
# ============================================================
import io
import zipfile
try:
    from lxml import etree
except ImportError:      # pip install lxml
    etree = None

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
S_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NCX_NS = "{http://www.daisy.org/z3986/2005/ncx/}"
DC_NS = "{http://purl.org/dc/elements/1.1/}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

HTML_INLINE = {"a", "span", "b", "i", "em", "strong", "u", "small", "big", "sub", "sup", "code", "font",
               "abbr", "cite", "q", "s", "strike", "mark", "ins", "del", "tt", "kbd", "samp", "var",
               "dfn", "label", "bdi", "bdo", "time", "data", "br", "img", "wbr", "ruby", "rt", "rp"}
HTML_SKIP = {"script", "style"}
FB2_INLINE = {"emphasis", "strong", "strikethrough", "sub", "sup", "code", "style", "a", "image"}
FB2_SKIP = {"binary", "genre", "id", "lang", "src-lang", "date", "version", "program-used",
            "home-page", "email", "src-url", "src-ocr", "isbn", "year", "city"}

_RE_LAT = re.compile(r'[a-zA-Z]')
_RE_CYR = re.compile(r'[а-яА-ЯёЁўқғҳЎҚҒҲ]')
MAX_UNZIPPED_MB = 400    # zip-bomba himoyasi

def count_scripts_text(text):
    return len(_RE_LAT.findall(text)), len(_RE_CYR.findall(text))

def convert_group(texts, convert):
    """Bir abzats ichidagi ketma-ket matn bo'laklarini (run) birgalikda o'giradi, shunda
    'Sh', 'Ch', "O'" kabi harf birikmalari bo'laklarga bo'linib qolsa ham to'g'ri chiqadi,
    har bir bo'lak o'z formatlashida (qalin, kursiv, rang) qoladi.
    O'zgarish bo'lmasa, o'sha ro'yxatning o'zini qaytaradi."""
    src = "".join(texts)
    if not src.strip():
        return texts
    full = convert(src)
    if full == src:
        return texts
    if len(texts) == 1:
        return [full]
    if len(texts) > 200:                      # juda uzun abzats: har birini alohida o'giramiz
        return [convert(t) for t in texts]
    out = [""] * len(texts)
    cum_prev, prefix, start = "", "", 0
    last = len(texts) - 1
    for i, t in enumerate(texts):
        prefix += t
        c = full if i == last else convert(prefix)
        if full.startswith(c) and len(c) >= len(cum_prev):
            piece = full[len(cum_prev):len(c)]
            pos = 0
            for r in range(start, i):             # xavfsiz bo'lmagan chegaralar: harflar o'z bo'lagida qoladi
                k = len(convert(texts[r]))
                out[r] = piece[pos:pos + k]
                pos += k
            out[i] = piece[pos:]
            cum_prev, start = c, i + 1
    return out

def _local(el):
    return etree.QName(el).localname

def _parse_xml(data):
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    try:
        return etree.parse(io.BytesIO(data), parser)
    except etree.XMLSyntaxError:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True, recover=True)
        return etree.parse(io.BytesIO(data), parser)

# --- matn bo'laklarini guruhlash (har bir guruh = bitta abzats) ---
def group_by_block(root, text_tag, block_tags, skip_under=()):
    groups = {}
    for el in root.iter(text_tag):
        if skip_under and any(a.tag in skip_under for a in el.iterancestors()):
            continue
        key = next((a for a in el.iterancestors() if a.tag in block_tags), root)
        groups.setdefault(key, []).append((el, "text"))
    return list(groups.values())

def group_each(root, tags):
    return [[(el, "text")] for el in root.iter(*tags) if el.text]

def _walk(root):
    """Hujjat tartibida (node,'text') va (node,'tail') ni beradi."""
    stack = [(root, False)]
    while stack:
        node, done = stack.pop()
        if done:
            yield node, "tail"
            continue
        if isinstance(node.tag, str):
            yield node, "text"
        stack.append((node, True))
        for ch in reversed(list(node)):
            stack.append((ch, False))

def group_html(root, inline, skip):
    def block_of(el):
        while el is not None:
            if isinstance(el.tag, str) and _local(el) not in inline:
                return el
            el = el.getparent()
        return root

    def in_skip(el):
        while el is not None:
            if isinstance(el.tag, str) and _local(el) in skip:
                return True
            el = el.getparent()
        return False

    groups = {}
    for node, kind in _walk(root):
        if kind == "text":
            if not node.text or in_skip(node):
                continue
            key = block_of(node)
        else:
            if not node.tail or node is root:
                continue
            parent = node.getparent()
            if parent is None or in_skip(parent):
                continue
            if isinstance(node.tag, str) and _local(node) not in inline:
                key = ("tail", node)          # blok elementdan keyingi matn - alohida abzats
            else:
                key = block_of(parent)
        groups.setdefault(key, []).append((node, kind))
    return list(groups.values())

def apply_groups(groups, convert, preserve_space=False):
    changed = 0
    for g in groups:
        texts = [((n.text if k == "text" else n.tail) or "") for n, k in g]
        new = convert_group(texts, convert)
        if new is texts:
            continue
        for (n, k), old, nw in zip(g, texts, new):
            if nw == old:
                continue
            if k == "text":
                n.text = nw
                if preserve_space and nw != nw.strip():
                    n.set(XML_SPACE, "preserve")
            else:
                n.tail = nw
            changed += 1
    return changed

# --- Word tilini ham o'zgartiramiz (imlo tekshiruvi to'g'ri ishlashi uchun) ---
def _fix_word_lang(root, to_cyr):
    old, new = ("Latn", "Cyrl") if to_cyr else ("Cyrl", "Latn")
    for el in root.iter(W_NS + "lang"):
        for attr in ("val", "eastAsia", "bidi"):
            v = el.get(W_NS + attr)
            if v and v.lower().startswith("uz") and old in v:
                el.set(W_NS + attr, v.replace(old, new))

# --- har bir format uchun qoidalar: (fayl nomi namunasi, guruhlovchi, preserve_space, post) ---
def _rules_for(ext, to_cyr=None):
    if ext == ".docx":
        return [(re.compile(r'^word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml$'),
                 lambda r: group_by_block(r, W_NS + "t", {W_NS + "p"}), True,
                 (lambda r: _fix_word_lang(r, to_cyr)) if to_cyr is not None else None)]
    if ext == ".pptx":
        return [(re.compile(r'^ppt/(slides/slide\d+|notesSlides/notesSlide\d+)\.xml$'),
                 lambda r: group_by_block(r, A_NS + "t", {A_NS + "p"}), False, None)]
    if ext == ".xlsx":
        return [
            (re.compile(r'^xl/sharedStrings\.xml$'),
             lambda r: group_by_block(r, S_NS + "t", {S_NS + "si"}, skip_under={S_NS + "rPh"}), True, None),
            (re.compile(r'^xl/worksheets/sheet\d+\.xml$'),
             lambda r: group_by_block(r, S_NS + "t", {S_NS + "is"}, skip_under={S_NS + "rPh"}), True, None),
            (re.compile(r'^xl/comments\d*\.xml$'),
             lambda r: group_by_block(r, S_NS + "t", {S_NS + "text"}, skip_under={S_NS + "rPh"}), True, None),
        ]
    if ext == ".epub":
        return [
            (re.compile(r'\.(xhtml|html|htm)$', re.I), lambda r: group_html(r, HTML_INLINE, HTML_SKIP), False, None),
            (re.compile(r'\.ncx$', re.I), lambda r: group_each(r, [NCX_NS + "text"]), False, None),
            (re.compile(r'\.opf$', re.I),
             lambda r: group_each(r, [DC_NS + t for t in ("title", "creator", "description", "publisher", "subject")]), False, None),
        ]
    return []

def process_zip_file(in_path, out_path, convert, ext, to_cyr=None, count_only=False):
    """DOCX/XLSX/PPTX/EPUB: ichidagi XML fayllarda matnni almashtiradi, qolgan hamma narsa
    (rasm, uslub, jadval, jadval formulalari...) bayt-bayt o'zgarishsiz ko'chiriladi."""
    rules = _rules_for(ext, to_cyr)
    lat = cyr = changed = 0
    with zipfile.ZipFile(in_path) as zin:
        if sum(i.file_size for i in zin.infolist()) > MAX_UNZIPPED_MB * 1024 * 1024:
            raise ValueError("ZIP_TOO_BIG")
        zout = None if count_only else zipfile.ZipFile(out_path, "w")
        try:
            for item in zin.infolist():
                data = zin.read(item.filename)
                for pattern, grouper, preserve, post in rules:
                    if not pattern.search(item.filename):
                        continue
                    try:
                        tree = _parse_xml(data)
                        groups = grouper(tree.getroot())
                    except Exception:
                        break                      # o'qib bo'lmasa, o'zgarishsiz qoldiramiz
                    if count_only:
                        for g in groups:
                            l, c = count_scripts_text("".join((n.text if k == "text" else n.tail) or "" for n, k in g))
                            lat += l
                            cyr += c
                    else:
                        changed += apply_groups(groups, convert, preserve)
                        if post:
                            post(tree.getroot())
                        was_standalone = bool(re.search(rb"standalone\s*=\s*['\"]yes", data[:300]))
                        data = etree.tostring(tree, xml_declaration=True, encoding="UTF-8",
                                              standalone=True if was_standalone else None)
                    break
                if zout:
                    zout.writestr(item, data)
        finally:
            if zout:
                zout.close()
    return (lat, cyr) if count_only else changed

def process_fb2(in_path, out_path, convert, count_only=False):
    with open(in_path, "rb") as f:
        data = f.read()
    tree = _parse_xml(data)
    groups = group_html(tree.getroot(), FB2_INLINE, FB2_SKIP)
    if count_only:
        lat = cyr = 0
        for g in groups:
            l, c = count_scripts_text("".join((n.text if k == "text" else n.tail) or "" for n, k in g))
            lat += l
            cyr += c
        return lat, cyr
    changed = apply_groups(groups, convert)
    with open(out_path, "wb") as f:
        f.write(etree.tostring(tree, xml_declaration=True, encoding="UTF-8"))
    return changed

def read_text_file(path):
    with open(path, "rb") as f:
        data = f.read()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), "utf-16"
    try:
        if data.startswith(b"\xef\xbb\xbf"):
            return data.decode("utf-8-sig"), "utf-8-sig"
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1251", errors="replace"), "utf-8"   # eski kirill kodirovkasi

def process_txt(in_path, out_path, convert, count_only=False):
    text, enc = read_text_file(in_path)
    if count_only:
        return count_scripts_text(text)
    with open(out_path, "w", encoding=enc, newline="") as f:
        f.write(convert(text))
    return 1

# --- umumiy kirish nuqtalari ---
OFFICE_EXTS = (".docx", ".xlsx", ".pptx", ".epub")
SUPPORTED_EXTS = (".pdf", ".txt", ".docx", ".xlsx", ".pptx", ".epub", ".fb2")
UNSUPPORTED_MSG = "❌ Iltimos, faqat PDF, TXT, DOCX, XLSX, PPTX, EPUB, FB2 fayl yuboring."

def count_scripts_file(ext, path):
    if ext == ".pdf":
        return count_pdf_scripts(path)
    if ext == ".txt":
        return process_txt(path, None, None, count_only=True)
    if ext == ".fb2":
        return process_fb2(path, None, None, count_only=True)
    return process_zip_file(path, None, None, ext, count_only=True)

def convert_file(ext, in_path, out_path, convert, to_cyr, progress=None):
    if ext == ".pdf":
        return convert_pdf_inplace(in_path, out_path, convert, progress=progress)
    if ext == ".txt":
        return process_txt(in_path, out_path, convert)
    if ext == ".fb2":
        return process_fb2(in_path, out_path, convert)
    return process_zip_file(in_path, out_path, convert, ext, to_cyr=to_cyr)


MAX_PDF_MB = 20          # Telegram botlar uchun yuklab olish chegarasi
MAX_PAGES = 1000         # bir PDF dagi maksimal sahifa
_busy_users = set()      # bir foydalanuvchi bir vaqtda bitta fayl

def handle_document(message, mode=None):
    """mode: 'cyr' (Lotin->Kirill), 'lat' (Kirill->Lotin), None (avtomatik aniqlash)"""
    doc = message.document
    chat_id = message.chat.id
    name = doc.file_name or "fayl"
    ext = os.path.splitext(name.lower())[1]
    if not ext and doc.mime_type == "application/pdf":
        ext = ".pdf"
    if ext in IMAGE_EXTS or (doc.mime_type or "").startswith("image/"):
        handle_image(message, mode)              # rasm fayli: ichidagi matn (OCR)
        return

    if ext not in SUPPORTED_EXTS:
        bot.send_message(chat_id, UNSUPPORTED_MSG)
        return
    if ext != ".pdf" and ext != ".txt" and etree is None:
        bot.send_message(chat_id, "❌ Serverda lxml kutubxonasi o'rnatilmagan. Admin: pip install lxml")
        return
    if doc.file_size and doc.file_size > MAX_PDF_MB * 1024 * 1024:
        bot.send_message(chat_id, f"❌ Fayl juda katta (maksimum {MAX_PDF_MB} MB).")
        return

    uid = message.from_user.id
    if uid in _busy_users:
        bot.send_message(chat_id, "⏳ Oldingi faylingiz hali o'girilmoqda. Tugashini kuting.")
        return
    _busy_users.add(uid)
    wait_msg = bot.send_message(chat_id, "⏳ Fayl o'girilmoqda. Iltimos kuting...")
    bot.send_chat_action(chat_id, 'upload_document')

    def say(text):
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=wait_msg.message_id)
        except Exception:
            bot.send_message(chat_id, text)

    in_path = out_path = None
    try:
        file_info = bot.get_file(doc.file_id)
        data = bot.download_file(file_info.file_path)
        fd, in_path = tempfile.mkstemp(suffix=ext)
        os.close(fd)
        with open(in_path, "wb") as f:
            f.write(data)

        if ext == ".pdf":
            with fitz.open(in_path) as _d:
                if _d.needs_pass:
                    say("❌ PDF parol bilan himoyalangan. Parolsiz fayl yuboring.")
                    return
                pages_total = len(_d)
            if pages_total > MAX_PAGES:
                say(f"❌ PDF juda uzun ({pages_total} sahifa). Maksimum {MAX_PAGES} sahifa. Faylni bo'lib yuboring.")
                return

        lat, cyr = count_scripts_file(ext, in_path)
        if lat + cyr == 0:
            if ext == ".pdf":
                say("❌ PDF ichida matn topilmadi. U skaner qilingan rasm bo'lishi mumkin (matn emas).")
            else:
                say("❌ Faylda o'girish uchun matn topilmadi.")
            return

        is_cyrillic = cyr > lat
        if mode == "cyr" and is_cyrillic:
            say("❌ Bu fayl kirillcha ekan. Lotincha fayl yuboring!")
            return
        if mode == "lat" and not is_cyrillic:
            say("❌ Bu fayl lotincha ekan. Kirillcha fayl yuboring!")
            return

        to_cyr = (mode == "cyr") or (mode is None and not is_cyrillic)
        convert = to_cyrillic if to_cyr else to_latin
        suffix = "_kirill" if to_cyr else "_lotin"
        label = "Kirill" if to_cyr else "Lotin"

        fd, out_path = tempfile.mkstemp(suffix=ext)
        os.close(fd)
        last = {"t": 0.0}
        def on_progress(done, total):
            now = time.time()
            if total > 20 and now - last["t"] >= 4:     # Telegram tez-tez tahrirlashga ruxsat bermaydi
                last["t"] = now
                try:
                    bot.edit_message_text(f"⏳ PDF o'girilmoqda: {done}/{total} sahifa ({done * 100 // total}%)", chat_id=chat_id, message_id=wait_msg.message_id)
                    bot.send_chat_action(chat_id, 'upload_document')
                except Exception:
                    pass

        convert_file(ext, in_path, out_path, convert, to_cyr, progress=on_progress)

        if os.path.getsize(out_path) > 49 * 1024 * 1024:
            say("❌ Natija fayl hajmi Telegram chegarasidan (50 MB) oshib ketdi. Faylni bo'lib yuboring.")
            return

        send_name = f"{os.path.splitext(name)[0]}{suffix}{ext}"
        with open(out_path, "rb") as f:
            bot.send_document(chat_id, f, visible_file_name=send_name, caption=f"📝 Natija ({label})")
        bot.delete_message(chat_id, wait_msg.message_id)

    except Exception as e:
        user_file_errors = (zipfile.BadZipFile,) + \
            ((etree.XMLSyntaxError,) if etree is not None else ()) + \
            ((fitz.FileDataError,) if hasattr(fitz, "FileDataError") else ())
        if isinstance(e, ValueError) and "ZIP_TOO_BIG" in str(e):
            say("❌ Fayl ichidagi ma'lumot hajmi juda katta. Kichikroq fayl yuboring.")
        elif isinstance(e, user_file_errors):
            # fayl buzilgan yoki noto'g'ri - bu foydalanuvchi faylining muammosi, admin bezovta qilinmaydi
            print("Fayl o'qilmadi:", repr(e))
            say("❌ Faylni o'qib bo'lmadi. U buzilgan yoki himoyalangan bo'lishi mumkin. Boshqa fayl yuboring.")
        else:
            hint = ""
            if isinstance(e, RuntimeError) and "FONT_NOT_FOUND" in str(e):
                hint = " | SERVER: kirill shrifti topilmadi - DejaVuSans.ttf ni main.py yoniga qo'ying"
            notify_admin("handle_document", e, message, extra=f"{name} ({ext}, {doc.file_size} bayt, rejim={mode}){hint}")
            say(GENERIC_ERROR_TEXT)          # foydalanuvchiga texnik tafsilot ko'rsatilmaydi
    finally:
        _busy_users.discard(uid)
        for p in (in_path, out_path):
            if p and os.path.exists(p):
                os.remove(p)

# --- MA'LUMOTLAR BAZASI ---
def init_db():
    with sqlite3.connect('bot_users.db', check_same_thread=False) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)')

def add_user(user_id):
    with sqlite3.connect('bot_users.db', check_same_thread=False) as conn:
        conn.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))

# ============================================================
#  RASM / VIDEO / AUDIO + IZOH (caption), FORMATLANGAN MATN
# ============================================================
MEDIA_TYPES = ('photo', 'video', 'animation', 'audio', 'voice')
# Shu turdagi bo'laklar o'girilmaydi (havola, @username, kod... buzilib qolmasligi uchun)
KEEP_ENTITY_TYPES = {"url", "email", "phone_number", "mention", "bot_command", "cashtag", "code", "pre", "custom_emoji"}
CAPTION_LIMIT = 1024     # Telegram: izoh uzunligi chegarasi
TEXT_LIMIT = 4000        # Telegram: xabar chegarasi 4096, xavfsiz zaxira bilan
ALBUM_WAIT = 1.5         # albom rasmlari ketma-ket kelishini kutish (soniya)
_albums = {}
_albums_lock = threading.Lock()

def utf16_len(s):
    return len(s.encode("utf-16-le")) // 2      # Telegram offsetlari UTF-16 birligida

def convert_with_entities(text, entities, convert):
    """Matnni o'giradi va qalin/kursiv/havola kabi formatlashni yangi joylarga ko'chiradi.
    Qaytaradi: (yangi_matn, yangi_entities)"""
    if not entities:
        return convert(text), []
    idx_of, u = {}, 0                            # UTF-16 offset -> Python indeksi
    for i, ch in enumerate(text):
        idx_of[u] = i
        u += 2 if ord(ch) > 0xFFFF else 1
    idx_of[u] = len(text)
    spans = []
    for e in entities:
        a, b = idx_of.get(e.offset), idx_of.get(e.offset + e.length)
        if a is not None and b is not None and b > a:
            spans.append((a, b, e))
    points = sorted({0, len(text)} | {a for a, _, _ in spans} | {b for _, b, _ in spans})
    segs = list(zip(points, points[1:]))

    def covered(a, b, kinds):
        return any(sa <= a and b <= sb and ent.type in kinds for sa, sb, ent in spans)

    out, group = [None] * len(segs), []

    def flush():
        if group:
            new = convert_group([text[segs[k][0]:segs[k][1]] for k in group], convert)
            for k, nt in zip(group, new):
                out[k] = nt
            group.clear()

    for k, (a, b) in enumerate(segs):
        if covered(a, b, KEEP_ENTITY_TYPES):
            flush()
            out[k] = text[a:b]
        else:
            group.append(k)
    flush()
    for k, (a, b) in enumerate(segs):            # hashtegda apostrof bo'lishi mumkin emas
        if covered(a, b, {"hashtag"}):
            out[k] = out[k].replace("'", "").replace("ʼ", "")

    pos, cum = {points[0]: 0}, 0
    for k, (a, b) in enumerate(segs):
        cum += utf16_len(out[k])
        pos[b] = cum
    new_entities = []
    for a, b, ent in spans:
        length = pos[b] - pos[a]
        if length > 0:
            ne = copy.copy(ent)
            ne.offset, ne.length = pos[a], length
            new_entities.append(ne)
    return "".join(out), new_entities

def _shift_entities(entities, shift):
    res = []
    for e in entities or []:
        ne = copy.copy(e)
        ne.offset = e.offset + shift
        res.append(ne)
    return res

def _split_text(text, limit=TEXT_LIMIT):
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    chunks.append(text)
    return chunks

def send_text_entities(chat_id, text, entities):
    """Matnni yuboradi (formatlash bilan). Juda uzun bo'lsa bo'laklarga bo'ladi."""
    if len(text) <= TEXT_LIMIT:
        bot.send_message(chat_id, text, entities=entities or None)
    else:
        for chunk in _split_text(text):
            bot.send_message(chat_id, chunk)

def send_result_text(chat_id, wait_msg_id, header, text, entities, convert):
    """Matn rejimi natijasi: 'Natija' sarlavhasi + o'girilgan matn (formatlash saqlanadi)."""
    new_text, new_ents = convert_with_entities(text, entities, convert)
    full = header + new_text
    if len(full) <= TEXT_LIMIT:
        bot.edit_message_text(full, chat_id=chat_id, message_id=wait_msg_id,
                              entities=_shift_entities(new_ents, utf16_len(header)) or None)
    else:
        chunks = _split_text(full)
        bot.edit_message_text(chunks[0], chat_id=chat_id, message_id=wait_msg_id)
        for chunk in chunks[1:]:
            bot.send_message(chat_id, chunk)

def _check_caption(caption, mode):
    """Izoh alifbosini tekshiradi. Qaytaradi: (convert_funksiyasi, xato_matni)"""
    lat, cyr = count_scripts_text(caption)
    if lat + cyr == 0:
        return None, "❌ Izohda o'girish uchun harflar topilmadi."
    is_cyrillic = cyr > lat
    if mode == "cyr" and is_cyrillic:
        return None, "❌ Iltimos, faqat lotincha matn kiriting!"
    if mode == "lat" and not is_cyrillic:
        return None, "❌ Iltimos, faqat kirillcha matn kiriting!"
    to_cyr = (mode == "cyr") or (mode is None and not is_cyrillic)
    return (to_cyrillic if to_cyr else to_latin), None

NO_CAPTION_TEXT = "ℹ️ Bu xabarda o'girish uchun matn (izoh) yo'q. Matni (izohi) bor rasm, video yoki audio yuboring."

def _send_media_only(chat_id, message):
    t, fid = message.content_type, None
    if t == 'photo':
        bot.send_photo(chat_id, message.photo[-1].file_id)
    elif t == 'video':
        bot.send_video(chat_id, message.video.file_id)
    elif t == 'animation':
        bot.send_animation(chat_id, message.animation.file_id)
    elif t == 'audio':
        bot.send_audio(chat_id, message.audio.file_id)
    elif t == 'voice':
        bot.send_voice(chat_id, message.voice.file_id)

def handle_media(message, mode=None):
    """Izohli rasm/video/GIF/audio/ovozli xabar: izoh o'giriladi, media o'zgarishsiz qayta yuboriladi.
    mode: 'cyr', 'lat' yoki None (avtomatik aniqlash)."""
    chat_id = message.chat.id
    if message.media_group_id:                   # albom (bir nechta rasm/video)
        collect_album(message, mode)
        return
    if not message.caption:
        if message.content_type == 'photo':
            handle_image(message, mode)          # izohsiz rasm: ichidagi matnni o'qiymiz (OCR)
        else:
            bot.send_message(chat_id, NO_CAPTION_TEXT)
        return
    convert, err = _check_caption(message.caption, mode)
    if err:
        bot.send_message(chat_id, err)
        return
    new_cap, new_ents = convert_with_entities(message.caption, message.caption_entities, convert)
    if len(new_cap) <= CAPTION_LIMIT:
        extra = {}
        if getattr(message, "show_caption_above_media", None):
            extra["show_caption_above_media"] = True
        bot.copy_message(chat_id, chat_id, message.message_id, caption=new_cap,
                         caption_entities=new_ents or None, **extra)
    else:                                         # izoh 1024 belgidan oshsa: media alohida, matn alohida
        _send_media_only(chat_id, message)
        send_text_entities(chat_id, new_cap, new_ents)

def collect_album(message, mode):
    key = (message.chat.id, message.media_group_id)
    with _albums_lock:
        entry = _albums.setdefault(key, {"msgs": [], "mode": mode, "timer": None})
        if mode and not entry["mode"]:
            entry["mode"] = mode
        entry["msgs"].append(message)
        if entry["timer"]:
            entry["timer"].cancel()
        entry["timer"] = threading.Timer(ALBUM_WAIT, _process_album_safe, args=(key,))
        entry["timer"].daemon = True
        entry["timer"].start()

def _process_album_safe(key):
    with _albums_lock:
        entry = _albums.pop(key, None)
    if not entry:
        return
    msgs = entry["msgs"]
    try:
        process_album(msgs, entry["mode"])
    except Exception as e:
        notify_admin("process_album", e, msgs[0])
        try:
            bot.send_message(msgs[0].chat.id, GENERIC_ERROR_TEXT)
        except Exception:
            pass

def process_album(msgs, mode):
    msgs = sorted(msgs, key=lambda m: m.message_id)
    chat_id = msgs[0].chat.id
    cap_msg = next((m for m in msgs if m.caption), None)
    if not cap_msg:
        photos = [m for m in msgs if m.content_type == 'photo']
        if photos:                               # izohsiz albom: har bir rasm alohida o'qiladi
            for m in photos[:10]:
                handle_image(m, mode)
        else:
            bot.send_message(chat_id, NO_CAPTION_TEXT)
        return
    convert, err = _check_caption(cap_msg.caption, mode)
    if err:
        bot.send_message(chat_id, err)
        return
    new_cap, new_ents = convert_with_entities(cap_msg.caption, cap_msg.caption_entities, convert)
    short = len(new_cap) <= CAPTION_LIMIT
    media = []
    for i, m in enumerate(msgs[:10]):
        kw = {}
        if i == 0 and short:
            kw = {"caption": new_cap, "caption_entities": new_ents or None}
        if m.content_type == 'photo':
            media.append(types.InputMediaPhoto(m.photo[-1].file_id, has_spoiler=getattr(m, "has_media_spoiler", None) or None, **kw))
        elif m.content_type == 'video':
            media.append(types.InputMediaVideo(m.video.file_id, has_spoiler=getattr(m, "has_media_spoiler", None) or None, **kw))
        elif m.content_type == 'audio':
            media.append(types.InputMediaAudio(m.audio.file_id, **kw))
    if not media:
        bot.send_message(chat_id, UNSUPPORTED_MSG)
        return
    bot.send_media_group(chat_id, media)
    if not short:
        send_text_entities(chat_id, new_cap, new_ents)

# ============================================================
#  RASM ICHIDAGI MATN (OCR) - Tesseract
# ============================================================
try:
    import pytesseract
    from pytesseract import Output
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except ImportError:          # pip install pytesseract pillow
    pytesseract = None
    Image = None

OCR_LANGS = ("uzb", "uzb_cyrl")             # lotin + kirill modellari birga
TESSDATA_DIR = os.path.join(_HERE, "tessdata")
TESSDATA_URL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/{}.traineddata"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
OCR_MIN_CONF = 45                           # bundan past ishonchli so'zlar tashlab yuboriladi
OCR_TIMEOUT = 60

def ensure_ocr_ready():
    """Tesseract va o'zbek til ma'lumotlarini tekshiradi (til fayllarini o'zi yuklab oladi)."""
    if pytesseract is None:
        raise RuntimeError("OCR_LIBS_NOT_FOUND")
    if not shutil.which(pytesseract.pytesseract.tesseract_cmd):
        raise RuntimeError("TESSERACT_NOT_FOUND")
    os.makedirs(TESSDATA_DIR, exist_ok=True)
    for lang in OCR_LANGS:
        path = os.path.join(TESSDATA_DIR, lang + ".traineddata")
        if not os.path.exists(path) or os.path.getsize(path) < 100000:
            tmp = path + ".part"
            urllib.request.urlretrieve(TESSDATA_URL.format(lang), tmp)
            os.replace(tmp, path)

# Ikki alifboda bir xil ko'rinadigan harflar (OCR ularni ko'pincha adashtiradi)
_CYR_LOOK = "АВЕКМНОРСТХаеорсху"
_LAT_LOOK = "ABEKMHOPCTXaeopcxy"
_TO_LAT = str.maketrans(_CYR_LOOK, _LAT_LOOK)
_TO_CYR = str.maketrans(_LAT_LOOK, _CYR_LOOK)

def _clean_tokens(tokens):
    """Bir qatordagi so'zlardan OCR 'axlati'ni olib tashlaydi (emoji, belgi, logotipdan chiqqan harflar)."""
    kept = [t for t in tokens if any(ch.isalnum() for ch in t["text"])]       # faqat belgilar - tashlanadi
    if len(kept) >= 3:
        def lone(t):                                  # yolg'iz harf ('u'/'U' - haqiqiy so'z, qoldiramiz)
            x = t["text"]
            return len(x) == 1 and x.isalpha() and x not in "uUуУ"
        for idx in (-1, 0):                           # chetdagi yolg'iz harf = ko'pincha emoji
            if len(kept) >= 3 and lone(kept[idx]):
                kept.pop(idx)
        kept = [t for t in kept if not (lone(t) and t["text"].isupper())]   # o'rtadagi yolg'iz bosh harf
    return kept

def _fix_lookalikes(all_tokens):
    """Rasm asosan lotin (yoki kirill) bo'lsa, boshqa alifbodagi o'xshash harflardan iborat so'zlarni
    (masalan lotin matn ichidagi 'Тор') asosiy alifboga qaytaradi."""
    text = " ".join(t["text"] for t in all_tokens)
    lat, cyr = count_scripts_text(text)
    if lat + cyr < 8:
        return
    if lat >= 0.7 * (lat + cyr):
        table, minor = _TO_LAT, _RE_CYR
    elif cyr >= 0.7 * (lat + cyr):
        table, minor = _TO_CYR, _RE_LAT
    else:
        return
    for t in all_tokens:
        letters = [ch for ch in t["text"] if ch.isalpha()]
        if letters and all(minor.match(ch) and ch in (_CYR_LOOK + _LAT_LOOK) for ch in letters):
            t["text"] = t["text"].translate(table)

def ocr_lines(img):
    """Rasmdan qatorlarni o'qiydi. Qaytaradi: (qatorlar, o'rtacha_ishonch).
    qator = dict(text, box=(x0,y0,x1,y1), block, par)  - koordinatalar asl rasm o'lchamida."""
    ensure_ocr_ready()
    img = img.convert("RGB")
    scale = 1.0
    longest = max(img.size)
    if longest < 1200:                       # kichik rasmni kattalashtirsak aniqroq o'qiladi
        scale = 2.0 if longest >= 500 else 3.0
    elif longest > 4000:
        scale = 4000.0 / longest
    work = img if scale == 1.0 else img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    data = pytesseract.image_to_data(work, lang="+".join(OCR_LANGS), output_type=Output.DICT, timeout=OCR_TIMEOUT,
                                     config=f'--tessdata-dir "{TESSDATA_DIR}" --psm 3')
    raw = {}
    for i, text in enumerate(data["text"]):
        text = text.strip()
        try:
            conf = float(data["conf"][i])
        except ValueError:
            continue
        if not text or conf < OCR_MIN_CONF:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        x0, y0 = data["left"][i], data["top"][i]
        raw.setdefault(key, []).append({"text": text, "conf": conf, "box": (x0, y0, x0 + data["width"][i], y0 + data["height"][i])})

    kept_lines = {k: _clean_tokens(v) for k, v in sorted(raw.items())}
    kept_lines = {k: v for k, v in kept_lines.items() if v}
    _fix_lookalikes([t for v in kept_lines.values() for t in v])

    result, total_w, total_c = [], 0, 0.0
    for key, toks in kept_lines.items():
        x0 = min(t["box"][0] for t in toks); y0 = min(t["box"][1] for t in toks)
        x1 = max(t["box"][2] for t in toks); y1 = max(t["box"][3] for t in toks)
        result.append({"text": " ".join(t["text"] for t in toks), "block": key[0], "par": key[1],
                       "box": (int(x0 / scale), int(y0 / scale), int(x1 / scale), int(y1 / scale))})
        for t in toks:
            total_c += t["conf"] * len(t["text"])
            total_w += len(t["text"])
    return result, (total_c / total_w if total_w else 0.0)

def lines_to_text(lines):
    """Qatorlarni abzatslarga ajratib matn qiladi."""
    out, prev = [], None
    for ln in lines:
        key = (ln["block"], ln["par"])
        if prev is not None and key != prev:
            out.append("")
        out.append(ln["text"])
        prev = key
    return "\n".join(out)

# --- rasm ustida matnni almashtirish ---
def _ring_color(img, box, pad=3):
    """Matn qutisi atrofidagi fon rangi (median)."""
    x0, y0, x1, y1 = box
    W, H = img.size
    px = []
    for x in range(max(0, x0 - pad), min(W, x1 + pad), max(1, (x1 - x0) // 40)):
        for y in (max(0, y0 - pad), min(H - 1, y1 + pad - 1)):
            px.append(img.getpixel((x, y)))
    for y in range(max(0, y0 - pad), min(H, y1 + pad), max(1, (y1 - y0) // 15)):
        for x in (max(0, x0 - pad), min(W - 1, x1 + pad - 1)):
            px.append(img.getpixel((x, y)))
    if not px:
        return (255, 255, 255)
    return tuple(sorted(p[c] for p in px)[len(px) // 2] for c in range(3))

def _text_color(img, box, bg):
    """Matn rangi: qutidagi fondan eng farq qiladigan piksellar medianasi."""
    crop = img.crop(box)
    pix = list(crop.getdata())
    if not pix:
        return (0, 0, 0)
    dist = lambda p: sum(abs(p[c] - bg[c]) for c in range(3))
    pix.sort(key=dist, reverse=True)
    top = pix[:max(3, len(pix) // 12)]
    col = tuple(sorted(p[c] for p in top)[len(top) // 2] for c in range(3))
    if dist(col) < 90:                       # farq kichik bo'lsa, kontrastli rang tanlaymiz
        lum = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
        return (0, 0, 0) if lum > 140 else (255, 255, 255)
    return col

def _pil_font(text, size, bold=False):
    idx = 1 if bold else 0
    for files in FONT_FAMILIES["sans"]:
        path = _find_font_file(files[idx])
        if path:
            f = _load_font(path)
            if f and _covers(f, text):
                return ImageFont.truetype(path, max(6, int(size)))
    return None

def _edge_color(img, x, y, vertical=True):
    """Nuqta atrofidagi rangning medianasi (3 piksellik chiziq bo'yicha)."""
    W, H = img.size
    x = min(max(x, 0), W - 1)
    pts = [img.getpixel((x, min(max(y + d, 0), H - 1))) for d in (-1, 0, 1)]
    return tuple(sorted(p[c] for p in pts)[1] for c in range(3))

def _busy_background(img, box, pad=3):
    """Qutining yuqori va pastki chetida fon 'to'qimali' (rasm, surat) bo'lsa True.
    Silliq gradient yoki bir xil fonda False."""
    x0, y0, x1, y1 = box
    W, H = img.size
    diffs = []
    for y in (max(0, y0 - pad), min(H - 1, y1 + pad - 1)):
        prev = None
        for x in range(max(0, x0), min(W, x1)):
            p = img.getpixel((x, y))
            if prev is not None:
                diffs.append(sum(abs(p[c] - prev[c]) for c in range(3)))
            prev = p
    return bool(diffs) and (sum(diffs) / len(diffs)) > 18

def _fill_box(img, box, pad=3):
    """Qutini fon bilan to'ldiradi: har bir qatorda chap va o'ng chetdagi ranglar orasida silliq o'tish
    (gradient fonda ham yassi dog' qolmaydi)."""
    x0, y0, x1, y1 = box
    W, H = img.size
    x0, y0, x1, y1 = max(0, x0 - 2), max(0, y0 - 2), min(W, x1 + 2), min(H, y1 + 2)
    bw, bh = x1 - x0, y1 - y0
    if bw <= 0 or bh <= 0:
        return
    data = []
    for y in range(y0, y1):
        left = _edge_color(img, x0 - pad, y)
        right = _edge_color(img, x1 + pad - 1, y)
        if bw == 1:
            data.append(left)
            continue
        for i in range(bw):
            t = i / (bw - 1)
            data.append((int(left[0] + (right[0] - left[0]) * t),
                         int(left[1] + (right[1] - left[1]) * t),
                         int(left[2] + (right[2] - left[2]) * t)))
    patch = Image.new("RGB", (bw, bh))
    patch.putdata(data)
    img.paste(patch, (x0, y0))

def _matched_size(text, width, bold):
    """Shu matn berilgan kenglikka sig'adigan shrift o'lchami."""
    f = _pil_font(text, 100, bold)
    if f is None:
        return None
    w = ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(text, font=f)
    return width * 100.0 / w if w > 0 else None

def redraw_image(img, lines, new_texts):
    """Har bir qator joyini fon bilan yopib, o'girilgan matnni xuddi shu joyga, shu rangda yozadi."""
    img = img.convert("RGB")
    W = img.width
    blocks = {}
    for ln in lines:
        blocks.setdefault((ln["block"], ln["par"]), []).append(ln)
    align = {}
    for key, group in blocks.items():                 # chapga yoki markazga tekislanganmi?
        lefts = [g["box"][0] for g in group]
        centers = [(g["box"][0] + g["box"][2]) / 2 for g in group]
        if len(group) > 1 and (max(lefts) - min(lefts)) > 0.03 * W and (max(centers) - min(centers)) <= 0.03 * W:
            align[key] = "center"
        else:
            align[key] = "left"

    # 1) asl qatorlardan rang, qalinlik va o'lchamni o'lchaymiz (fonni o'zgartirishdan oldin)
    info = []
    for ln in lines:
        box = ln["box"]
        bw = max(1, box[2] - box[0])
        bg = _ring_color(img, box)
        col = _text_color(img, box, bg)
        size = _matched_size(ln["text"], bw, False)
        bold = False
        if size:
            crop = list(img.crop(box).getdata())
            dist = lambda p: sum(abs(p[c] - bg[c]) for c in range(3))
            dd = max(1, dist(col))
            ink = sum(1 for p in crop if dist(p) > 0.5 * dd)
            bh_line = max(1, box[3] - box[1])
            if bh_line >= 14 and ink / (bw * bh_line) > 0.285:   # siyoh zichligi yuqori - qalin shrift
                bold = True
                size = _matched_size(ln["text"], bw, True) or size
        info.append((col, size, bold))
    para_size = {}
    for key, group in blocks.items():                 # bir abzatsda bir xil shrift o'lchami (median)
        ss = sorted(info[lines.index(g)][1] for g in group if info[lines.index(g)][1])
        para_size[key] = ss[len(ss) // 2] if ss else None

    # 2) eski matnni fon bilan yopamiz, yangisini yozamiz (rasm/surat ustidagi matnga tegmaymiz)
    skip = [_busy_background(img, ln["box"]) for ln in lines]
    for ln, sk in zip(lines, skip):
        if not sk:
            _fill_box(img, ln["box"])
    draw = ImageDraw.Draw(img)
    for ln, new, (col, own_size, bold), sk in zip(lines, new_texts, info, skip):
        if sk:
            continue
        x0, y0, x1, y1 = ln["box"]
        bw, bh = x1 - x0, y1 - y0
        size = para_size[(ln["block"], ln["par"])] or own_size or bh * 1.07
        font = _pil_font(new, size, bold)
        if font is None:
            continue
        w = draw.textlength(new, font=font)
        if w > bw * 1.02:                              # sig'maydigan bo'lsa, kichraytiramiz
            font = _pil_font(new, max(6, size * bw * 1.02 / w), bold)
            w = draw.textlength(new, font=font)
        x = x0 if align[(ln["block"], ln["par"])] == "left" else x0 + (bw - w) / 2
        asc, desc = font.getmetrics()
        y = y0 + (bh - (asc + desc)) / 2
        draw.text((x, y), new, font=font, fill=col)
    return img

def ocr_read(img):
    """Rasmni o'qiydi. Qaytaradi: dict(lines, conf, is_cyrillic) yoki None (matn topilmasa)."""
    lines, conf = ocr_lines(img)
    if not lines:
        return None
    lat, cyr = count_scripts_text(lines_to_text(lines))
    return {"lines": lines, "conf": conf, "is_cyrillic": cyr > lat}

def handle_image(message, mode=None):
    """Rasm (izohsiz foto yoki rasm fayli): ichidagi matn o'qiladi (OCR), o'giriladi va
    matn rasm ustiga qayta yoziladi. Natija: yangi rasm + o'girilgan matn."""
    chat_id = message.chat.id
    is_doc = message.content_type == 'document'
    if is_doc:
        file_id, fsize = message.document.file_id, message.document.file_size
        base = os.path.splitext(message.document.file_name or "rasm")[0]
    else:
        file_id, fsize, base = message.photo[-1].file_id, message.photo[-1].file_size, "rasm"
    if fsize and fsize > MAX_PDF_MB * 1024 * 1024:
        bot.send_message(chat_id, f"❌ Fayl juda katta (maksimum {MAX_PDF_MB} MB).")
        return

    uid = message.from_user.id
    if uid in _busy_users:
        bot.send_message(chat_id, "⏳ Oldingi faylingiz hali o'girilmoqda. Tugashini kuting.")
        return
    _busy_users.add(uid)
    wait_msg = bot.send_message(chat_id, "⏳ Rasm o'qilmoqda. Iltimos kuting...")
    bot.send_chat_action(chat_id, 'upload_photo')

    def say(text):
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=wait_msg.message_id)
        except Exception:
            bot.send_message(chat_id, text)

    try:
        ensure_ocr_ready()
        data = bot.download_file(bot.get_file(file_id).file_path)
        img = ImageOps.exif_transpose(Image.open(BytesIO(data)))
        img.load()
        info = ocr_read(img)
        if info is None:
            say("❌ Rasmda o'qiladigan matn topilmadi.")
            return
        if mode == "cyr" and info["is_cyrillic"]:
            say("❌ Iltimos, faqat lotincha matn kiriting!")
            return
        if mode == "lat" and not info["is_cyrillic"]:
            say("❌ Iltimos, faqat kirillcha matn kiriting!")
            return
        to_cyr = (mode == "cyr") or (mode is None and not info["is_cyrillic"])
        convert = to_cyrillic if to_cyr else to_latin
        label, suffix = ("Kirill", "_kirill") if to_cyr else ("Lotin", "_lotin")

        lines = info["lines"]
        new_texts = [convert(l["text"]) for l in lines]
        out_img = redraw_image(img, lines, new_texts)
        buf = BytesIO()
        if is_doc:
            out_img.save(buf, "PNG")
            buf.seek(0)
            bot.send_document(chat_id, buf, visible_file_name=f"{base}{suffix}.png")
        else:
            out_img.save(buf, "JPEG", quality=92)
            buf.seek(0)
            bot.send_photo(chat_id, buf)
        result = lines_to_text([dict(l, text=t) for l, t in zip(lines, new_texts)])
        note = ("⚠️ Rasm sifati past, natijada xatolar ko'p bo'lishi mumkin. Tekshirib oling."
                if info["conf"] < 70 else
                "⚠️ Matn rasmdan avtomatik o'qildi, xatolar bo'lishi mumkin. Tekshirib oling.")
        send_text_entities(chat_id, f"📝 Natija ({label}):\n\n{result}\n\n{note}", None)
        bot.delete_message(chat_id, wait_msg.message_id)
    except Exception as e:
        user_errs = (Image.UnidentifiedImageError, Image.DecompressionBombError) if Image is not None else ()
        if user_errs and isinstance(e, user_errs):
            print("Rasm o'qilmadi:", repr(e))
            say("❌ Rasmni o'qib bo'lmadi. Boshqa rasm yuboring.")
        else:
            hint = {"TESSERACT_NOT_FOUND": " | SERVER: Tesseract o'rnatilmagan - apt-get install tesseract-ocr",
                    "OCR_LIBS_NOT_FOUND": " | SERVER: pip install pytesseract pillow"}.get(str(e), "")
            notify_admin("handle_image", e, message, extra=f"rasm, rejim={mode}{hint}")
            say(GENERIC_ERROR_TEXT)
    finally:
        _busy_users.discard(uid)

# --- MATNLAR (Telegram HTML formati) ---
FORMATS_TEXT = "(PDF, TXT, DOCX, XLSX, PPTX, EPUB, FB2)"
NOTE_TEXT = "⚠️ <i>Eslatma: Natija aniq va to\u2018g\u2018ri chiqishi uchun yuborilayotgan matnda imlo xatolari bo\u2018lmasligiga e\u2019tibor bering.</i>"

def welcome_text(first_name):
    name = html.escape(first_name or "")
    return (
        f"👋 <b>Salom, {name}, Lotin-Kirill tarjimon botiga xush kelibsiz!</b>\n\n"
        "Ushbu bot sizga matn shuningdek Pdf, Word, TXT va boshqa ko'plab fayllarni <b>Lotin ⇆ Kirill</b> "
        "alifbolariga tez hamda sifatli tarzda o'girib beradi.\n\n"
        "👇 Boshlash uchun quyidagi bot menyusidan o‘zingizga kerakli alifboni tanlang:"
    )

def prompt_text(kind):
    # kind: "Lotincha" yoki "Kirillcha"
    return f"<b>{kind} matn yoki fayl yuboring:</b> {FORMATS_TEXT}\n\n{NOTE_TEXT}"

# --- TUGMA MATNLARI (faqat shu yerdan o'zgartiring) ---
BTN_TO_CYR = "🔤 Lotin ➔ Крилл"
BTN_TO_LAT = "🔠 Крилл ➔ Lotin"
# Eski klaviaturasi hali yangilanmagan foydalanuvchilar uchun oldingi yozuvlar ham qabul qilinadi
_OLD_TO_CYR = ("🔤 Lotin ➡️ Kirill",)
_OLD_TO_LAT = ("🔠 Kirill ➡️ Lotin",)

def _norm_btn(text):
    """Emoji variatsiya belgilari va ortiqcha bo'shliqlarni e'tiborsiz qoldirib solishtirish uchun."""
    return " ".join((text or "").replace("\ufe0f", "").replace("\u200b", "").split())

def is_btn(text, *labels):
    return _norm_btn(text) in {_norm_btn(l) for l in labels}

# --- KLAVIATURALAR ---
def main_menu(user_id, username=None):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(BTN_TO_CYR, BTN_TO_LAT)
    if user_id == ADMIN_ID or (username and username.lower() == ADMIN_USERNAME.lower()):
        markup.row("📊 Statistika", "📢 Xabar yuborish")
    return markup

def back_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🔙 Orqaga")
    return markup

def no_button_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("▶️ Tugmasiz yuborish")
    markup.row("🔙 Orqaga")
    return markup

# --- HANDLERS ---
@bot.message_handler(commands=['start'])
@safe_handler
def welcome(message):
    add_user(message.from_user.id)
    bot.send_message(message.chat.id, welcome_text(message.from_user.first_name), parse_mode="HTML", reply_markup=main_menu(message.from_user.id, message.from_user.username))

@bot.message_handler(content_types=['text', 'photo', 'video', 'animation', 'document', 'audio', 'voice',
                                    'sticker', 'video_note', 'contact', 'location', 'venue', 'poll', 'dice'])
@safe_handler
def handle_msg(message):
    user_id = message.from_user.id
    user_name = message.from_user.username
    is_admin = (user_id == ADMIN_ID or (user_name and user_name.lower() == ADMIN_USERNAME.lower()))

    text = message.text if message.text else ""

    if is_btn(text, BTN_TO_CYR, *_OLD_TO_CYR):
        msg = bot.send_message(message.chat.id, prompt_text("Lotincha"), parse_mode="HTML", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_to_cyrillic)
    elif is_btn(text, BTN_TO_LAT, *_OLD_TO_LAT):
        msg = bot.send_message(message.chat.id, prompt_text("Kirillcha"), parse_mode="HTML", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_to_latin)
    elif text == "📊 Statistika" and is_admin:
        with sqlite3.connect('bot_users.db') as conn: count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        bot.send_message(message.chat.id, f"👥 Foydalanuvchilar: {count} ta", reply_markup=main_menu(user_id, user_name))
    elif text == "📢 Xabar yuborish" and is_admin:
        msg = bot.send_message(message.chat.id, "📢 Tarqatmoqchi bo'lgan xabaringizni yuboring (Matn, Rasm, Video yoki istalgan fayl):", reply_markup=back_menu())
        bot.register_next_step_handler(msg, step1_broadcast)
    elif message.content_type == 'document':
        handle_document(message, None)   # avtomatik aniqlash
    elif message.content_type in MEDIA_TYPES:
        handle_media(message, None)      # izohli rasm/video: avtomatik aniqlash
    else:
        if text:
            bot.send_message(message.chat.id, "⚠️ Iltimos, avval quyidagi tugmalardan birini tanlang! 👇", reply_markup=main_menu(user_id, user_name))
        else:
            bot.send_message(message.chat.id, UNSUPPORTED_MSG, reply_markup=main_menu(user_id, user_name))

def switch_mode(message, text):
    """Rejim ichida turib boshqa yo'nalish tugmasi bosilsa, rejimni almashtiradi."""
    if is_btn(text, BTN_TO_CYR, *_OLD_TO_CYR):
        msg = bot.send_message(message.chat.id, prompt_text("Lotincha"), parse_mode="HTML", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_to_cyrillic)
    else:
        msg = bot.send_message(message.chat.id, prompt_text("Kirillcha"), parse_mode="HTML", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_to_latin)

# --- LOTIN → KIRILL ---
@safe_handler
def process_to_cyrillic(message):
    user_id = message.from_user.id
    user_name = message.from_user.username
    text = message.text
    if message.content_type == 'document':
        handle_document(message, 'cyr')
        bot.register_next_step_handler(message, process_to_cyrillic)
        return
    if message.content_type in MEDIA_TYPES:
        handle_media(message, 'cyr')
        bot.register_next_step_handler(message, process_to_cyrillic)
        return
    if not text:
        msg = bot.send_message(message.chat.id, UNSUPPORTED_MSG, reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_to_cyrillic)
        return

    if is_btn(text, BTN_TO_CYR, *_OLD_TO_CYR, BTN_TO_LAT, *_OLD_TO_LAT):
        switch_mode(message, text)
        return

    if text in ["🔙 Orqaga", "/start"]:
        bot.send_message(message.chat.id, "Bosh menyuga qaytdingiz.", reply_markup=main_menu(user_id, user_name))
        return

    has_latin = bool(re.search(r'[a-zA-Z]', text))
    has_cyrillic = bool(re.search(r'[а-яА-ЯёЁўқғҳЎҚҒҲ]', text))

    if has_cyrillic and not has_latin:
        msg = bot.send_message(message.chat.id, "❌ Iltimos, faqat lotincha matn kiriting!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_to_cyrillic)
        return

    bot.send_chat_action(message.chat.id, 'typing')
    wait_msg = bot.send_message(message.chat.id, "⏳ *Matn o'girilmoqda. Iltimos kuting* •••", parse_mode="Markdown")
    time.sleep(0.6)

    send_result_text(message.chat.id, wait_msg.message_id, "📝 Natija (Kirill):\n\n", text, message.entities, to_cyrillic)
    bot.register_next_step_handler(message, process_to_cyrillic)

# --- KIRILL → LOTIN ---
@safe_handler
def process_to_latin(message):
    user_id = message.from_user.id
    user_name = message.from_user.username
    text = message.text
    if message.content_type == 'document':
        handle_document(message, 'lat')
        bot.register_next_step_handler(message, process_to_latin)
        return
    if message.content_type in MEDIA_TYPES:
        handle_media(message, 'lat')
        bot.register_next_step_handler(message, process_to_latin)
        return
    if not text:
        msg = bot.send_message(message.chat.id, UNSUPPORTED_MSG, reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_to_latin)
        return

    if is_btn(text, BTN_TO_CYR, *_OLD_TO_CYR, BTN_TO_LAT, *_OLD_TO_LAT):
        switch_mode(message, text)
        return

    if text in ["🔙 Orqaga", "/start"]:
        bot.send_message(message.chat.id, "🏠 Bosh menyudasiz.", reply_markup=main_menu(user_id, user_name))
        return

    has_latin = bool(re.search(r'[a-zA-Z]', text))
    has_cyrillic = bool(re.search(r'[а-яА-ЯёЁўқғҳЎҚҒҲ]', text))

    if has_latin and not has_cyrillic:
        msg = bot.send_message(message.chat.id, "❌ Iltimos, faqat kirillcha matn kiriting!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_to_latin)
        return

    bot.send_chat_action(message.chat.id, 'typing')
    wait_msg = bot.send_message(message.chat.id, "⏳ *Matn o'girilmoqda. Iltimos kuting* •••", parse_mode="Markdown")
    time.sleep(0.6)

    send_result_text(message.chat.id, wait_msg.message_id, "📝 Natija (Lotin):\n\n", text, message.entities, to_latin)
    bot.register_next_step_handler(message, process_to_latin)

# --- REKLAMA TARQATISH ---
@safe_handler
def step1_broadcast(message):
    user_id = message.from_user.id
    user_name = message.from_user.username

    if message.text in ["🔙 Orqaga", "/start"]:
        bot.send_message(message.chat.id, "❌ Xabar yuborish bekor qilindi.", reply_markup=main_menu(user_id, user_name))
        return

    admin_broadcast_data[user_id] = message

    text = (
        "Zo'r! Endi bu xabarga tugma qo'shamizmi?\n\n"
        "🔗 *Katta (1 qatorli) tugmalar uchun:*\n"
        "`1-Kanal - https://t.me/kanal1`\n"
        "`2-Kanal - https://t.me/kanal2`\n\n"
        "🔗 *Yonma-yon bo'lish uchun o'rtasiga | qoyasiz:*\n"
        "`1 Kanal - t.me/k1 | 2 Kanal - t.me/k2`\n\n"
        "➖ Agar tugma kerak bo'lmasa, pastdagi «▶️ Tugmasiz yuborish» tugmasini bosing."
    )
    msg = bot.send_message(message.chat.id, text, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=no_button_menu())
    bot.register_next_step_handler(msg, step2_broadcast)

@safe_handler
def step2_broadcast(message):
    user_id = message.from_user.id
    user_name = message.from_user.username

    if message.text in ["🔙 Orqaga", "/start"]:
        bot.send_message(message.chat.id, "❌ Xabar yuborish bekor qilindi.", reply_markup=main_menu(user_id, user_name))
        return

    broadcast_msg = admin_broadcast_data.get(user_id)
    if not broadcast_msg:
        bot.send_message(message.chat.id, "Xatolik yuz berdi. Iltimos boshqatdan urinib ko'ring.", reply_markup=main_menu(user_id, user_name))
        return

    inline_markup = None

    if message.text != "▶️ Tugmasiz yuborish":
        inline_markup = types.InlineKeyboardMarkup()
        lines = message.text.strip().split('\n')

        try:
            for line in lines:
                line = line.strip()
                if not line:
                    continue

                row_buttons = []
                buttons_in_row = line.split('|')

                for btn_str in buttons_in_row:
                    btn_str = btn_str.strip()
                    if not btn_str:
                        continue

                    match = re.search(r'\s*-\s*(https?://|t\.me/|www\.|@)', btn_str)

                    if match:
                        idx = match.start()
                        btn_text = btn_str[:idx].strip()
                        btn_url = btn_str[idx:].strip()
                        if btn_url.startswith('-'):
                            btn_url = btn_url[1:].strip()
                    elif '-' in btn_str:
                        btn_text, btn_url = btn_str.rsplit('-', 1)
                        btn_text = btn_text.strip()
                        btn_url = btn_url.strip()
                    else:
                        raise ValueError("Format xato")

                    if btn_url.startswith('@'):
                        btn_url = 'https://t.me/' + btn_url[1:]
                    elif not btn_url.startswith('http'):
                        btn_url = 'https://' + btn_url

                    row_buttons.append(types.InlineKeyboardButton(text=btn_text, url=btn_url))

                if row_buttons:
                    inline_markup.row(*row_buttons)

        except Exception:
            error_text = (
                "❌ Xato format!\nIltimos, har bir tugma `Nomi - Ssilkasi` shaklida bo'lishiga ishonch hosil qiling.\n\n"
                "To'g'ri misol:\n"
                "`Asosiy kanal - https://t.me/kanal`\n"
                "`Kanal 1 - t.me/k1 | Kanal 2 - t.me/k2`\n\n"
                "Boshqatdan yozing yoki «▶️ Tugmasiz yuborish» ni bosing."
            )
            msg = bot.send_message(message.chat.id, error_text, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=no_button_menu())
            bot.register_next_step_handler(msg, step2_broadcast)
            return

    wait_msg = bot.send_message(message.chat.id, "⏳ *Xabar tarqatilmoqda. Iltimos kuting* •••", parse_mode="Markdown")

    with sqlite3.connect('bot_users.db') as conn:
        users = conn.execute('SELECT user_id FROM users').fetchall()

    sent = 0
    failed = 0
    for u in users:
        try:
            bot.copy_message(
                chat_id=u[0],
                from_chat_id=broadcast_msg.chat.id,
                message_id=broadcast_msg.message_id,
                reply_markup=inline_markup
            )
            sent += 1
            time.sleep(0.05)
        except Exception:
            failed += 1
            pass

    natija_matni = (
        f"✅ Xabar {sent} ta foydalanuvchiga muvaffaqiyatli yuborildi!\n"
        f"❌ {failed} ta odamga bormadi (Botni o'chirib yuborgan bo'lishi mumkin)."
    )
    bot.edit_message_text(natija_matni, chat_id=message.chat.id, message_id=wait_msg.message_id)
    bot.send_message(message.chat.id, "Bosh menyudasiz:", reply_markup=main_menu(user_id, user_name))


def startup_report():
    """Ishga tushganda nimalar ishlayotganini tekshiradi va adminga yuboradi."""
    lines = ["✅ <b>Bot ishga tushdi</b>"]

    # boshqa nusxa bormi?
    try:
        bot.get_updates(offset=-1, limit=1, timeout=0)
    except Exception as e:
        if getattr(e, "error_code", None) == 409:
            lines.append("❌ <b>BOSHQA NUSXA ISHLAYAPTI (409)</b> - yuqoridagi xabarga qarang")
            admin_say(CONFLICT_TEXT, key="409", cooldown=1800)

    # PDF uchun shrift
    try:
        lines.append("✅ PDF: shrift topildi" if fonts_available() else
                     "❌ PDF: kirill shrifti topilmadi - DejaVuSans.ttf ni main.py yoniga qo'ying")
    except Exception as e:
        lines.append(f"❌ PDF: {html.escape(repr(e))}")

    # DOCX, XLSX, PPTX, EPUB, FB2
    lines.append("✅ DOCX/XLSX/PPTX/EPUB/FB2: lxml bor" if etree is not None else
                 "❌ DOCX/XLSX/PPTX/EPUB/FB2: lxml yo'q - pip install lxml")

    # rasm (OCR)
    try:
        ensure_ocr_ready()
        lines.append("✅ Rasm (OCR): Tesseract va o'zbek tili tayyor")
    except RuntimeError as e:
        why = {"OCR_LIBS_NOT_FOUND": "pytesseract/pillow yo'q - pip install pytesseract pillow",
               "TESSERACT_NOT_FOUND": "Tesseract dasturi yo'q - apt-get install -y tesseract-ocr"}.get(str(e), str(e))
        lines.append(f"❌ Rasm (OCR): {html.escape(why)}")
    except Exception as e:
        lines.append(f"❌ Rasm (OCR): til fayllarini yuklab bo'lmadi ({html.escape(repr(e))})")

    admin_say("\n".join(lines))


if __name__ == "__main__":
    init_db()
    bot.remove_webhook()
    print("Bot muvaffaqiyatli ishga tushdi...")
    try:
        startup_report()
    except Exception as e:
        print("Hisobot yuborilmadi:", repr(e))
    bot.infinity_polling(skip_pending=True)
