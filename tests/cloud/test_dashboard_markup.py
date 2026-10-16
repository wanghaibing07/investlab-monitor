"""Static quality gates for the human-facing private InvestLab dashboard.

No real account records, browser sessions or private APIs are accessed here.
"""
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2] / "deploy" / "cloud" / "assets"


class AuditHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.labels_for = []
        self.nav_routes = []
        self.pages = []
        self.scripts = []
        self.links = []
        self.fields = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "label" and "for" in a:
            self.labels_for.append(a["for"])
        if "data-route" in a:
            self.nav_routes.append(a["data-route"])
        if "data-page" in a:
            self.pages.append(a["data-page"])
        if tag == "script":
            self.scripts.append(a.get("src"))
        if tag == "link":
            self.links.append(a.get("href"))
        if tag in {"input", "textarea", "select"}:
            self.fields.append(a)


class DashboardMarkupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.css = (ROOT / "app.css").read_text(encoding="utf-8")
        cls.js = (ROOT / "app.js").read_text(encoding="utf-8")
        cls.parser = AuditHTML()
        cls.parser.feed(cls.html)

    def test_every_id_unique_and_form_labels_point_to_real_fields(self):
        p = self.parser
        self.assertEqual(len(p.ids), len(set(p.ids)), "Duplicate HTML id")
        ids = set(p.ids)
        for label in p.labels_for:
            self.assertIn(label, ids, label)
        for field in p.fields:
            self.assertIn("id", field, field)
        self.assertIn("valuation-date", ids)
        self.assertIn("valuation-note", ids)
        for required in ["decision-workbench", "decision-headline", "decision-next-step",
                         "decision-action-tickets", "decision-proof-status", "decision-account-date",
                         "model-conditions", "model-next", "run-action-headline"]:
            self.assertIn(required, ids)
        self.assertIn("valuation-confirmed", ids)

    def test_navigation_is_complete_not_decorative(self):
        p = self.parser
        self.assertEqual(set(p.nav_routes),
                         {"overview", "portfolio", "research", "runs", "settings"})
        self.assertEqual(set(p.pages), set(p.nav_routes))
        for required in ["history-chart", "allocation-donut", "portfolio-rows",
                         "history-rows", "weights-comparison", "risk-report",
                         "run-checks", "run-detail", "valuation-dialog",
                         "run-dialog", "global-error"]:
            self.assertIn(required, p.ids)

    def test_own_assets_only_and_no_embedded_private_values(self):
        self.assertEqual(self.parser.scripts, ["/assets/app.js"])
        self.assertEqual(self.parser.links, ["/assets/app.css", "/assets/decision.css"])
        self.assertNotIn("https://", self.html)
        self.assertNotIn("INVESTLAB_ADMIN_TOKEN", self.html)
        self.assertNotIn("BLOB_READ_WRITE_TOKEN", self.html)
        self.assertNotIn("12000", self.html)
        self.assertNotIn("8000", self.html)
        self.assertIn('lang="zh-CN"', self.html)
        self.assertIn('href="#main-content"', self.html)

    def test_app_avoids_fabricating_performance_or_trading(self):
        self.assertIn('api("/api/account")', self.js)
        self.assertIn('api("/api/history")', self.js)
        self.assertIn('apiOptional("/api/latest")', self.js)
        self.assertIn("entriesByDate()", self.js)
        self.assertIn('api("/api/brief")', self.js)
        self.assertIn("function renderDecision()", self.js)
        self.assertIn("if(actionable&&Array.isArray(b.steps))", self.js)
        self.assertIn("rows.length<2", self.js)
        self.assertIn("持仓", self.html)
        self.assertIn("不代表投资收益率", self.html)
        self.assertNotIn("Math.random(", self.js)
        self.assertNotIn("eval(", self.js)
        self.assertNotIn("localStorage.", self.js)

    def test_decision_first_user_can_find_evidence_action_and_history(self):
        for anchor in (
            "decision-workbench",
            "decision-headline",
            "decision-next-step",
            "decision-allocation",
            "decision-allocation-rows",
            "historical-signal",
            "historical-signal-title",
            "historical-signal-description",
            "decision-proof-status",
            "decision-session",
        ):
            self.assertIn(anchor, self.parser.ids, anchor)
        self.assertIn("function renderDecisionAllocation", self.js)
        self.assertIn("function renderHistoricalSignal", self.js)
        self.assertIn("Number.isSafeInteger(step.estimated_difference_cny)", self.js)
        self.assertIn("历史模型观察", self.html)
        self.assertIn("不是", self.html + self.js)
        self.assertNotIn("Math.random", self.js)
        self.assertNotIn("localStorage", self.js)
        self.assertIn(".decision-allocation-row", self.css + (ROOT / "decision.css").read_text(encoding="utf-8"))
        self.assertIn("不自动下单", self.html)

    def test_responsive_accessible_states_exist(self):
        self.assertIn("@media(max-width:880px)", self.css)
        self.assertIn("@media(max-width:640px)", self.css)
        self.assertIn("prefers-reduced-motion:reduce", self.css)
        self.assertIn("font-variant-numeric:tabular-nums", self.css)
        self.assertIn(":focus-visible", self.css)
        self.assertIn("aria-live", self.html)
        self.assertIn('role="alert"', self.html)
        self.assertIn('role="img"', self.html)
        self.assertIn(".empty-chart", self.css)
        modern=(ROOT / "decision.css").read_text(encoding="utf-8")
        self.assertIn(".decision-workbench", modern)
        self.assertIn(".action-ticket", modern)
        self.assertIn("@media(max-width:640px)", modern)
        self.assertIn(":focus-visible", self.css)


if __name__ == "__main__":
    unittest.main()
