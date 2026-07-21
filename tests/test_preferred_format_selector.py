import json
import os
import tempfile
import unittest

from YTDL import PreferredFormatSelector, Video


def video(format_id, codec, height, fps=60, dynamic_range="SDR", protocol="https"):
    return {
        "format_id": format_id,
        "vcodec": codec,
        "acodec": "none",
        "width": height * 16 // 9,
        "height": height,
        "fps": fps,
        "dynamic_range": dynamic_range,
        "protocol": protocol,
    }


def audio(format_id, codec, ext, abr=128, protocol="https"):
    return {
        "format_id": format_id,
        "vcodec": "none",
        "acodec": codec,
        "ext": ext,
        "audio_channels": 2,
        "asr": 48000,
        "abr": abr,
        "protocol": protocol,
    }


class PreferredFormatSelectorTests(unittest.TestCase):
    def setUp(self):
        self.opus = audio("251", "opus", "webm")
        self.m4a = audio("140", "mp4a.40.2", "m4a")

    def test_resolution_beats_codec_family(self):
        formats = [
            video("303", "vp9", 1080),
            video("299", "avc1.64002a", 2160),
            video("400", "av01.0.12M.08", 1440),
            self.opus,
            self.m4a,
        ]

        self.assertEqual(PreferredFormatSelector.select(formats), "299+140")

    def test_fps_beats_codec_family_within_the_same_resolution(self):
        formats = [
            video("303", "vp9", 2160, fps=30),
            video("401", "av01.0.13M.08", 2160, fps=60),
            self.opus,
        ]

        self.assertEqual(PreferredFormatSelector.select(formats), "401+251")

    def test_hdr_beats_codec_family_within_same_resolution_and_fps(self):
        formats = [
            video("303", "vp9", 2160, dynamic_range="SDR"),
            video("299", "avc1.64002a", 2160, dynamic_range="HDR10"),
            self.opus,
            self.m4a,
        ]

        self.assertEqual(PreferredFormatSelector.select(formats), "299+140")

    def test_codec_family_order_applies_after_visual_properties_tie(self):
        formats = [
            video("315", "vp9", 2160),
            video("299", "avc1.64002a", 2160),
            video("401", "av01.0.13M.08", 2160),
            self.opus,
            self.m4a,
        ]

        self.assertEqual(PreferredFormatSelector.select(formats), "315+251")

    def test_https_beats_m3u8_for_matching_vp9_formats(self):
        # These values mirror the user's 4K60 YouTube listing: 628 is HLS
        # VP09, whereas 315 is direct HTTPS VP9.
        formats = [
            video("628", "vp09.00.51.08", 2160, protocol="m3u8"),
            video("315", "vp9", 2160, protocol="https"),
            video("401", "av01.0.13M.08", 2160),
            self.opus,
        ]

        self.assertEqual(PreferredFormatSelector.select(formats), "315+251")

    def test_non_drc_audio_beats_a_higher_bitrate_drc_track(self):
        formats = [
            video("315", "vp9", 2160),
            audio("251-drc", "opus", "webm", abr=128),
            audio("251", "opus", "webm", abr=127),
        ]

        self.assertEqual(PreferredFormatSelector.select(formats), "315+251")

    def test_codec_policy_is_consistent_across_common_resolutions(self):
        for height in (144, 360, 720, 1080, 1440, 2160):
            with self.subTest(height=height):
                formats = [
                    video(f"vp9-{height}", "vp9", height),
                    video(f"avc-{height}", "avc1.64002a", height),
                    video(f"av1-{height}", "av01.0.13M.08", height),
                    self.opus,
                    self.m4a,
                ]
                self.assertEqual(
                    PreferredFormatSelector.select(formats),
                    f"vp9-{height}+251",
                )

    def test_requires_the_family_audio_pairing(self):
        formats = [
            video("315", "vp9", 2160),
            video("299", "avc1.64002a", 2160),
            self.m4a,
        ]

        self.assertEqual(PreferredFormatSelector.select(formats), "299+140")

    def test_returns_none_without_a_supported_matched_pair(self):
        formats = [
            video("299", "avc1.64002a", 2160),
            audio("251", "opus", "webm"),
        ]

        self.assertIsNone(PreferredFormatSelector.select(formats))

    def test_video_download_arguments_use_the_selected_format_ids(self):
        metadata = {
            "webpage_url": "https://www.youtube.com/watch?v=test-video",
            "title": "Test video",
            "formats": [
                video("315", "vp9", 2160),
                video("299", "avc1.64002a", 2160),
                self.opus,
                self.m4a,
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False) as handle:
            json.dump(metadata, handle)
            meta_path = handle.name
        try:
            args = Video(meta_path).get_download_args()
        finally:
            os.remove(meta_path)

        format_index = args.index("-f")
        self.assertEqual(args[format_index + 1], "315+251")
        self.assertNotIn("-S", args)


if __name__ == "__main__":
    unittest.main()
