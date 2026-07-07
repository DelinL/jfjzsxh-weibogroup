"""_is_logged_in 登录态判据测试

验证扫码登录态判定逻辑：api.weibo.com/chat 未登录时 URL 为 #/，
扫码登录成功后 hash 路由跳转为 #/chat。
"""
import unittest
from unittest.mock import MagicMock, patch

import requests

import crawl
from weibo_im.crawler import make_session, renew_cookie, _serialize_cookies


def _fake_page(url: str):
    """构造一个 page mock，evaluate("window.location.href") 返回给定 url"""
    page = MagicMock()
    page.evaluate.return_value = url
    return page


class IsLoggedInTest(unittest.TestCase):

    def test_rejects_login_page(self):
        """api.weibo.com/chat 未登录态 URL 为 #/ → 未登录"""
        page = _fake_page("https://api.weibo.com/chat#/")
        self.assertFalse(crawl._is_logged_in(page))

    def test_accepts_after_login(self):
        """扫码登录成功后 hash 路由变为 #/chat → 已登录"""
        page = _fake_page("https://api.weibo.com/chat#/chat")
        self.assertTrue(crawl._is_logged_in(page))

    def test_evaluate_raises_returns_false(self):
        """page.evaluate 抛异常（页面已关闭等）→ 视为未登录，不抛出"""
        page = MagicMock()
        page.evaluate.side_effect = Exception("page closed")
        self.assertFalse(crawl._is_logged_in(page))

    def test_empty_url_returns_false(self):
        """evaluate 返回空串 → 未登录"""
        page = _fake_page("")
        self.assertFalse(crawl._is_logged_in(page))


class MakeSessionTest(unittest.TestCase):
    """make_session 应把 cookie 写进 session.cookies（jar）而非 headers。"""

    def test_cookies_in_jar_not_headers(self):
        s = make_session("SUB=abc123; SUBP=def456")
        self.assertEqual(s.cookies.get("SUB"), "abc123")
        self.assertEqual(s.cookies.get("SUBP"), "def456")
        # headers 里不应有 Cookie 键（避免覆盖 jar 导致 Set-Cookie 丢失）
        self.assertNotIn("Cookie", s.headers)

    def test_cookies_without_domain_sent_cross_domain(self):
        """不绑定 domain 的 cookie 应能跨域发送（login.sina.com.cn 等 SSO 域）。"""
        s = make_session("SUB=abc123")
        # requests 在无 domain 时会将 cookie 发送给任意域
        prepared = s.prepare_request(requests.Request("GET", "https://login.sina.com.cn/"))
        self.assertIn("SUB=abc123", prepared.headers.get("Cookie", ""))

    def test_empty_cookie_parts_skipped(self):
        """空片段（如尾部多余的 '; '）不应导致异常"""
        s = make_session("SUB=abc; ")
        self.assertEqual(s.cookies.get("SUB"), "abc")

    def test_serialize_roundtrip(self):
        """_serialize_cookies 应能还原可解析的 cookie 字符串"""
        original = "SUB=abc123; SUBP=def456"
        s = make_session(original)
        serialized = _serialize_cookies(s)
        # 重建验证
        s2 = make_session(serialized)
        self.assertEqual(s2.cookies.get("SUB"), "abc123")
        self.assertEqual(s2.cookies.get("SUBP"), "def456")


class RenewCookieTest(unittest.TestCase):
    """renew_cookie 续期链测试：mock SSO 接口响应，验证链路逻辑。

    renew_cookie 内部用 make_session 创建独立临时 session 跑续期链，
    所以 mock 的是 weibo_im.crawler.make_session，让临时 session 的 .get
    走 fake 响应。
    """

    def _mock_session_get(self, responses):
        """返回一个 fake make_session，其返回的 session.get 走 responses 映射。"""
        def fake_make_session(cookie):
            s = requests.Session()
            s.cookies.set("SUB", "old_sub")
            s.cookies.set("SUBP", "old_subp")

            def fake_get(url, **kwargs):
                for key, resp in responses.items():
                    if key in url:
                        return resp
                return MagicMock(text="", headers={})
            s.get = fake_get
            return s
        return fake_make_session

    def _resp(self, text, cookie_updates=None):
        r = MagicMock()
        r.text = text
        r.headers = {}
        if cookie_updates:
            r.cookies = MagicMock()
            r.cookies.get = lambda name=None: cookie_updates.get(name)
        return r

    @patch("weibo_im.crawler.make_session")
    def test_renewal_chain_success(self, mock_make):
        """续期链全通（retcode:0 + arrURL）→ 返回 True"""
        crossdomain_resp = self._resp(
            'cb({"retcode":0,"arrURL":'
            '["https://passport.weibo.com/wbsso/crossdomain?action=login",'
            '"https://passport.weibo.cn/sso/crossdomain?action=login"]})'
        )
        mock_make.side_effect = self._mock_session_get({
            "updatetgt": self._resp('cb({"retcode":0})'),
            "crossdomain.php": crossdomain_resp,
            "passport.weibo": self._resp('cb({"retcode":0})'),
        })
        s = make_session("SUB=old; SUBP=old")
        self.assertTrue(renew_cookie(s))

    @patch("weibo_im.crawler.make_session")
    def test_renewal_no_arrurl_returns_false(self, mock_make):
        """crossdomain 未返回 arrURL → 返回 False"""
        mock_make.side_effect = self._mock_session_get({
            "updatetgt": self._resp('cb({"retcode":0})'),
            "crossdomain.php": self._resp('cb({"retcode":500})'),
        })
        s = make_session("SUB=old; SUBP=old")
        self.assertFalse(renew_cookie(s))

    @patch("weibo_im.crawler.make_session")
    def test_renewal_network_error_returns_false(self, mock_make):
        """网络异常 → 返回 False（不抛出，降级让后续请求触发 CookieExpiredError）"""
        def raise_error(url, **kwargs):
            raise requests.ConnectionError("network down")
        def fake_make(cookie):
            s = requests.Session()
            s.cookies.set("SUB", "old")
            s.get = raise_error
            return s
        mock_make.side_effect = fake_make
        s = make_session("SUB=old; SUBP=old")
        self.assertFalse(renew_cookie(s))


if __name__ == "__main__":
    unittest.main()
