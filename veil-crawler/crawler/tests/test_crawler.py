"""실제 로컬 HTTP 페이지 수집과 오류·정규화 검증. 외부 접속 없음."""
import contextlib
import io
import json
import logging
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import requests
from bs4 import BeautifulSoup
import config
from main import main
from crawler.fetcher import Fetcher, FetchError
from crawler.pagination import page_url, next_link
from crawler.parser import parse_page, parse_article
from models.post import RawPost
from processing.normalizer import parse_like_count, parse_count, normalize_comment, normalize_post, normalize_time
from samples.mock_site import Handler


class NormalizerTests(unittest.TestCase):
    def test_like_and_retweet_formats(self):
        for value, expected in (("153",153),("1,253",1253),("1.2K",1200),("2.3K",2300),("1M",1000000),("1.5k",1500),(None,0)):
            with self.subTest(value=value):
                self.assertEqual(parse_like_count(value), expected)
                self.assertEqual(parse_count(value, "재게시"), expected)
                self.assertIsInstance(parse_count(value), int)

    def test_invalid_time_and_counts(self):
        with self.assertLogs("crawler.normalizer",level="WARNING"):
            self.assertEqual(parse_like_count("unknown"),0)
            self.assertEqual(parse_count("-3", "재게시"),0)
            self.assertIsNone(normalize_time("yesterday"))

    def test_defaults(self):
        with self.assertLogs("crawler.normalizer",level="WARNING"):
            post = normalize_post(RawPost(), "http://localhost/posts")
        self.assertEqual(post.author_id, "")
        self.assertEqual(post.comment, "false")
        self.assertEqual(post.text, "")
        self.assertEqual(post.retweet_count, 0)
        self.assertEqual(post.like_count, 0)
        self.assertIsNone(post.created_at)

    def test_comment_is_a_string_and_not_a_count(self):
        for value, expected in ((None,"false"),(False,"false"),(True,"true"),(" TRUE ","true"),("0","false"),("1","true")):
            self.assertEqual(normalize_comment(value),expected)
            self.assertIsInstance(normalize_comment(value),str)
        with self.assertLogs("crawler.normalizer",level="WARNING"):
            self.assertEqual(normalize_comment("72"),"false")

    def test_timezones(self):
        self.assertEqual(normalize_time("2026-10-10 15:30:00"),"2026-10-10T15:30:00+09:00")
        self.assertEqual(normalize_time("2026-10-10T07:00:00Z"),"2026-10-10T07:00:00+00:00")
        self.assertEqual(normalize_time("2026-10-10"),"2026-10-10")

    def test_author_id_is_not_replaced_with_an_invented_id(self):
        post=normalize_post(RawPost(author_id=" observer_01 ",text=" 첫 줄\n  두 번째 줄 ",retweet_count="2.3K",like_count="12"),"http://localhost")
        self.assertEqual(post.author_id,"observer_01")
        self.assertEqual(post.text,"첫 줄 두 번째 줄")
        self.assertEqual(post.retweet_count,2300)
        self.assertEqual(post.like_count,12)


class ParserTests(unittest.TestCase):
    def test_inline_text_and_paragraph_breaks(self):
        html='<article class="post" data-author-id="u"><div class="post-content"><b>새로운</b>책<br>다음<p>마지막 문단</p></div></article>'
        result=parse_page(html,config.SELECTORS,config.ATTRIBUTES,config.POST_ID_ATTRIBUTES,config.REMOVE_TEXT_SELECTORS,config.TEXT_BREAK_SELECTORS)
        self.assertEqual(normalize_post(result.posts[0],"http://localhost").text,"새로운책 다음 마지막 문단")

    def test_custom_selectors_and_attributes(self):
        selectors={**config.SELECTORS,"post":"div.card","author_id":".writer","text":".body","like_count":None,"retweet_count":".reposts","comment":None}
        attributes={**config.ATTRIBUTES,"author_id":None,"like_count":"data-likes","retweet_count":None}
        html='<div class="card" data-likes="2.3K" data-comment="true"><span class="reposts">1.2K</span><b class="writer">test</b><div class="body">안녕 <b>세계</b><script>exclude()</script></div><img class="photo" data-src="/photo.jpg"></div>'
        parsed=parse_page(html,selectors,attributes,(),config.REMOVE_TEXT_SELECTORS)
        self.assertEqual(parsed.posts[0].author_id,"test")
        self.assertEqual(parsed.posts[0].text,"안녕 세계")
        self.assertEqual(parsed.posts[0].like_count,"2.3K")
        self.assertEqual(parsed.posts[0].retweet_count,"1.2K")
        self.assertEqual(parsed.posts[0].comment,"true")

    def test_one_broken_post_does_not_stop_the_next(self):
        html='<article class="post" id="bad"></article><article class="post" id="good" data-author-id="ok"></article>'
        def parse_or_fail(article,*args):
            if article.get("id")=="bad":
                raise ValueError("injected parser failure")
            return parse_article(article,*args)
        with patch("crawler.parser.parse_article",side_effect=parse_or_fail),self.assertLogs("crawler.parser",level="ERROR"):
            result=parse_page(html,config.SELECTORS,config.ATTRIBUTES,config.POST_ID_ATTRIBUTES,config.REMOVE_TEXT_SELECTORS)
        self.assertEqual(result.found,2)
        self.assertEqual(len(result.posts),1)
        self.assertEqual(result.posts[0].author_id,"ok")


