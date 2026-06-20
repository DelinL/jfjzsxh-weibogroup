"""_is_logged_in 登录态判据测试

验证扫码登录态判定逻辑：api.weibo.com/chat 未登录时 URL 为 #/，
扫码登录成功后 hash 路由跳转为 #/chat。
"""
import unittest
from unittest.mock import MagicMock

import crawl


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


if __name__ == "__main__":
    unittest.main()
