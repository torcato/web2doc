from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from web2doc.documentation.models import DocumentContent

_MARKDOWN_SPECIAL = re.compile(r"([\\`*_[\]{}()#+.!|>-])")


def markdown_escape(value: object) -> str:
    text = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


class MarkdownRenderer:
    def __init__(self) -> None:
        environment = Environment(
            loader=FileSystemLoader(Path(__file__).with_name("templates")),
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=True,
        )
        environment.filters["md"] = markdown_escape
        self.template = environment.get_template("guide.md.j2")

    def render(self, document: DocumentContent, *, evidence_prefix: str = "") -> str:
        if evidence_prefix not in {"", "../"}:
            raise ValueError("unsupported evidence link prefix")
        return self.template.render(document=document, evidence_prefix=evidence_prefix)
