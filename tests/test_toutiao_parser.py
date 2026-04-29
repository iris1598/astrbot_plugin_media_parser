import asyncio
import unittest

from core.parser.platform.toutiao import ToutiaoParser


def build_weitoutiao_state():
    return {
        "articleInfo": {
            "thread": {
                "threadBase": {
                    "title": "Thread title",
                    "content": "Thread plain content",
                    "richContent": "Thread <b>rich</b><br>content",
                    "createTime": 1756091176,
                    "user": {
                        "info": {
                            "name": "Thread author",
                            "userId": 12345,
                        }
                    },
                    "largeImageList": [
                        {
                            "url": "https://example.com/large.jpg",
                            "urlList": [
                                {"url": "https://example.com/large-backup.jpg"}
                            ],
                        }
                    ],
                }
            }
        }
    }


class ToutiaoParserTest(unittest.TestCase):
    def test_build_article_metadata_reads_weitoutiao_thread_base(self):
        parser = ToutiaoParser(article_image_refreshes=1)

        metadata = parser._build_article_metadata_from_state(
            source_url="https://www.toutiao.com/w/1841395061602304/",
            page_url="https://m.toutiao.com/w/1841395061602304/",
            state=build_weitoutiao_state(),
        )

        self.assertEqual(metadata["title"], "Thread title")
        self.assertEqual(metadata["author"], "Thread author(uid:12345)")
        self.assertEqual(metadata["desc"], "Thread rich\ncontent")
        self.assertEqual(metadata["timestamp"], parser._format_timestamp(1756091176))
        self.assertEqual(
            metadata["image_urls"],
            [[
                "https://example.com/large.jpg",
                "https://example.com/large-backup.jpg",
            ]],
        )

    def test_collect_article_image_candidates_reads_thread_image_lists(self):
        parser = ToutiaoParser(article_image_refreshes=1)

        image_urls = asyncio.run(
            parser._collect_article_image_candidates(
                session=None,
                page_url="https://m.toutiao.com/w/1841395061602304/",
                state=build_weitoutiao_state(),
            )
        )

        self.assertEqual(
            image_urls,
            [[
                "https://example.com/large.jpg",
                "https://example.com/large-backup.jpg",
            ]],
        )


if __name__ == "__main__":
    unittest.main()
