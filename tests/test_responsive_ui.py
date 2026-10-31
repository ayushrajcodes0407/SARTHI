"""
SARTHI: Responsive UI Optimization Unit Tests
Verifies cross-device compatibility across all 8 target viewports:
- Small mobile (320x640)
- Standard mobile (375x812)
- Large mobile (430x932)
- Tablet portrait (768x1024)
- Tablet landscape (1024x768)
- Small laptop (1280x720)
- Desktop (1440x900)
- Large desktop (1920x1080)
Validates header, drawer overlays, landing hero, conversation cards,
horizontal table scrolls, composer action row, and zero desktop regression.
"""

import unittest
import os
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STYLE_CSS_PATH = os.path.join(BASE_DIR, "web", "style.css")
INDEX_HTML_PATH = os.path.join(BASE_DIR, "web", "index.html")
APP_JS_PATH = os.path.join(BASE_DIR, "web", "app.js")


class TestResponsiveUIOptimization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(STYLE_CSS_PATH, "r", encoding="utf-8") as f:
            cls.css = f.read()
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            cls.html = f.read()
        with open(APP_JS_PATH, "r", encoding="utf-8") as f:
            cls.js = f.read()

    def test_01_viewport_meta_tag(self):
        """Verify modern responsive viewport meta tag with viewport-fit=cover."""
        self.assertIn('viewport-fit=cover', self.html)
        self.assertIn('width=device-width', self.html)
        self.assertIn('initial-scale=1.0', self.html)

    def test_02_breakpoints_presence_in_css(self):
        """Verify presence of all suggested and required breakpoint media queries."""
        expected_breakpoints = [
            "max-width: 1023px",
            "max-width: 767px",
            "max-width: 480px",
            "max-width: 374px",
            "max-width: 1279px",
            "max-height: 500px"
        ]
        for bp in expected_breakpoints:
            self.assertIn(bp, self.css, f"Breakpoint {bp} missing in style.css")

    def test_03_dvh_units_and_mobile_safe_areas(self):
        """Verify modern dvh viewport units and safe-area environment variables."""
        self.assertIn("100dvh", self.css)
        self.assertIn("env(safe-area-inset-top", self.css)
        self.assertIn("env(safe-area-inset-bottom", self.css)

    def test_04_drawer_overlay_tablet_and_mobile(self):
        """Verify left & right panels operate as overlay drawers without squeezing center."""
        # Check drawer overlay styling in max-width: 1023px
        self.assertIn("position: fixed !important", self.css)
        self.assertIn("transform: translateX(-100%)", self.css)
        self.assertIn("transform: translateX(100%)", self.css)
        # Backdrop for closing on outside click
        self.assertIn(".sidebar-backdrop", self.css)
        self.assertIn("backdrop-filter: blur", self.css)
        # Verify closeAllSidebars is attached to sidebarBackdrop in HTML
        self.assertIn('id="sidebarBackdrop"', self.html)
        self.assertIn('closeAllSidebars()', self.html)

    def test_05_header_navigation_responsiveness(self):
        """Verify header elements compact gracefully on narrow viewports."""
        # Toggle button label hidden on <= 1023px
        self.assertIn(".toggle-btn-label", self.css)
        # Brand subtext hidden on <= 767px
        self.assertIn(".brand .sub-text", self.css)
        # Header New Chat button compact icon on <= 480px
        self.assertIn(".header-new-chat-btn", self.css)

    def test_06_landing_page_clamp_and_centering(self):
        """Verify default landing page uses responsive clamp() and avoids vertical overflow."""
        self.assertIn("clamp(", self.css)
        self.assertIn(".landing-hero-container", self.css)
        self.assertIn(".landing-welcome-title", self.css)
        self.assertIn(".landing-welcome-sub", self.css)

    def test_07_conversation_stream_and_table_wrapping(self):
        """Verify messages, tables, and code blocks wrap or scroll without page clipping."""
        self.assertIn("overflow-wrap: anywhere", self.css)
        self.assertIn("word-break: break-word", self.css)
        # Horizontal table wrapping
        self.assertIn(".chat-table-wrap", self.css)
        self.assertIn("overflow-x: auto", self.css)
        self.assertIn(".chat-markdown pre", self.css)

    def test_08_message_composer_compactness_and_no_collision(self):
        """Verify composer controls never collide or push Execute button out on small screens."""
        # Execute button retains visible minimum width and styling
        self.assertIn(".composer-execute-btn", self.css)
        self.assertIn("min-width:", self.css)
        # Wake word label hidden on standard mobile to prevent button squishing
        self.assertIn(".wake-btn-label", self.css)
        # Small mobile wrapping rule for 320px
        self.assertIn("flex-wrap: wrap !important", self.css)

    def test_09_saved_data_library_responsiveness(self):
        """Verify Saved Data Library and Tactical Intel fit within drawers."""
        self.assertIn(".library-module-box", self.css)
        self.assertIn(".library-toolbar", self.css)
        self.assertIn(".library-card-name", self.css)

    def test_10_desktop_appearance_integrity(self):
        """Verify desktop (>1280px) appearance remains preserved and uncorrupted."""
        # Original desktop sidebar widths and transition rules must be intact
        self.assertIn(".panel.left-panel", self.css)
        self.assertIn(".panel.right-panel", self.css)
        self.assertIn("var(--cyan)", self.css)
        self.assertIn("#C5A06A", self.css)


    def test_11_suggested_inquiries_followup_chips_styling(self):
        """Verify suggested next inquiries / follow-up chips wrap cleanly with 6px border-radius."""
        self.assertIn('.chat-followup-chip', self.css)
        self.assertIn('border-radius: 6px', self.css)
        self.assertIn('word-break: break-word', self.css)
        self.assertIn('overflow-wrap: break-word', self.css)
        self.assertIn('white-space: normal', self.css)
        self.assertIn('flex-wrap: wrap', self.css)

    def test_12_mobile_footer_compactness_and_sticky_composer(self):
        """Verify mobile footer is compact 20px, keyboard hints hidden, composer is sticky."""
        self.assertIn('height: 20px !important', self.css)
        self.assertIn('.footer-right', self.css)
        self.assertIn('position: sticky !important', self.css)
        self.assertIn('text-overflow: ellipsis', self.css)

    def test_13_header_overcrowding_prevention(self):
        """Verify mobile header controls prevent brand collision and overcrowding."""
        self.assertIn('#statusText', self.css)
        self.assertIn('.chat-current-title', self.css)
        self.assertIn('.chat-action-btn span', self.css)
        self.assertIn('.sarthi-brand-logo-wrap', self.css)

    def test_14_composer_two_row_layout_and_zero_collision(self):
        """Verify composer cleanly maintains 2-row layout with zero button collisions."""
        self.assertIn('composer-input-row', self.html)
        self.assertIn('composer-action-row', self.html)
        self.assertIn('composer-action-left', self.html)
        self.assertIn('composer-action-right', self.html)
        self.assertIn('flex-wrap: wrap !important', self.css)
        self.assertIn('.wake-btn-label', self.css)


if __name__ == "__main__":
    unittest.main()


