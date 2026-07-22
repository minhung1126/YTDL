import unittest

from YTDL import Config


class YouTubeUrlParsingTests(unittest.TestCase):
    def test_accepts_supported_single_content_urls(self):
        urls = (
            "https://www.youtube.com/watch?v=KZjViXrAycM",
            "https://youtube.com/watch?feature=share&v=KZjViXrAycM",
            "m.youtube.com/watch?v=KZjViXrAycM",
            "https://youtu.be/KZjViXrAycM?si=share",
            "https://youtube.com/shorts/KZjViXrAycM",
            "https://youtube.com/live/KZjViXrAycM?feature=share",
            "https://youtube.com/embed/KZjViXrAycM",
            "https://youtube.com/v/KZjViXrAycM",
            "https://www.youtube-nocookie.com/embed/KZjViXrAycM",
            "https://music.youtube.com/watch?v=KZjViXrAycM",
            "https://youtube.com/clip/UgkxExampleClipId",
        )

        for url in urls:
            with self.subTest(url=url):
                self.assertTrue(Config.is_youtube_url(url))
                self.assertFalse(Config.is_playlist_or_channel_url(url))

    def test_accepts_supported_playlist_and_channel_urls(self):
        urls = (
            "https://www.youtube.com/playlist?list=PLexample",
            "https://music.youtube.com/playlist?list=PLexample",
            "https://youtube.com/channel/UCexample",
            "https://youtube.com/channel/UCexample/videos",
            "https://youtube.com/c/example/streams",
            "https://youtube.com/user/example/shorts",
            "https://youtube.com/@example",
            "https://youtube.com/@example/live",
        )

        for url in urls:
            with self.subTest(url=url):
                self.assertTrue(Config.is_youtube_url(url))
                self.assertTrue(Config.is_playlist_or_channel_url(url))

    def test_rejects_unsupported_or_malformed_urls(self):
        urls = (
            "https://youtube.com/not-a-video",
            "https://youtube.com/results?search_query=test",
            "https://youtube.com/watch?list=PLexample",
            "https://youtube.com/redirect?event=video_description",
            "https://youtube-nocookie.com/watch?v=KZjViXrAycM",
            "https://example.com/watch?v=KZjViXrAycM",
            "ftp://youtube.com/watch?v=KZjViXrAycM",
        )

        for url in urls:
            with self.subTest(url=url):
                self.assertFalse(Config.is_youtube_url(url))
                self.assertFalse(Config.is_playlist_or_channel_url(url))

    def test_extracts_supported_urls_from_clipboard_text(self):
        clipboard_text = (
            "Watch https://youtu.be/KZjViXrAycM?si=share, then "
            "https://youtube.com/@example/videos. Ignore "
            "https://example.com/watch?v=KZjViXrAycM and "
            "https://notyoutube.com/watch?v=KZjViXrAycM."
        )

        self.assertEqual(
            Config.extract_youtube_urls(clipboard_text),
            [
                "https://youtu.be/KZjViXrAycM?si=share",
                "https://youtube.com/@example/videos",
            ],
        )


if __name__ == "__main__":
    unittest.main()
