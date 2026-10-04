"""SEC HTML cleanup preserving substantive filing content."""

import re

from bs4 import BeautifulSoup


def clean_html(html: str) -> str:
    """Remove clear page chrome while preserving substantive filing content."""
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all(
        ["script", "style", "noscript", "template", "nav", "form", "iframe", "svg"]
    ):
        if node.parent is not None:
            node.decompose()

    chrome_pattern = re.compile(
        r"(?:cookie|social|share|sidebar|toolbar|breadcrumb|site[-_ ]?(?:nav|header|footer))",
        re.I,
    )
    for node in soup.find_all(attrs={"role": re.compile(r"^(navigation|complementary)$", re.I)}):
        if node.parent is not None:
            node.decompose()
    for node in soup.find_all(attrs={"class": True}):
        if node.attrs is None:  # A matching ancestor may already have been removed.
            continue
        classes = " ".join(node.get("class", []))
        if chrome_pattern.search(classes):
            node.decompose()
    for node in soup.find_all(id=True):
        if node.attrs is None:
            continue
        if chrome_pattern.search(node.get("id", "")):
            node.decompose()

    return str(soup)
