import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import render_site

SITE = Path(__file__).resolve().parents[1] / "site"


class FloxCreditTests(unittest.TestCase):
    """The player page credits Flox, which builds, tests and deploys this tree.

    The credit is part of a sponsorship arrangement, so losing it in a page
    rewrite should fail CI rather than go unnoticed.
    """

    def footer(self, html: str) -> str:
        match = re.search(r'<footer class="site-foot">(.*?)</footer>', html, re.S)
        self.assertIsNotNone(match, "player page has no site-foot footer")
        return match.group(1)

    def test_template_links_flox_and_source(self) -> None:
        footer = self.footer((SITE / "index.html").read_text(encoding="utf-8"))
        self.assertIn('href="https://flox.dev"', footer)
        self.assertIn('href="https://github.com/imkarrer/ac-host"', footer)

    def test_rendering_keeps_the_credit(self) -> None:
        rendered = render_site.substitute((SITE / "index.html").read_text(encoding="utf-8"))
        self.assertIn('href="https://flox.dev"', self.footer(rendered))

    def test_footer_is_styled(self) -> None:
        self.assertIn(".site-foot {", (SITE / "style.css").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
