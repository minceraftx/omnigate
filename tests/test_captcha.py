"""Unit tests for captcha detection logic (no browser needed)."""
import unittest

from omnigate.browser.captcha import detect_captcha_features, CAPTCHA_PATTERNS


class TestDetectCaptchaFeatures(unittest.TestCase):
    def test_recaptcha_iframe(self):
        html = '<iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe>'
        result = detect_captcha_features(html)
        self.assertIn("recaptcha", result)

    def test_turnstile(self):
        html = '<iframe src="https://challenges.cloudflare.com/turnstile/"></iframe>'
        result = detect_captcha_features(html)
        self.assertIn("turnstile", result)

    def test_plain_page_no_captcha(self):
        html = "<html><body><h1>Hello</h1></body></html>"
        result = detect_captcha_features(html)
        self.assertEqual(result, [])

    def test_returns_list_of_matches(self):
        html = '<iframe src="/recaptcha/"></iframe><div id="hcaptcha"></div>'
        result = detect_captcha_features(html)
        self.assertTrue(set(result) & {"recaptcha", "hcaptcha"})

    def test_case_insensitive(self):
        html = '<iframe src="/RECAPTCHA/"></iframe>'
        result = detect_captcha_features(html)
        self.assertIn("recaptcha", result)


if __name__ == "__main__":
    unittest.main()
