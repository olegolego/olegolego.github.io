"""Builds the site from posts/, pages/, files/ and theme/ (standard library only).

    build(dev=False)  ->  docs/      the public site (drafts and empty slots hidden)
    build(dev=True)   ->  .preview/  local preview (drafts, empty slots, live reload)
"""
import datetime as dt
import html
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

from . import markdown

ROOT = Path(__file__).resolve().parent.parent
POSTS = ROOT / "posts"
PAGES = ROOT / "pages"
FILES = ROOT / "files"
THEME = ROOT / "theme"
OUT = ROOT / "docs"
PREVIEW = ROOT / ".preview"

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

KATEX = """
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.css">
<script defer src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.js"></script>
<script defer src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/contrib/auto-render.min.js"
  onload="renderMathInElement(document.querySelector('main'),{delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false}],throwOnError:false})"></script>"""

LIVE_RELOAD = """<script>(function(){var v=null;setInterval(function(){fetch('/__reload').then(function(r){return r.text()}).then(function(t){if(v===null)v=t;else if(t!==v)location.reload()}).catch(function(){})},700)})();</script>"""


# ---------------------------------------------------------------- sources

def load_config():
    cfg = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    cfg.setdefault("title", "")
    cfg.setdefault("author", cfg["title"])
    cfg.setdefault("tagline", "")
    cfg.setdefault("description", "")
    cfg.setdefault("url", "")
    cfg.setdefault("domain", "")
    cfg.setdefault("language", "en")
    cfg.setdefault("notebook_title", "Notebook")
    cfg.setdefault("home_entries", 10)
    cfg.setdefault("links", [])
    cfg["url"] = cfg["url"].rstrip("/")
    return cfg