class PaginationTests(unittest.TestCase):
    def test_query_preserves_other_parameters(self):
        self.assertEqual(page_url("http://localhost/posts?topic=book&page=8",2),"http://localhost/posts?topic=book&page=2")

    def test_next_relative_and_external_links(self):
        soup=BeautifulSoup('<a class="next" href="?page=2">next</a>',"html.parser")
        self.assertEqual(next_link(soup,"http://localhost/posts?page=1",".next"),"http://localhost/posts?page=2")
        soup.a["href"]="https://elsewhere.example/posts"
        with self.assertLogs("crawler.pagination",level="WARNING"):
            self.assertIsNone(next_link(soup,"http://localhost/posts",".next"))


def response(status, url="http://localhost/posts", headers=None):
    value=requests.Response()
    value.status_code=status
    value.url=url
    value.headers.update(headers or {})
    value._content=b'<html><p>ok</p></html>'
    value._content_consumed=True
    value.encoding="utf-8"
    return value


class FetcherTests(unittest.TestCase):
    def test_retry_then_success(self):
        fetcher=Fetcher("test",1,retries=2,backoff=0)
        try:
            with patch.object(fetcher.session,"get",side_effect=[response(503),response(200)]) as get,self.assertLogs("crawler.fetcher",level="WARNING"):
                self.assertIn("ok",fetcher.fetch("http://localhost/posts").html)
            self.assertEqual(get.call_count,2)
        finally:
            fetcher.close()

    def test_403_does_not_retry(self):
        fetcher=Fetcher("test",1)
        try:
            with patch.object(fetcher.session,"get",return_value=response(403)) as get:
                with self.assertRaises(FetchError):fetcher.fetch("http://localhost/posts")
                self.assertEqual(get.call_count,1)
        finally:
            fetcher.close()

    def test_long_retry_after_stops(self):
        fetcher=Fetcher("test",1,max_retry_wait=1)
        try:
            with patch.object(fetcher.session,"get",return_value=response(429,headers={"Retry-After":"120"})) as get:
                with self.assertRaises(FetchError):fetcher.fetch("http://localhost/posts")
                self.assertEqual(get.call_count,1)
        finally:
            fetcher.close()


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.url=f"http://127.0.0.1:{self.server.server_port}/posts?page=1"
        self.temp=tempfile.TemporaryDirectory()
        self.output=Path(self.temp.name)/"raw_posts.jsonl"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def test_http_query_to_jsonl(self):
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):
            code=main(["--url",self.url,"--pagination","query","--output",str(self.output)])
        lines=self.output.read_text(encoding="utf-8").splitlines()
        self.assertEqual(code,0)
        self.assertEqual(len(lines),8)
        posts=[json.loads(line) for line in lines]
        expected={"author_id","comment","created_at","text","retweet_count","like_count"}
        self.assertTrue(all(set(post)==expected and type(post["like_count"]) is int for post in posts))
        self.assertEqual(posts[0]["text"],"지역 도서관에 새로운 책이 입고되었습니다. 이번 주에 방문할 예정입니다.")
        self.assertEqual([post["like_count"] for post in posts],[153,1253,1200,2300,1000000,0,0,0])
        self.assertEqual(posts[0]["retweet_count"],3)
        self.assertTrue(all(type(post["retweet_count"]) is int and post["comment"] == "false" for post in posts))
        self.assertEqual(posts[5]["author_id"],"")
        self.assertIsNone(posts[6]["created_at"])
        self.assertIn("Pages crawled : 3",stream.getvalue())
        self.assertIn("Warnings      : 3",stream.getvalue())
        self.assertIn("Errors        : 0",stream.getvalue())

    def test_next_mode(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--url",self.url,"--pagination","next","--output",str(self.output)]),0)
        self.assertEqual(len(self.output.read_text().splitlines()),8)

    def test_default_runs_keep_separate_kst_timestamped_files(self):
        base=Path(self.temp.name)/"raw_posts.jsonl"
        base.write_text("previous result\n")
        with patch.object(config,"OUTPUT_PATH",base):
            first=config.timestamped_output_path(datetime(2026,10,10,17,15,30,123456,tzinfo=timezone.utc))
            second=config.timestamped_output_path(datetime(2026,10,10,17,15,30,654321,tzinfo=timezone.utc))
        self.assertEqual(first.name,"raw_posts_20261011_021530_123456.jsonl")
        with patch.object(config,"timestamped_output_path",side_effect=[first,second,first]),contextlib.redirect_stdout(io.StringIO()):
            for _ in range(2):
                self.assertEqual(main(["--url",self.url,"--pagination","none"]),0)
            previous=first.read_bytes()
            self.assertEqual(main(["--url",self.url,"--pagination","none"]),1)
        self.assertEqual(first.read_bytes(),previous)
        self.assertEqual(len(first.read_text().splitlines()),4)
        self.assertEqual(len(second.read_text().splitlines()),4)
        self.assertEqual(base.read_text(),"previous result\n")

    def test_one_normalization_error_keeps_other_posts(self):
        from processing.normalizer import normalize_post as real_normalize
        def normalize_or_fail(raw,*args):
            if raw.post_id=="POST_003":raise ValueError("injected normalization failure")
            return real_normalize(raw,*args)
        stream=io.StringIO()
        with patch("main.normalize_post",side_effect=normalize_or_fail),contextlib.redirect_stdout(stream):
            code=main(["--url",self.url,"--pagination","query","--output",str(self.output)])
        self.assertEqual(code,1)
        self.assertEqual(len(self.output.read_text().splitlines()),7)
        self.assertIn("Errors        : 1",stream.getvalue())


if __name__=="__main__":
    unittest.main()
