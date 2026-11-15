"""Smoke-test the rendered workspace pages and every static asset they reference."""

from html.parser import HTMLParser
import unittest

from fastapi.testclient import TestClient

from src.managers.io_manager import IOManager


class StaticReferences(HTMLParser):
    """Collect local stylesheet and script URLs from a rendered page."""

    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        for name in ("href", "src"):
            value = attributes.get(name, "")
            if value.startswith("/static/"):
                self.urls.append(value)


class FrontendPageRouteTests(unittest.TestCase):
    def setUp(self):
        # Page and static routes must work without opening a database connection.
        self.client = TestClient(IOManager(None, None).get_application())
        self.addCleanup(self.client.close)

    def test_workspace_pages_render_and_serve_their_referenced_assets(self):
        pages = (
            ("/", "Stackplan — Assessment schedule", "/static/app.js"),
            ("/documents", "Source traceability — Stackplan", "/static/document-workspace.js"),
        )

        for route, title, entrypoint in pages:
            with self.subTest(page=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertIn(title, response.text)
                self.assertEqual(response.headers["cache-control"], "no-store")

                references = StaticReferences()
                references.feed(response.text)
                self.assertIn(entrypoint, references.urls)
                self.assertTrue(references.urls, "Page should reference local static assets")

                for url in sorted(set(references.urls)):
                    with self.subTest(page=route, asset=url):
                        asset = self.client.get(url)
                        self.assertEqual(asset.status_code, 200)
                        self.assertEqual(asset.headers["x-content-type-options"], "nosniff")
                        self.assertEqual(asset.headers["cache-control"], "no-store")
                        self.assertTrue(asset.content)

    def test_unknown_page_routes_are_not_served_as_workspace_pages(self):
        response = self.client.get("/missing-workspace-page")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