def read_source(path):
    """Returns (front matter dict, markdown body). HTML comments are private notes and are dropped."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    meta = {}
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            for line in text[4:end].split("\n"):
                if ":" in line and not line.lstrip().startswith("#"):
                    key, value = line.split(":", 1)
                    meta[key.strip().lower()] = parse_value(value.strip())
            text = text[end + 4:].lstrip("-").lstrip("\n")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return meta, text


def parse_value(v):
    if v.lower() in ("true", "yes"):
        return True
    if v.lower() in ("false", "no"):
        return False
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    if v.startswith("[") and v.endswith("]"):
        return [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
    return v


def as_list(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v:
        return [x.strip() for x in v.split(",") if x.strip()]
    return []


def parse_date(value, fallback):
    if isinstance(value, str) and value:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                return dt.datetime.strptime(value.strip(), fmt)
            except ValueError:
                pass
    return fallback


def long_date(d):
    return "%d %s %d" % (d.day, MONTHS[d.month - 1], d.year)


def plain_summary(body_html, limit=180):
    m = re.search(r"<p>(.*?)</p>", body_html, flags=re.S)
    if not m:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def tag_slug(tag):
    return re.sub(r"[^\w-]+", "-", tag.lower(), flags=re.U).strip("-")


def load_posts(include_drafts):
    posts = []
    for path in sorted(POSTS.glob("*.md")):
        if path.name.startswith("_"):
            continue
        meta, body = read_source(path)
        draft = bool(meta.get("draft", False))
        if draft and not include_drafts:
            continue
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", path.stem)
        fallback = dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else \
            dt.datetime.fromtimestamp(path.stat().st_mtime)
        date = parse_date(meta.get("date"), fallback)
        math = bool(meta.get("math", False))
        body_html = markdown.render(body, math)
        posts.append({
            "title": meta.get("title") or long_date(date),
            "date": date,
            "tags": as_list(meta.get("tags")),
            "draft": draft,
            "math": math,
            "html": body_html,
            "summary": meta.get("summary") or plain_summary(body_html),
            "url": "/notebook/%s/" % path.stem,
            "slug": path.stem,
        })
    posts.sort(key=lambda p: (p["date"], p["slug"]), reverse=True)
    return posts


def load_pages():
    pages = []
    for path in sorted(PAGES.glob("*.md")):
        if path.name.startswith("_"):
            continue
        meta, body = read_source(path)
        attached = meta.get("file") or ""
        has_file = bool(attached) and (FILES / attached).is_file()
        nav = meta.get("nav", 50)
        pages.append({
            "slug": path.stem,
            "title": meta.get("title") or path.stem.replace("-", " ").title(),
            "nav": None if nav is False else int(nav) if str(nav).isdigit() else 50,
            "math": bool(meta.get("math", False)),
            "html": markdown.render(body, bool(meta.get("math", False))),
            "file": attached,
            "has_file": has_file,
            "icon": meta.get("icon") or ("pdf" if attached.lower().endswith(".pdf") else "doc"),
            "empty": not body.strip() and not has_file,
            "source": path.relative_to(ROOT).as_posix(),
            "url": "/" if path.stem == "home" else "/%s/" % path.stem,
        })
    return pages


# ---------------------------------------------------------------- rendering

# 32x32 pixel-style icons; drawn at 32px on the desktop and 16px in lists and menus
ICONS = {
    "computer": '<rect x="4.5" y="3.5" width="23" height="17" fill="#c0c0c0" stroke="#000"/>'
                '<rect x="7.5" y="6.5" width="17" height="11" fill="#008080" stroke="#404040"/>'
                '<path d="M9 9h7" stroke="#fff"/><rect x="11.5" y="20.5" width="9" height="3" fill="#a0a0a0" stroke="#000"/>'
                '<rect x="3.5" y="23.5" width="25" height="5" fill="#c0c0c0" stroke="#000"/><path d="M21 26h5" stroke="#00a000"/>',
    "notebook": '<rect x="7.5" y="3.5" width="20" height="25" fill="#2457d6" stroke="#000"/>'
                '<rect x="12.5" y="8.5" width="11" height="6" fill="#fff" stroke="#000"/>'
                '<path d="M4 7h6M4 11h6M4 15h6M4 19h6M4 23h6" stroke="#808080" stroke-width="2"/>',
    "folder": '<path d="M2.5 7.5h10l3 3h14v18h-27z" fill="#ffd84a" stroke="#000"/><path d="M3 12.5h26" stroke="#b08a00"/>',
    "doc": '<path d="M6.5 2.5h14l6 6v21h-20z" fill="#fff" stroke="#000"/><path d="M20.5 2.5v6h6" fill="#c0c0c0" stroke="#000"/>'
           '<path d="M9 12h14M9 15h14M9 18h14M9 21h10M9 24h12" stroke="#000080"/>',
    "pdf": '<path d="M6.5 2.5h14l6 6v21h-20z" fill="#fff" stroke="#000"/><path d="M20.5 2.5v6h6" fill="#c0c0c0" stroke="#000"/>'
           '<path d="M9 12h14M9 15h14M9 18h10" stroke="#808080"/><rect x="8" y="21" width="16" height="6" fill="#d40000"/>',
    "mail": '<rect x="3.5" y="8.5" width="25" height="16" fill="#fff" stroke="#000"/><path d="M4 9l12 9 12-9" fill="none" stroke="#000"/>',
    "link": '<circle cx="16" cy="16" r="12" fill="#3a8ee6" stroke="#000"/>'
            '<path d="M8 11c4 1 5 4 3 7s1 6 4 6M20 6c-2 4 2 5 5 6" fill="#3ca63c" stroke="#1e6e1e"/>',
    "rss": '<rect x="4.5" y="4.5" width="23" height="23" fill="#f78422" stroke="#000"/><circle cx="10" cy="22" r="2.5" fill="#fff"/>'
           '<path d="M8 15a9 9 0 0 1 9 9M8 9a15 15 0 0 1 15 15" fill="none" stroke="#fff" stroke-width="3"/>',
    "error": '<circle cx="16" cy="16" r="13" fill="#d40000" stroke="#000"/><path d="M11 11l10 10M21 11l-10 10" stroke="#fff" stroke-width="3"/>',
}


def icon(name, size=16):
    return ('<svg class="icon" width="%d" height="%d" viewBox="0 0 32 32" shape-rendering="crispEdges" '
            'aria-hidden="true">%s</svg>' % (size, size, ICONS.get(name, ICONS["doc"])))


def window(title, icon_name, body, status=(), address=None, cls="", close="/"):
    addr = ""
    if address is not None:
        path = "C:\\" + "\\".join(part for part in address.strip("/").split("/") if part)
        addr = '<div class="addressbar"><span>Address</span><div class="field">%s</div></div>' % html.escape(path)
    bar = ""
    if status:
        bar = '<div class="statusbar">%s</div>' % "".join("<span>%s</span>" % s for s in status)
    return """<section class="window {cls}">
  <div class="titlebar">
    {icon}<span class="title">{title}</span>
    <span class="controls"><span class="ctl" aria-hidden="true">_</span><span class="ctl" aria-hidden="true">□</span><a class="ctl close" href="{close}" aria-label="Close">✕</a></span>
  </div>
  {addr}
  <div class="window-body">
{body}
  </div>
  {bar}
