from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

from capture_subtitles import read_cues
from parse_subtitles import Cue, load_cues, parse_json, parse_page_dump, save_cues


class CaptionTests(TestCase):
    def test_example_track(self):
        example = Path(__file__).resolve().parents[1] / "examples" / "demo.vtt"
        cues = load_cues(example, "s")
        self.assertEqual(cues[0], Cue(2000, 4500, "这是一段虚构的字幕。"))
        self.assertEqual(len(cues), 2)

    def test_json_with_explicit_units(self):
        cues = parse_json('{"items":[{"startMs":1500,"endMs":2100,"text":"示例"}]}', "s")
        self.assertEqual(cues, [Cue(1500, 2100, "示例")])

    def test_page_dump_ignores_surrounding_text(self):
        page = "演示页眉\n转写\n第一句\n00:02\n第二句\n00:04\n总字数：6个\n演示页脚\n00:06"
        self.assertEqual(parse_page_dump(page), [Cue(2000, None, "第一句"), Cue(4000, None, "第二句")])

    def test_capture_reads_only_platform_pages(self):
        replay = Mock(url="https://ylb.nwafu.edu.cn/demo")
        replay.evaluate.return_value = "转写\n示例\n00:01\n总字数：2个"
        other = Mock(url="https://example.test")
        self.assertEqual(read_cues([replay, other]), [Cue(1000, None, "示例")])
        other.evaluate.assert_not_called()

    def test_save_never_replaces_an_existing_file(self):
        with TemporaryDirectory() as folder:
            target = Path(folder) / "outputs" / "demo.txt"
            first = save_cues([Cue(1000, None, "第一句")], target)
            second = save_cues([Cue(2000, None, "第二句")], target)
            self.assertEqual(first.read_text(encoding="utf-8"), "[00:00:01.000] 第一句\n")
            self.assertEqual(second.name, "demo_002.txt")
