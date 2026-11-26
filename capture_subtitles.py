"""Export the visible transcription from an open NWAFU classroom replay."""

import argparse
from datetime import datetime
from pathlib import Path
from queue import Empty, SimpleQueue
import sys
from threading import Thread
from urllib.parse import urlsplit

from parse_subtitles import OUTPUT_DIR, parse_page_dump, save_cues


ENTRY_URL = "https://ylb.nwafu.edu.cn/TeachingCenterStudentWeb/index.html"
PLATFORM_HOST = urlsplit(ENTRY_URL).hostname
READ_TRANSCRIPTION = r"""() => {
    if (document.visibilityState !== "visible" || !document.body) return "";
    const lines = document.body.innerText.split(/\r?\n/).map(line => line.trim());
    const start = lines.indexOf("转写");
    if (start < 0) return "";
    const end = lines.findIndex((line, index) =>
        index > start && /^总字数[：:]\s*\d+\s*个$/.test(line));
    return end > start ? lines.slice(start, end + 1).join("\n") : "";
}"""


def read_commands(commands):
    for line in sys.stdin:
        command = line.strip().lower()
        commands.put(command or "d")
        if command == "q":
            return
    commands.put("q")


def read_cues(pages):
    for page in reversed(pages):
        location = urlsplit(page.url)
        if location.scheme != "https" or location.hostname != PLATFORM_HOST:
            continue
        text = page.evaluate(READ_TRANSCRIPTION)
        if text:
            return parse_page_dump(text)
    return []


def save_replay(pages, output_dir):
    cues = read_cues(pages)
    if not cues:
        print("没有找到带时间戳的转写。请切到回放标签页，等「转写」和总字数出现，再按回车。", flush=True)
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = save_cues(cues, output_dir / f"captions_{stamp}.txt")
    print(f"已保存 {len(cues):,} 条转写 → {target}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="把西农云课堂回放上的转写保存为 TXT。")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="保存目录，默认 outputs/")
    args = parser.parse_args()
    try:
        from playwright.sync_api import Error, sync_playwright
    except ModuleNotFoundError:
        parser.exit(1, "请先安装 Playwright。Windows 可以双击 start.cmd。\n")

    commands = SimpleQueue()
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=False)
        except Error:
            parser.exit(1, "无法启动 Chromium。请先执行 python -m playwright install --no-shell chromium。\n")

        try:
            context = browser.new_context(accept_downloads=False)
            page = context.new_page()
            try:
                page.goto(ENTRY_URL, wait_until="domcontentloaded", timeout=20_000)
            except Error:
                print(f"暂时打不开课堂入口。请在启动的浏览器中打开 {ENTRY_URL}。", flush=True)
            print("在打开的浏览器中登录 → 课堂实录 → 打开回放并等待转写加载。", flush=True)
            print("回到此窗口按回车保存，或输入 q 再按回车退出。", flush=True)
            Thread(target=read_commands, args=(commands,), daemon=True).start()

            while browser.is_connected() and context.pages:
                try:
                    command = commands.get_nowait()
                except Empty:
                    command = None
                if command == "q":
                    break
                if command == "d":
                    try:
                        save_replay(context.pages, args.output_dir.resolve())
                    except Error:
                        print("页面正在切换，请等回放加载后再按回车。", flush=True)
                    except OSError as error:
                        print(f"保存失败，请检查输出目录是否可写。{error}", flush=True)
                elif command:
                    print("按回车保存，或输入 q 再按回车退出。", flush=True)
                try:
                    context.pages[-1].wait_for_timeout(150)
                except (Error, IndexError):
                    if not browser.is_connected() or not context.pages:
                        break
        finally:
            if browser.is_connected():
                browser.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("已退出。")
