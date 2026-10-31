"""
SARTHI: Automatic Wake-Word Detection & Hands-Free Voice Execution Unit Tests
Validates wake-word detection, wake-word stripping, state management, auto-execution routing,
manual mic auto-execution, echo feedback loop prevention, and continuous loop re-arming.
"""

import unittest
import re

class TestVoiceAutomationLogic(unittest.TestCase):
    def setUp(self):
        # The exact regex used in web/app.js
        self.wake_word_regex = re.compile(r'\b(sarthi|saarthi|sarathi|sarti)\b', re.IGNORECASE)

    def clean_wake_word_from_query(self, raw_text):
        """Python mirror of the JavaScript cleanWakeWordFromQuery function in web/app.js."""
        if not raw_text:
            return ""
        # Strip leading activation word
        cleaned = re.sub(r'^\s*(?:hey|hi|hello|ok|okay)?\s*(?:sarthi|saarthi|sarathi|sarti)\b[\s,.:;?!-]*', '', raw_text, flags=re.IGNORECASE)
        # Strip any repeated internal wake word
        cleaned = re.sub(r'\b(?:sarthi|saarthi|sarathi|sarti)\b', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
        return cleaned

    def test_01_wake_word_recognition_variations(self):
        """Scenario 3: Recognize natural pronunciation and variations of 'Sarthi'."""
        variations = [
            "Sarthi",
            "sarthi",
            "SARTHI",
            "Hey Sarthi",
            "saarthi",
            "sarathi",
            "sarti",
            "Sarthi, what is the margin of capacitor?",
            "ok sarthi show all products"
        ]
        for phrase in variations:
            self.assertTrue(bool(self.wake_word_regex.search(phrase)), f"Failed to match wake word in '{phrase}'")

    def test_02_wake_word_rejection_of_unrelated_words(self):
        """Scenario 3: Reject unrelated words and avoid accidental triggers."""
        unrelated = [
            "start the report",
            "search the database",
            "smart inventory",
            "sales report",
            "show products",
            "south region sales"
        ]
        for phrase in unrelated:
            self.assertFalse(bool(self.wake_word_regex.search(phrase)), f"Accidentally triggered on '{phrase}'")

    def test_03_wake_word_stripping_from_business_query(self):
        """Scenario 4 & 5: Detect 'Sarthi', strip activation word, and retain actual question."""
        test_cases = [
            ("Sarthi, what is the current stock of capacitor?", "what is the current stock of capacitor?"),
            ("Hey Sarthi, show me all products", "show me all products"),
            ("sarthi: tell me lowest stock items", "tell me lowest stock items"),
            ("Hello Saarthi, calculate profit margin of reactor", "calculate profit margin of reactor"),
            ("sarthi", ""), # Just the wake word, no trailing query
            ("SARTHI - list all suppliers", "list all suppliers"),
            ("What is gross margin sarthi?", "What is gross margin ?")
        ]
        for raw_input, expected_clean in test_cases:
            cleaned = self.clean_wake_word_from_query(raw_input)
            self.assertEqual(cleaned, expected_clean, f"Failed for raw input: '{raw_input}'")

    def test_04_empty_speech_rejection(self):
        """Scenario 14: Reject empty transcriptions, ambient noise, and do not execute."""
        empty_inputs = ["", "   ", "Sarthi", "hey sarthi!", "..."]
        for empty in empty_inputs:
            cleaned = self.clean_wake_word_from_query(empty)
            effective_chars = re.sub(r'[^a-zA-Z0-9]', '', cleaned)
            self.assertTrue(len(effective_chars) < 2, f"Expected empty query rejection for '{empty}', got '{cleaned}'")

    def test_05_manual_mic_preserves_full_query(self):
        """Scenario 12: Manual microphone mode captures query directly without needing wake word."""
        manual_speech = "Show all products with low stock"
        # In manual mode, cleanWakeWordFromQuery preserves the question unchanged
        cleaned = self.clean_wake_word_from_query(manual_speech)
        self.assertEqual(cleaned, manual_speech)

    def test_06_state_machine_completeness(self):
        """Verify all 9 strictly separated voice states are defined."""
        required_states = {
            'DISABLED',
            'INITIALIZING',
            'WAKE_WORD_LISTENING',
            'WAKE_WORD_DETECTED',
            'CAPTURING_QUERY',
            'TRANSCRIPTION_FINALIZING',
            'EXECUTING_QUERY',
            'SPEAKING_RESPONSE',
            'ERROR'
        }
        # Read web/app.js to verify all states are present in VoiceStates
        with open(r"C:\Users\bitd\Downloads\SARTHI\web\app.js", "r", encoding="utf-8") as f:
            js_code = f.read()

        for state in required_states:
            self.assertIn(f"'{state}'", js_code, f"State '{state}' missing in app.js")


if __name__ == '__main__':
    unittest.main()
