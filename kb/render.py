"""
把词条正文（Markdown）变成网页，并把其中出现的专业词自动变成可点击的链接。

规则：
- 能被链接的词：其他词条的缩写、中文名、行业俗称（至少 2 个字符）；
- 长词优先（“抗冲共聚聚丙烯”先于“聚丙烯”）；
- 英文缩写要求前后不是字母或数字（“PP”不会误连到“PPS”里）；
- 同一个词条在一页里只链接第一次出现；
- 一个写法对应多个词条（比如 PIR）时不自动链接，避免连错；
- 标题、已有链接、代码里不加链接。
"""

import html
import re

import markdown
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils.safestring import mark_safe

from . import models as m

_LINKABLE_KINDS = [m.Alias.Kind.ABBR, m.Alias.Kind.NAME_ZH, m.Alias.Kind.NICKNAME]
_SKIP_TAGS = {"a", "code", "pre", "h1", "h2", "h3", "h4", "h5", "h6"}
_TAG_RE = re.compile(r"(<[^>]+>)")
_TAG_NAME_RE = re.compile(r"^<\s*(/)?\s*([a-zA-Z0-9]+)")
_ASCII_TERM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-/+. ]*$")


_BLOCK_START_RE = re.compile(r"^\s*([-*+]\s|\d+\.\s|\|)")


def _ensure_block_spacing(text: str) -> str:
    """列表和表格前面自动补一个空行（Markdown 要求，不然会和上一段挤成一行）。"""
    out = []
    for line in (text or "").split("\n"):
        if out and _BLOCK_START_RE.match(line):
            prev = out[-1]
            if prev.strip() and not _BLOCK_START_RE.match(prev) and not prev.startswith((" ", "\t")):
                out.append("")
        out.append(line)
    return "\n".join(out)


def md_to_html(text: str) -> str:
    return markdown.markdown(_ensure_block_spacing(text), extensions=["tables", "sane_lists"])


class TermLinker:
    def __init__(self, exclude_entry_id=None):
        ct = ContentType.objects.get_for_model(m.Entry)
        rows = m.Alias.objects.filter(content_type=ct, kind__in=_LINKABLE_KINDS).values_list("text", "object_id")
        by_text = {}
        for text, obj_id in rows:
            text = text.strip()
            if len(text) < 2:
                continue
            by_text.setdefault(text, set()).add(obj_id)
        # 一个写法对应多个词条的不自动链接；排除当前词条自己的名字
        self.term_to_id = {
            t: next(iter(ids)) for t, ids in by_text.items()
            if len(ids) == 1 and exclude_entry_id not in ids
        }
        self.titles = dict(m.Entry.objects.filter(pk__in=set(self.term_to_id.values()))
                           .values_list("pk", "one_liner"))
        self.used_ids = set()
        self.pattern = self._build_pattern()

    def _build_pattern(self):
        if not self.term_to_id:
            return None
        parts = []
        for term in sorted(self.term_to_id, key=len, reverse=True):
            escaped = re.escape(html.escape(term, quote=False))
            if _ASCII_TERM_RE.match(term):
                parts.append(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])")
            else:
                parts.append(escaped)
        return re.compile("|".join(parts))

    def _link_text(self, segment: str) -> str:
        def repl(match):
            raw = html.unescape(match.group(0))
            entry_id = self.term_to_id.get(raw)
            if entry_id is None or entry_id in self.used_ids:
                return match.group(0)
            self.used_ids.add(entry_id)
            url = reverse("kb:entry", args=[entry_id])
            title = html.escape(self.titles.get(entry_id) or "点击查看解释")
            return f'<a class="term" href="{url}" title="{title}">{match.group(0)}</a>'
        return self.pattern.sub(repl, segment)

    def link(self, html_text: str) -> str:
        if not self.pattern:
            return html_text
        out, skip_depth = [], 0
        for piece in _TAG_RE.split(html_text):
            if piece.startswith("<"):
                tag = _TAG_NAME_RE.match(piece)
                if tag and tag.group(2).lower() in _SKIP_TAGS and not piece.endswith("/>"):
                    skip_depth += -1 if tag.group(1) else 1
                    skip_depth = max(skip_depth, 0)
                out.append(piece)
            elif skip_depth or not piece.strip():
                out.append(piece)
            else:
                out.append(self._link_text(piece))
        return "".join(out)

    def render(self, text: str):
        return mark_safe(self.link(md_to_html(text)))
