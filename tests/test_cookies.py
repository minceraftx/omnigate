"""Unit tests for cookie domain filtering (no browser needed)."""
import unittest

from omnigate.browser.cookies import cookies_for_url


def _c(domain: str, name: str = "k") -> dict:
    return {"name": name, "value": "v", "domain": domain}


class TestCookiesForUrl(unittest.TestCase):
    def test_parent_domain_matches_subdomain(self):
        cookies = [_c(".bilibili.com", "parent")]
        result = cookies_for_url(cookies, "https://www.bilibili.com/")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "parent")

    def test_subdomain_cookie_does_not_match_parent(self):
        cookies = [_c("api.bilibili.com", "sub")]
        result = cookies_for_url(cookies, "https://bilibili.com/")
        self.assertEqual(result, [])

    def test_foreign_domain_does_not_match(self):
        cookies = [_c("evilbilibili.com", "evil")]
        result = cookies_for_url(cookies, "https://www.bilibili.com/")
        self.assertEqual(result, [])

    def test_exact_host_match(self):
        cookies = [_c("example.com", "exact")]
        result = cookies_for_url(cookies, "https://example.com/")
        self.assertEqual(len(result), 1)

    def test_missing_domain_field_ignored(self):
        cookies = [{"name": "k", "value": "v"}]  # no domain
        result = cookies_for_url(cookies, "https://example.com/")
        self.assertEqual(result, [])

    def test_empty_host_no_crash(self):
        cookies = [_c("example.com")]
        result = cookies_for_url(cookies, "")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
