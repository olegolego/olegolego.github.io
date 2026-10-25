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
    return "%d %s %Y" % (d.day, MONTHS[d.month - 1], d.year)


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
            "empty": not body.strip() and not has_file,
            "source": path.relative_to(ROOT).as_posix(),
            "url": "/" if path.stem == "home" else "/%s/" % path.stem,
        })
    return pages


# ---------------------------------------------------------------- rendering

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

    def nav(self, active):
        tabs = [("/notebook/", self.cfg["notebook_title"], "notebook")]
        for p in sorted((p for p in self.pages if p["nav"] is not None), key=lambda p: (p["nav"], p["title"])):
            tabs.append((p["url"], p["title"], p["slug"]))
        out = []
        for url, title, key in tabs:
            cls = ' class="active" aria-current="page"' if key == active else ""
            out.append('<a href="%s"%s>%s</a>' % (url, cls, html.escape(title)))
        return "\n    ".join(out)

    def footer(self):
        bits = []
        for link in self.cfg["links"]:
            if link.get("url"):
                bits.append('<a href="%s">%s</a>' % (html.escape(link["url"]), html.escape(link.get("label", link["url"]))))
        if self.cfg["url"] and not self.dev:
            bits.append('<a href="/feed.xml">RSS</a>')
        bits.append("updated %s" % self.today.isoformat())
        return " · ".join(bits)

    def write(self, url, title, content, active="", math=False, description=""):
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
            "tagline": '<p class="tagline">%s</p>' % markdown.inline(self.cfg["tagline"]) if self.cfg["tagline"] else "",
            "nav": self.nav(active),
            "content": content,
            "footer": self.footer(),
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

    def entry_list(self, posts, summaries=False, date_format="%Y-%m-%d"):
        if not posts:
            return '<p class="muted">No entries yet.</p>'
        items = []
        for p in posts:
            draft = ' <span class="draft-tag">draft</span>' if p["draft"] else ""
            summary = '<span class="summary">%s</span>' % html.escape(p["summary"]) if summaries and p["summary"] else ""
            items.append('<li><time datetime="%s">%s</time><span><a href="%s">%s</a>%s%s</span></li>' % (
                p["date"].date().isoformat(), p["date"].strftime(date_format).lstrip("0"),
                p["url"], html.escape(p["title"]), draft, summary))
        return '<ul class="entries">\n%s\n</ul>' % "\n".join(items)

    def tag_links(self, tags):
        return " ".join('<a class="tag" href="/notebook/tags/%s/">#%s</a>' % (tag_slug(t), html.escape(t)) for t in tags)

    # -- pages

    def build_home(self):
        parts = []
        if self.home and not self.home["empty"]:
            parts.append('<div class="prose">%s</div>' % self.home["html"])
        elif self.dev:
            parts.append(empty_slot("pages/home.md", "Intro text for the front page."))
        latest = self.posts[: int(self.cfg["home_entries"])]
        parts.append('<section class="recent">\n<h2>Recent</h2>\n%s' % self.entry_list(latest, summaries=True))
        if len(self.posts) > len(latest):
            parts.append('<p class="more"><a href="/notebook/">All %d entries →</a></p>' % len(self.posts))
        parts.append("</section>")
        self.write("/", "", "\n".join(parts), active="home", math=bool(self.home and self.home["math"]))

    def build_entries(self):
        for k, p in enumerate(self.posts):
            newer = self.posts[k - 1] if k > 0 else None
            older = self.posts[k + 1] if k + 1 < len(self.posts) else None
            pager = []
            if older:
                pager.append('<a rel="prev" href="%s">← %s</a>' % (older["url"], html.escape(older["title"])))
            else:
                pager.append("<span></span>")
            if newer:
                pager.append('<a rel="next" href="%s">%s →</a>' % (newer["url"], html.escape(newer["title"])))
            stamp = '<div class="draft-stamp">draft</div>' if p["draft"] else ""
            tags = '<p class="tags">%s</p>' % self.tag_links(p["tags"]) if p["tags"] else ""
            content = """<article class="entry">
{stamp}<header>
  <time class="stamp" datetime="{iso}">{date}</time>
  <h1>{title}</h1>
  {tags}
</header>
<div class="prose">
{body}
</div>
<nav class="pager">{pager}</nav>
</article>""".format(stamp=stamp, iso=p["date"].isoformat(), date=p["date"].strftime("%Y-%m-%d"),
                     title=html.escape(p["title"]), tags=tags, body=p["html"], pager="".join(pager))
            self.write(p["url"], p["title"], content, active="notebook", math=p["math"], description=p["summary"])

    def build_notebook(self):
        parts = ['<h1>%s</h1>' % html.escape(self.cfg["notebook_title"])]
        tags = sorted({t for p in self.posts for t in p["tags"]}, key=str.lower)
        if tags:
            parts.append('<p class="tags">%s</p>' % self.tag_links(tags))
        if not self.posts:
            parts.append(self.entry_list([]))
        year = month = None
        group = []

        def flush():
            if group:
                parts.append("<h3>%s</h3>\n%s" % (MONTHS[month - 1], self.entry_list(group, date_format="%d")))

        for p in self.posts:
            if p["date"].year != year:
                flush()
                group = []
                year, month = p["date"].year, p["date"].month
                parts.append('<h2 class="year">%d</h2>' % year)
            elif p["date"].month != month:
                flush()
                group = []
                month = p["date"].month
            group.append(p)
        flush()
        self.write("/notebook/", self.cfg["notebook_title"], "\n".join(parts), active="notebook")

        for t in tags:
            tagged = [p for p in self.posts if t in p["tags"]]
            content = '<h1>#%s</h1>\n%s\n<p class="more"><a href="/notebook/">← all entries</a></p>' % (
                html.escape(t), self.entry_list(tagged))
            self.write("/notebook/tags/%s/" % tag_slug(t), "#" + t, content, active="notebook")

    def build_pages(self):
        for p in self.pages:
            parts = ['<h1>%s</h1>' % html.escape(p["title"])]
            if p["empty"]:
                hint = "Write in %s" % p["source"]
                if p["file"]:
                    hint += " and/or put files/%s in place" % p["file"]
                parts.append(empty_slot(p["source"], hint + ". Hidden on the public site until filled."))
            if p["has_file"]:
                href = "/files/%s" % p["file"]
                parts.append('<p class="doc-actions"><a class="button" href="%s" download>Download %s</a></p>' % (
                    html.escape(href), html.escape(p["file"])))
            elif p["file"] and self.dev and not p["empty"]:
                parts.append(empty_slot("files/" + p["file"], "Drop the file here to add a download button."))
            if p["html"].strip():
                parts.append('<div class="prose">%s</div>' % p["html"])
            if p["has_file"] and p["file"].lower().endswith(".pdf"):
                parts.append('<object class="pdf" data="%s" type="application/pdf"><p><a href="%s">Open %s</a></p></object>' % (
                    html.escape(href), html.escape(href), html.escape(p["file"])))
            self.write(p["url"], p["title"], "\n".join(parts), active=p["slug"], math=p["math"])

    def build_404(self):
        self.write("/404.html", "Not found", '<h1>Page not found</h1>\n<p><a href="/">← home</a></p>')

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
    return '<div class="slot"><strong>empty slot</strong> · <code>%s</code><br>%s</div>' % (
        html.escape(where), html.escape(hint))


def relativize(page, depth):
    """Turns root links ("/about/") into relative ones, so the site works from any folder or subpath."""
    prefix = "../" * depth or "./"
    return re.sub(r'(href|src|data)="/(?!/)', lambda m: '%s="%s' % (m.group(1), prefix), page)


def build(dev=False):
    return Site(dev).build()
