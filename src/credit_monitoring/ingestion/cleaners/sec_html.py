"""SEC HTML cleanup preserving substantive filing content."""

import re

from bs4 import BeautifulSoup

CHROME_IDENTIFIERS = frozenset(
    {
        "cookie",
        "cookie-banner",
        "cookie-consent",
        "social",
        "social-share",
        "share",
        "share-buttons",
        "sidebar",
        "toolbar",
        "breadcrumb",
        "breadcrumbs",
        "site-nav",
        "site-header",
        "site-footer",
    }
)


def _is_chrome(identifier: str) -> bool:
    return identifier.casefold().replace("_", "-") in CHROME_IDENTIFIERS


def clean_html(html: str) -> str:
    """Remove clear page chrome while preserving substantive filing content."""
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all(
        ["script", "style", "noscript", "template", "nav", "form", "iframe", "svg"]
    ):
        if node.parent is not None:
            node.decompose()

    for node in soup.find_all(attrs={"role": re.compile(r"^(navigation|complementary)$", re.I)}):
        if node.parent is not None:
            node.decompose()
    for node in soup.find_all(attrs={"class": True}):
        if node.attrs is None:  # A matching ancestor may already have been removed.
            continue
        if any(_is_chrome(value) for value in node.get("class", [])):
            node.decompose()
    for node in soup.find_all(id=True):
        if node.attrs is None:
            continue
        if _is_chrome(node.get("id", "")):
            node.decompose()

    return str(soup)
