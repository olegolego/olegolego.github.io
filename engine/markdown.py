"""Small Markdown -> HTML converter (standard library only).

Supports: headings, paragraphs, **bold**, *italic*, ~~strike~~, ==highlight==,
`code`, fenced code blocks, links, images (a "title" becomes a caption),
nested lists, task lists, blockquotes, tables, horizontal rules, raw HTML
and, when enabled, $inline$ / $$display$$ math (rendered by KaTeX).
"""
import html
import re

FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*([\w+#.-]*)")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
HR = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
HTML_BLOCK = re.compile(r"^\s{0,3}<(/?[a-zA-Z][\w-]*[\s/>]|/?[a-zA-Z][\w-]*$|!--)")
TASK = re.compile(r"^\[([ xX])\]\s+")


def render(text, math=False):
    lines = text.replace("\r\n", "\n").replace("\t", "    ").split("\n")
    return _blocks(lines, math)


def slugify_heading(text):
    text = re.sub(r"<[^>]+>", "", text).lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.U)
    return re.sub(r"[\s_-]+", "-", text).strip("-") or "section"


# ---------------------------------------------------------------- blocks

def _starts_block(line, math):
    return bool(
        FENCE.match(line) or HEADING.match(line) or HR.match(line)
        or QUOTE.match(line) or LIST_ITEM.match(line)
        or (math and line.strip().startswith("$$"))
    )


def _blocks(lines, math):
    out = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        m = FENCE.match(line)
        if m:
            fence, lang = m.group(1), m.group(2)
            body = []
            i += 1
            while i < n and not lines[i].strip().startswith(fence):
                body.append(lines[i])
                i += 1
            i += 1
            cls = ' class="language-%s"' % html.escape(lang) if lang else ""
            out.append("<pre><code%s>%s</code></pre>" % (cls, html.escape("\n".join(body))))
            continue

        if math and line.strip().startswith("$$"):
            body = [line]
            if not (line.strip().endswith("$$") and len(line.strip()) > 2):
                i += 1
                while i < n and "$$" not in lines[i]:
                    body.append(lines[i])
                    i += 1
                if i < n:
                    body.append(lines[i])
            i += 1
            out.append('<div class="math">%s</div>' % html.escape("\n".join(body)))
            continue

        m = HEADING.match(line)
        if m:
            level = len(m.group(1))
            inner = inline(m.group(2), math)
            out.append('<h%d id="%s">%s</h%d>' % (level, slugify_heading(inner), inner, level))
            i += 1
            continue

        if HR.match(line):
            out.append("<hr>")
            i += 1
            continue

        if QUOTE.match(line):
            body = []
            while i < n and lines[i].strip():
                q = QUOTE.match(lines[i])
                body.append(q.group(1) if q else lines[i])
                i += 1
            out.append("<blockquote>\n%s\n</blockquote>" % _blocks(body, math))
            continue

        if LIST_ITEM.match(line):
            i, block = _list(lines, i, math)
            out.append(block)
            continue

        if "|" in line and i + 1 < n and TABLE_SEP.match(lines[i + 1]) and "-" in lines[i + 1]:
            i, block = _table(lines, i, math)
            out.append(block)
            continue

        if HTML_BLOCK.match(line):
            body = []
            while i < n and lines[i].strip():
                body.append(lines[i])
                i += 1
            out.append("\n".join(body))
            continue

        # paragraph
        body = [line]
        i += 1
        while i < n and lines[i].strip() and not _starts_block(lines[i], math):
            body.append(lines[i])
            i += 1
        out.append(_paragraph(body, math))

    return "\n".join(out)


def _paragraph(lines, math):
    parts = []
    for k, line in enumerate(lines):
        last = k == len(lines) - 1
        if not last and (line.endswith("  ") or line.endswith("\\")):
            parts.append(inline(line.rstrip(" \\"), math) + "<br>")
        else:
            parts.append(inline(line.strip(), math))
    text = "\n".join(parts)

    # A paragraph that is just one captioned image becomes a figure.
    fig = re.match(r'^\s*!\[([^\]]*)\]\(\s*(\S+?)\s+"([^"]+)"\s*\)\s*$', "\n".join(lines))
    if fig:
        alt, src, cap = fig.groups()
        return '<figure><img src="%s" alt="%s" loading="lazy"><figcaption>%s</figcaption></figure>' % (
            html.escape(src), html.escape(alt), inline(cap, math))
    return "<p>%s</p>" % text


def _indent(line):
    return len(line) - len(line.lstrip(" "))


def _list(lines, i, math):
    first = LIST_ITEM.match(lines[i])
    base = len(first.group(1))
    ordered = first.group(2)[0].isdigit()
    start = int(first.group(2)[:-1]) if ordered else 1
    items = []
    n = len(lines)

    while i < n:
        m = LIST_ITEM.match(lines[i])
        if not m or len(m.group(1)) != base or m.group(2)[0].isdigit() != ordered:
            break
        offset = m.start(3)
        body = [m.group(3)]
        loose = False
        i += 1
        while i < n:
            line = lines[i]
            if not line.strip():
                # blank line: item continues only if the next text is indented
                j = i
                while j < n and not lines[j].strip():
                    j += 1
                if j < n and _indent(lines[j]) > base:
                    if not LIST_ITEM.match(lines[j]) or _indent(lines[j]) >= offset:
                        loose = True
                    body.extend([""] * (j - i))
                    i = j
                    continue
                break
            ind = _indent(line)
            if ind > base:
                body.append(line[min(ind, offset):])
            elif LIST_ITEM.match(line) or _starts_block(line, math):
                break
            elif body and body[-1].strip():
                body.append(line.strip())  # lazy continuation
            else:
                break
            i += 1

        cls = ""
        task = TASK.match(body[0])
        if task:
            checked = " checked" if task.group(1).lower() == "x" else ""
            body[0] = body[0][task.end():]
            cls = ' class="task"'
        inner = _blocks(body, math)
        if not loose and inner.startswith("<p>"):
            end = inner.find("</p>")
            inner = inner[3:end] + inner[end + 4:]
        if task:
            inner = '<input type="checkbox" disabled%s> %s' % (checked, inner)
        items.append("<li%s>%s</li>" % (cls, inner))

        if i < n and not lines[i].strip():
            break

    tag = "ol" if ordered else "ul"
    attr = ' start="%d"' % start if ordered and start != 1 else ""
    return i, "<%s%s>\n%s\n</%s>" % (tag, attr, "\n".join(items), tag)


def _cells(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def _table(lines, i, math):
    head = _cells(lines[i])
    aligns = []
    for c in _cells(lines[i + 1]):
        if c.startswith(":") and c.endswith(":"):
            aligns.append("center")
        elif c.endswith(":"):
            aligns.append("right")
        elif c.startswith(":"):
            aligns.append("left")
        else:
            aligns.append("")
    i += 2
    rows = []
    while i < len(lines) and lines[i].strip() and "|" in lines[i]:
        rows.append(_cells(lines[i]))
        i += 1

    def cell(tag, text, k):
        a = aligns[k] if k < len(aligns) else ""
        style = ' style="text-align:%s"' % a if a else ""
        return "<%s%s>%s</%s>" % (tag, style, inline(text, math), tag)

    out = ["<table>", "<thead><tr>%s</tr></thead>" % "".join(cell("th", c, k) for k, c in enumerate(head)), "<tbody>"]
    for r in rows:
        r = (r + [""] * len(head))[:len(head)]
        out.append("<tr>%s</tr>" % "".join(cell("td", c, k) for k, c in enumerate(r)))
    out.append("</tbody></table>")
    return i, "\n".join(out)


# ---------------------------------------------------------------- inline

def inline(text, math=False):
    slots = []

    def keep(s):
        slots.append(s)
        return "\x00%d\x00" % (len(slots) - 1)

    text = re.sub(r"(`+)(.+?)\1", lambda m: keep("<code>%s</code>" % html.escape(m.group(2).strip())), text)
    if math:
        text = re.sub(r"\$\$(.+?)\$\$", lambda m: keep(html.escape(m.group(0))), text)
        text = re.sub(r"(?<![\\$\w])\$(?=\S)([^$\n]+?)(?<=\S)\$(?![\w$])", lambda m: keep(html.escape(m.group(0))), text)
    # an escaped \$ gets its own element so KaTeX never pairs it up as math
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|~=$<>])",
                  lambda m: keep("<span>$</span>" if m.group(1) == "$" and math else html.escape(m.group(1))), text)
    text = re.sub(r"<(https?://[^>\s]+)>", lambda m: keep(_a(m.group(1), html.escape(m.group(1)))), text)
    text = re.sub(r"<!--.*?-->|</?[a-zA-Z][\w-]*(\s[^<>]*)?/?>", lambda m: keep(m.group(0)), text)

    def image(m):
        alt, src, title = m.group(1), m.group(2), m.group(3)
        t = ' title="%s"' % html.escape(title) if title else ""
        return keep('<img src="%s" alt="%s"%s loading="lazy">' % (html.escape(src), html.escape(alt), t))

    def link(m):
        label, href, title = m.group(1), m.group(2), m.group(3)
        return keep(_a(href, _format(label), title))

    text = re.sub(r'!\[([^\]]*)\]\(\s*<?([^\s>]+)>?(?:\s+"([^"]*)")?\s*\)', image, text)
    text = re.sub(r'\[([^\]]+)\]\(\s*<?([^\s>]+)>?(?:\s+"([^"]*)")?\s*\)', link, text)
    text = re.sub(r"(?<![\w\"'=/])(https?://[^\s<\x00]+[^\s<\x00.,;:!?)\]'\"])",
                  lambda m: keep(_a(m.group(1), html.escape(m.group(1)))), text)

    text = _format(text)
    for _ in range(10):
        if "\x00" not in text:
            break
        text = re.sub(r"\x00(\d+)\x00", lambda m: slots[int(m.group(1))], text)
    return text


def _a(href, label, title=None):
    t = ' title="%s"' % html.escape(title) if title else ""
    return '<a href="%s"%s>%s</a>' % (html.escape(href), t, label)


def _format(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)", r"<strong>\1</strong>", s)
    s = re.sub(r"\*(?=\S)(.+?)(?<=\S)\*", r"<em>\1</em>", s)
    s = re.sub(r"(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)", r"<em>\1</em>", s)
    s = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<del>\1</del>", s)
    s = re.sub(r"==(?=\S)(.+?)(?<=\S)==", r"<mark>\1</mark>", s)
    return s
