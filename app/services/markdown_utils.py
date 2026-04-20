from __future__ import annotations

import re
from html import escape, unescape
from html.parser import HTMLParser
from urllib.parse import urlparse

import markdown
from markupsafe import Markup


MARKDOWN_EXTENSIONS = ['extra', 'nl2br', 'sane_lists']
TAG_RE = re.compile(r'<[^>]+>')
WHITESPACE_RE = re.compile(r'\s+')
FENCE_RE = re.compile(r'^\s*(```|~~~)')
LIST_MARKER_RE = re.compile(r'^\s*(?:[-+*]\s+|\d+\.\s+)')
CPP_DIRECTIVE_RE = re.compile(r'^\s*#(?:include|define|ifdef|ifndef|endif|pragma|if|elif|else|undef|error|line)\b')
ALLOWED_TAGS = {
    'a',
    'blockquote',
    'br',
    'code',
    'em',
    'h1',
    'h2',
    'h3',
    'h4',
    'h5',
    'h6',
    'hr',
    'li',
    'ol',
    'p',
    'pre',
    'strong',
    'ul',
    'table',
    'thead',
    'tbody',
    'tr',
    'th',
    'td',
}
SELF_CLOSING_TAGS = {'br', 'hr'}
DROP_WITH_CONTENT_TAGS = {'script', 'style'}


def preprocess_markdown(text: str) -> str:
    lines = text.splitlines()
    processed: list[str] = []
    in_fence = False

    for line in lines:
        if FENCE_RE.match(line):
            in_fence = not in_fence
            processed.append(line)
            continue

        if not in_fence and LIST_MARKER_RE.match(line):
            previous_line = processed[-1] if processed else ''
            if previous_line.strip() and not LIST_MARKER_RE.match(previous_line):
                processed.append('')

        if not in_fence and CPP_DIRECTIVE_RE.match(line):
            line = re.sub(r'^(\s*)#', r'\1\\#', line, count=1)
            line = line.replace('<', '&lt;').replace('>', '&gt;')

        processed.append(line)

    return '\n'.join(processed)


def sanitize_url(value: str) -> str | None:
    candidate = unescape(value).strip()
    if not candidate:
        return None
    parsed = urlparse(candidate)
    if parsed.scheme and parsed.scheme not in {'http', 'https', 'mailto'}:
        return None
    if candidate.startswith('//'):
        return None
    return escape(candidate, quote=True)


class SafeHTMLSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.drop_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in DROP_WITH_CONTENT_TAGS:
            self.drop_depth += 1
            return
        if self.drop_depth or normalized_tag not in ALLOWED_TAGS:
            return
        rendered_attrs: list[str] = []
        for attr_name, attr_value in attrs:
            normalized_attr = attr_name.lower()
            if normalized_tag == 'a' and normalized_attr == 'href' and attr_value is not None:
                safe_href = sanitize_url(attr_value)
                if safe_href:
                    rendered_attrs.append(f'href="{safe_href}"')
            elif normalized_tag == 'a' and normalized_attr == 'title' and attr_value is not None:
                rendered_attrs.append(f'title="{escape(attr_value, quote=True)}"')
            elif normalized_tag == 'code' and normalized_attr == 'class' and attr_value:
                if attr_value.startswith('language-'):
                    rendered_attrs.append(f'class="{escape(attr_value, quote=True)}"')
            elif normalized_tag in {'th', 'td'} and normalized_attr == 'align' and attr_value in {'left', 'center', 'right'}:
                rendered_attrs.append(f'align="{attr_value}"')
        attr_suffix = f" {' '.join(rendered_attrs)}" if rendered_attrs else ''
        if normalized_tag in SELF_CLOSING_TAGS:
            self.parts.append(f'<{normalized_tag}{attr_suffix}>')
        else:
            self.parts.append(f'<{normalized_tag}{attr_suffix}>')

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in DROP_WITH_CONTENT_TAGS:
            if self.drop_depth:
                self.drop_depth -= 1
            return
        if self.drop_depth or normalized_tag not in ALLOWED_TAGS or normalized_tag in SELF_CLOSING_TAGS:
            return
        self.parts.append(f'</{normalized_tag}>')

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self.drop_depth:
            return
        self.parts.append(escape(data))

    def handle_entityref(self, name: str) -> None:
        if self.drop_depth:
            return
        self.parts.append(f'&{name};')

    def handle_charref(self, name: str) -> None:
        if self.drop_depth:
            return
        self.parts.append(f'&#{name};')

    def get_html(self) -> str:
        return ''.join(self.parts)


def sanitize_html(html: str) -> str:
    sanitizer = SafeHTMLSanitizer()
    sanitizer.feed(html)
    sanitizer.close()
    return sanitizer.get_html()


def render_markdown(text: str | None) -> Markup:
    if not text:
        return Markup('')

    prepared_source = preprocess_markdown(text)
    rendered = markdown.markdown(prepared_source, extensions=MARKDOWN_EXTENSIONS)
    return Markup(sanitize_html(rendered))


def markdown_to_plain_text(text: str | None) -> str:
    if not text:
        return ''

    rendered = render_markdown(text)
    plain_text = TAG_RE.sub(' ', str(rendered))
    plain_text = unescape(plain_text)
    return WHITESPACE_RE.sub(' ', plain_text).strip()


def build_markdown_excerpt(text: str | None, max_length: int = 120) -> str:
    plain_text = markdown_to_plain_text(text)
    if not plain_text:
        return ''
    if len(plain_text) <= max_length:
        return plain_text
    return plain_text[:max_length].rstrip() + '...'