</section>""".format(cls=cls, icon=icon(icon_name), title=html.escape(title), close=close, addr=addr, body=body, bar=bar)


class Site:
    def __init__(self, dev):
        self.dev = dev
        self.out = PREVIEW if dev else OUT
        self.cfg = load_config()
        self.layout = (THEME / "layout.html").read_text(encoding="utf-8")
        self.posts = load_posts(include_drafts=dev)
        pages = load_pages()
        self.home = next((p for p in pages if p["slug"] == "home"), None)
        self.pages = [p for p in pages if p["slug"] != "home" and (dev or not p["empty"])]
        self.today = dt.date.today()

    # -- helpers

    def places(self):
        """(key, url, label, icon) for the desktop and the Start menu."""
        items = [("home", "/", "Home", "computer"), ("notebook", "/notebook/", self.cfg["notebook_title"], "notebook")]
        for p in sorted((p for p in self.pages if p["nav"] is not None), key=lambda p: (p["nav"], p["title"])):
            items.append((p["slug"], p["url"], p["title"], p["icon"]))
        return items

    def links(self):
        out = []
        for link in self.cfg["links"]:
            if link.get("url"):
                out.append((link["url"], link.get("label", link["url"]), "mail" if link["url"].startswith("mailto:") else "link"))
        return out

    def desktop_icons(self, active):
        out = []
        for key, url, label, ico in self.places():
            cls = " selected" if key == active else ""
            cur = ' aria-current="page"' if key == active else ""
            out.append('<a class="desk-icon%s" href="%s"%s>%s<span>%s</span></a>' % (cls, url, cur, icon(ico, 32), html.escape(label)))
        for url, label, ico in self.links():
            out.append('<a class="desk-icon" href="%s">%s<span>%s</span></a>' % (html.escape(url), icon(ico, 32), html.escape(label)))
        return "\n    ".join(out)

    def start_menu(self):
        items = ['<li><a href="%s">%s%s</a></li>' % (url, icon(ico, 24), html.escape(label)) for _, url, label, ico in self.places()]
        extra = ['<li><a href="%s">%s%s</a></li>' % (html.escape(url), icon(ico, 24), html.escape(label)) for url, label, ico in self.links()]
        if self.cfg["url"] and not self.dev:
            extra.append('<li><a href="/feed.xml">%sRSS feed</a></li>' % icon("rss", 24))
        if extra:
            items.append('<li class="sep" role="separator"></li>')
            items.extend(extra)
        return "\n      ".join(items)

    def write(self, url, title, content, active="", task_icon="doc", math=False, description=""):
        rel = url.strip("/")
        target = self.out / rel / "index.html" if rel and not rel.endswith(".html") else self.out / (rel or "index.html")
        depth = len(Path(rel).parts) if rel and not rel.endswith(".html") else max(len(Path(rel).parts) - 1, 0)
        head = KATEX if math else ""
        canonical = self.cfg["url"] + url if self.cfg["url"] else ""
        if canonical:
            head += '\n<link rel="canonical" href="%s">' % html.escape(canonical)
            head += '\n<link rel="alternate" type="application/atom+xml" title="%s" href="/feed.xml">' % html.escape(self.cfg["title"])
        site_title = self.cfg["title"]
        values = {
            "lang": self.cfg["language"],
            "page_title": html.escape("%s · %s" % (title, site_title) if title and title != site_title else site_title),
            "description": html.escape(description or self.cfg["description"]),
            "site_title": html.escape(site_title),
            "desktop_icons": self.desktop_icons(active),
            "content": content,
            "start_menu": self.start_menu(),
            "start_icon": icon("notebook", 20),
            "task": '<a class="btn taskbtn pressed" href="%s">%s<span>%s</span></a>' % (url, icon(task_icon), html.escape(title or site_title)),
            "updated": self.today.isoformat(),
            "head_extra": head,
            "body_extra": LIVE_RELOAD if self.dev else "",
        }
        page = re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: values.get(m.group(1), ""), self.layout)
        if url == "/404.html" and self.cfg["url"]:
            # served for any missing path, so its links must be absolute
            base = urlparse(self.cfg["url"]).path.rstrip("/")
            page = re.sub(r'(href|src|data)="/(?!/)', lambda m: '%s="%s/' % (m.group(1), base), page)
        else:
            page = relativize(page, depth)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page, encoding="utf-8")

    def entry_table(self, posts, summaries=False, by_year=False):
        if not posts:
            return '<div class="pane list"><p class="empty">No entries yet.</p></div>'
        rows = []
        year = None
        for p in posts:
            if by_year and p["date"].year != year:
                year = p["date"].year
                rows.append('<tr class="group"><td colspan="3">%s %d</td></tr>' % (icon("folder"), year))
            draft = ' <span class="draft-tag">[draft]</span>' if p["draft"] else ""
            summary = '<span class="summary">%s</span>' % html.escape(p["summary"]) if summaries and p["summary"] else ""
            tags = " ".join("#" + html.escape(t) for t in p["tags"])
            rows.append('<tr><td><a href="%s">%s<span>%s</span></a>%s%s</td><td><time datetime="%s">%s</time></td><td class="col-tags">%s</td></tr>' % (
                p["url"], icon("doc"), html.escape(p["title"]), draft, summary,
                p["date"].date().isoformat(), p["date"].strftime("%Y-%m-%d"), tags))
        return ('<div class="pane list"><table class="details">\n<thead><tr><th>Name</th><th>Date</th><th class="col-tags">Tags</th></tr></thead>\n'
                '<tbody>\n%s\n</tbody></table></div>' % "\n".join(rows))

    def count(self, n, one, many):
        return "%d %s" % (n, one if n == 1 else many)

    # -- pages

    def build_home(self):
        parts = ['<h1 class="sr-only">%s</h1>' % html.escape(self.cfg["title"])]
        if self.home and not self.home["empty"]:
            parts.append('<div class="pane doc prose">%s</div>' % self.home["html"])
        elif self.dev:
            parts.append(empty_slot("pages/home.md", "Intro text for the front page."))
        latest = self.posts[: int(self.cfg["home_entries"])]
        parts.append('<fieldset class="group"><legend>Recent entries</legend>\n%s' % self.entry_table(latest, summaries=True))
        if len(self.posts) > len(latest):
            parts.append('<p class="more"><a class="btn" href="/notebook/">All %d entries…</a></p>' % len(self.posts))
        parts.append("</fieldset>")
        content = window(self.cfg["title"], "computer", "\n".join(parts), address="/",
                         status=[self.count(len(self.posts), "entry", "entries"), "updated %s" % self.today.isoformat()])
        self.write("/", "", content, active="home", task_icon="computer", math=bool(self.home and self.home["math"]))

    def build_entries(self):
        for k, p in enumerate(self.posts):
            newer = self.posts[k - 1] if k > 0 else None
            older = self.posts[k + 1] if k + 1 < len(self.posts) else None
            pager = ['<a class="btn" rel="prev" href="%s" title="%s">&lt; Older</a>' % (older["url"], html.escape(older["title"]))
                     if older else '<span class="btn disabled">&lt; Older</span>',
                     '<a class="btn" href="/notebook/">All entries</a>',
                     '<a class="btn" rel="next" href="%s" title="%s">Newer &gt;</a>' % (newer["url"], html.escape(newer["title"]))
                     if newer else '<span class="btn disabled">Newer &gt;</span>']
            tags = '<p class="tags">%s</p>' % " ".join(
                '<a href="/notebook/tags/%s/">#%s</a>' % (tag_slug(t), html.escape(t)) for t in p["tags"]) if p["tags"] else ""
            body = """<article class="pane doc">
