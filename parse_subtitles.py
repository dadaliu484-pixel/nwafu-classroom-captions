"""Read a local subtitle file and write one timestamped cue per line."""

import argparse
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import unescape
from itertools import count
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
EXTENSIONS = {".json", ".vtt", ".srt"}
CLOCK = r"(?:\d{1,}:)?[0-5]?\d:[0-5]\d(?:[.,]\d{1,3})?"
TIMING = re.compile(rf"^\s*(?P<start>{CLOCK})\s*-->\s*(?P<end>{CLOCK})(?:\s.*)?$")
PAGE_FOOTER = re.compile(r"总字数[：:]\s*\d+\s*个")
BLOCK_BREAK = re.compile(r"\n[ \t]*\n")
CUE_TAG = re.compile(rf"</?[a-zA-Z][^>]*>|<{CLOCK}>")
LINE_BREAK_TAG = re.compile(r"<br\s*/?>", re.IGNORECASE)
TEXT_FIELDS = (
    "text", "content", "subtitletext", "captiontext", "sentencetext", "transcription",
    "transcript", "subtitle", "caption", "sentence", "utterance", "line", "onebest",
)
START_FIELDS = ("start", "starttime", "begintime", "begin", "from", "offset", "timestamp", "ts", "bg")
END_FIELDS = ("end", "endtime", "stoptime", "stop", "to", "te", "ed")


@dataclass(frozen=True)
class Cue:
    start: int
    end: int | None
    text: str

    def render(self):
        axis = format_clock(self.start)
        if self.end is not None:
            axis += f" --> {format_clock(self.end)}"
        return f"[{axis}] {self.text}"


def read_text(path):
    body = path.read_bytes()
    if body.startswith((b"\xff\xfe", b"\xfe\xff")):
        return body.decode("utf-16")
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return body.decode("gb18030")


def clean_text(value):
    value = LINE_BREAK_TAG.sub(" ", value)
    return " ".join(unescape(CUE_TAG.sub("", value)).split())


def format_clock(milliseconds):
    seconds, milliseconds = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def parse_time(value, unit):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    value = str(value).strip().replace(",", ".")
    try:
        if re.fullmatch(CLOCK, value):
            parts = value.split(":")
            seconds = Decimal(parts[-1]) + 60 * int(parts[-2])
            if len(parts) == 3:
                seconds += 3600 * int(parts[0])
            milliseconds = seconds * 1000
        else:
            milliseconds = Decimal(value) * (1000 if unit == "s" else 1)
        if not milliseconds.is_finite() or milliseconds < 0:
            return None
        return int(milliseconds.to_integral_value(rounding=ROUND_HALF_UP))
    except (InvalidOperation, OverflowError, ValueError):
        return None


def parse_track(value):
    cues = []
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    for block in BLOCK_BREAK.split(value):
        lines = block.splitlines()
        if not lines or lines[0].split(maxsplit=1)[:1] in (["NOTE"], ["STYLE"], ["REGION"]):
            continue
        # A cue may start with a WebVTT identifier or an SRT sequence number.
        for index, line in enumerate(lines[:2]):
            timing = TIMING.match(line)
            if timing:
                text = clean_text(" ".join(lines[index + 1:]))
                start = parse_time(timing["start"], "s")
                end = parse_time(timing["end"], "s")
                if text and start is not None and end is not None and start <= end:
                    cues.append(Cue(start, end, text))
                break
    return cues


def json_time(fields, keys, unit):
    # Explicit units take precedence over the CLI default.
    for suffix, field_unit in (("milliseconds", "ms"), ("ms", "ms"), ("seconds", "s"), ("sec", "s"), ("", unit)):
        for key in keys:
            timestamp = parse_time(fields.get(key + suffix), field_unit)
            if timestamp is not None:
                return timestamp
    return None


def parse_json(value, unit):
    stack = [json.loads(value, parse_float=Decimal)]
    cues = []
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            stack.extend(reversed(item))
        elif isinstance(item, dict):
            fields = {re.sub(r"[^a-z0-9]", "", key.lower()): val for key, val in item.items()}
            start = json_time(fields, START_FIELDS, unit)
            if start is not None:
                for key in TEXT_FIELDS:
                    raw_text = fields.get(key)
                    text = clean_text(raw_text) if isinstance(raw_text, str) else ""
                    if text:
                        end = json_time(fields, END_FIELDS, unit)
                        if end is None or start <= end:
                            cues.append(Cue(start, end, text))
                        break
            stack.extend(reversed(item.values()))
    return cues


def parse_page_dump(value):
    lines = [line.strip() for line in value.splitlines()]
    try:
        start_index = lines.index("转写") + 1
    except ValueError:
        return []

    cues = []
    text_lines = []
    for line in lines[start_index:]:
        if not line:
            continue
        if PAGE_FOOTER.fullmatch(line):
            break
        if re.fullmatch(CLOCK, line):
            timestamp = parse_time(line, "s")
            if text_lines and timestamp is not None:
                cues.append(Cue(timestamp, None, " ".join(text_lines)))
            text_lines.clear()
        else:
            text_lines.append(line)
    return cues


def load_cues(path, unit):
    value = read_text(path)
    if path.suffix.lower() == ".json":
        return parse_json(value, unit)
    if path.suffix.lower() == ".txt":
        return parse_page_dump(value)
    return parse_track(value)


def save_cues(cues, base):
    base.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(f"{cue.render()}\n" for cue in cues)
    for number in count(1):
        target = base if number == 1 else base.with_stem(f"{base.stem}_{number:03d}")
        try:
            with target.open("x", encoding="utf-8") as file:
                file.write(content)
            return target
        except FileExistsError:
            continue


def main():
    parser = argparse.ArgumentParser(description="将本地字幕转换为带时间轴的纯文本。")
    parser.add_argument(
        "source", type=Path, help="本地 .vtt、.srt、.json 或转写页面 .txt 文件。",
    )
    parser.add_argument("-o", "--output", type=Path, help="输出文件，默认保存到 outputs/。")
    parser.add_argument("--json-unit", default="s", choices=("s", "ms"), help="JSON 无单位数字的时间单位，默认 s。")
    args = parser.parse_args()
    source = args.source
    if source.suffix.lower() not in EXTENSIONS | {".txt"}:
        parser.error("请输入 .json、.vtt、.srt 或转写页面 .txt 文件。")
    try:
        cues = load_cues(source, args.json_unit)
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        parser.exit(1, f"读取失败。{error}\n")
    if not cues:
        parser.exit(1, "未找到可识别的带时间轴字幕。\n")
    if source.suffix.lower() != ".txt":
        cues = sorted(dict.fromkeys(cues), key=lambda cue: cue.start)
    output = args.output or OUTPUT_DIR / f"{source.stem}_captions.txt"
    try:
        target = save_cues(cues, output)
    except OSError as error:
        parser.exit(1, f"保存失败。{error}\n")
    print(f"已保存 {len(cues):,} 条转写 → {target.resolve()}")


if __name__ == "__main__":
    main()
