"""Parsed source text that extracted facts can cite as evidence."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceElement:
    """One bounded segment of text from a single document parse.

    ``regions`` holds the page locations used to highlight the text in the
    original document, and ``context`` names the heading or table it came
    from. Facts refer to an element by ``id`` so evidence stays traceable.
    """

    id: str
    document_id: str
    parse_id: str
    text: str
    regions: list
    context: str