<header class="doc-head">
  <time datetime="{iso}">{date}</time>
  <h1>{title}</h1>
  {tags}
</header>
<div class="prose">
{body}
</div>
</article>
<nav class="pager">{pager}</nav>""".format(iso=p["date"].isoformat(), date=long_date(p["date"]),
                                          title=html.escape(p["title"]), tags=tags, body=p["html"], pager="".join(pager))
            status = [long_date(p["date"])] + (["DRAFT: hidden on the public site"] if p["draft"] else [])
            title = "%s%s - %s" % (p["title"], " [draft]" if p["draft"] else "", self.cfg["notebook_title"])
            content = window(title, "doc", body, address=p["url"], status=status, close="/notebook/")
            self.write(p["url"], p["title"], content, active="notebook", math=p["math"], description=p["summary"])

    def build_notebook(self):
        name = self.cfg["notebook_title"]
        tags = sorted({t for p in self.posts for t in p["tags"]}, key=str.lower)
        parts = ['<h1 class="sr-only">%s</h1>' % html.escape(name)]
        if tags:
            parts.append('<div class="toolbar">%s</div>' % "".join(
                '<a class="btn small" href="/notebook/tags/%s/">#%s</a>' % (tag_slug(t), html.escape(t)) for t in tags))
        parts.append(self.entry_table(self.posts, by_year=True))
        status = [self.count(len(self.posts), "entry", "entries"), self.count(len(tags), "tag", "tags")]
        self.write("/notebook/", name, window(name, "notebook", "\n".join(parts), address="/notebook/", status=status),
                   active="notebook", task_icon="notebook")

        for t in tags:
            tagged = [p for p in self.posts if t in p["tags"]]
            body = ('<h1 class="sr-only">#%s</h1>\n<div class="toolbar"><a class="btn small" href="/notebook/">&lt; All entries</a></div>\n%s'
                    % (html.escape(t), self.entry_table(tagged)))
            url = "/notebook/tags/%s/" % tag_slug(t)
            content = window("#" + t, "folder", body, address=url, status=[self.count(len(tagged), "entry", "entries")],
                             close="/notebook/")
            self.write(url, "#" + t, content, active="notebook", task_icon="folder")

    def build_pages(self):
        for p in self.pages:
            parts = ['<h1 class="sr-only">%s</h1>' % html.escape(p["title"])]
            href = "/files/%s" % p["file"]
            if p["has_file"]:
                parts.append('<div class="toolbar"><a class="btn" href="%s" download>%s Download %s</a>'
                             '<a class="btn" href="%s">Open in new tab</a></div>' % (
                                 html.escape(href), icon(p["icon"]), html.escape(p["file"]), html.escape(href)))
            if p["empty"]:
                hint = "Write in %s" % p["source"]
                if p["file"]:
                    hint += " and/or put files/%s in place" % p["file"]
                parts.append(empty_slot(p["source"], hint + ". Hidden on the public site until filled."))
            elif p["file"] and not p["has_file"] and self.dev:
                parts.append(empty_slot("files/" + p["file"], "Drop the file here to add a download button."))
            if p["html"].strip():
                parts.append('<div class="pane doc prose">%s</div>' % p["html"])
            if p["has_file"] and p["file"].lower().endswith(".pdf"):
                parts.append('<div class="pane list"><object class="pdf" data="%s" type="application/pdf">'
                             '<p class="empty"><a href="%s">Open %s</a></p></object></div>' % (
                                 html.escape(href), html.escape(href), html.escape(p["file"])))
            content = window(p["title"], p["icon"], "\n".join(parts), address=p["url"], status=["updated %s" % self.today.isoformat()])
            self.write(p["url"], p["title"], content, active=p["slug"], task_icon=p["icon"], math=p["math"])

    def build_404(self):
        body = ('<div class="dialog-body">%s<h1>Page not found</h1></div>\n'
                '<div class="dialog-buttons"><a class="btn" href="/">OK</a></div>' % icon("error", 32))
        self.write("/404.html", "Error", window("Error", "error", body, cls="dialog"), task_icon="error")

    def build_feed(self):
        if not self.cfg["url"] or self.dev:
            return
        base = self.cfg["url"]
        updated = self.posts[0]["date"] if self.posts else dt.datetime.now()
        entries = []
        for p in self.posts[:20]:
            body = re.sub(r'(href|src)="/(?!/)', r'\1="%s/' % base, p["html"])
            entries.append("""  <entry>
    <title>{title}</title>
    <link href="{url}"/>
    <id>{url}</id>
    <updated>{date}</updated>
    <content type="html">{body}</content>
  </entry>""".format(title=html.escape(p["title"]), url=base + p["url"],
                     date=p["date"].strftime("%Y-%m-%dT%H:%M:%SZ"), body=html.escape(body)))
        feed = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>{title}</title>
  <link href="{base}/"/>
  <link rel="self" href="{base}/feed.xml"/>
  <id>{base}/</id>
  <updated>{updated}</updated>
  <author><name>{author}</name></author>
{entries}
</feed>
""".format(title=html.escape(self.cfg["title"]), base=base, author=html.escape(self.cfg["author"]),
           updated=updated.strftime("%Y-%m-%dT%H:%M:%SZ"), entries="\n".join(entries))
        (self.out / "feed.xml").write_text(feed, encoding="utf-8")

    def build(self):
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        shutil.copy(THEME / "style.css", self.out / "style.css")
        if FILES.exists():
            shutil.copytree(FILES, self.out / "files", ignore=shutil.ignore_patterns(".*"))
        self.build_home()
        self.build_entries()
        self.build_notebook()
        self.build_pages()
        self.build_404()
        self.build_feed()
        (self.out / ".nojekyll").write_text("")
        if self.cfg["domain"] and not self.dev:
            (self.out / "CNAME").write_text(self.cfg["domain"].strip() + "\n")
        return self


def empty_slot(where, hint):
    return '<div class="slot">%s<div><strong>Empty slot</strong> <code>%s</code><br>%s</div></div>' % (
        icon("folder", 32), html.escape(where), html.escape(hint))


def relativize(page, depth):
    """Turns root links ("/about/") into relative ones, so the site works from any folder or subpath."""
    prefix = "../" * depth or "./"
    return re.sub(r'(href|src|data)="/(?!/)', lambda m: '%s="%s' % (m.group(1), prefix), page)


def build(dev=False):
    return Site(dev).build()
