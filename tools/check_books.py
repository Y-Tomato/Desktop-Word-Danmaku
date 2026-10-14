# -*- coding: utf-8 -*-
r"""
词书体检 —— 一次跑完 books\ 下所有词书，列出会被弹幕**直接暴露**出来的数据问题。

用法：
    python tools\check_books.py                # 检查 books\ 下所有词书
    python tools\check_books.py 四级高频        # 只检查名字里含这个的书
    python tools\check_books.py --max-text 30  # 换个“文案太长”的阈值

退出码：0 = 干净，1 = 有问题（提交前跑一遍，以后挂 CI 也行）。

为什么需要它：2026 那次改动就是靠它发现 acquire 在 4 本词书里全都解析错的
（数据里词性后面跟了两个空格，于是 v. 掉出去变成了一个义项）。这类“个别词”的
问题肉眼看弹幕基本发现不了 —— 得跑完全库才知道。
"""
import argparse
import os
import re
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import danmaku  # noqa: E402   （sys.path 处理好之后再 import）

# 义项里混进来的词性标记，如 "v." —— acquire 那种解析事故的指纹
POS_TOKEN_RE = re.compile(r"^[a-zA-Z]{1,6}\.$")
# 生成文案的字数阈值：字幕式阅读，超过这个数基本来不及看完
DEFAULT_MAX_TEXT = 40


def check_book(path, display, max_text):
    """返回 [(级别, 条目, 说明), ...]；级别是 问题 / 提示。"""
    issues = []
    words = danmaku.load_words(path)
    if not words:
        return issues

    seen = {}
    for w in words:
        name = w["word"]
        raw = w.get("mean_cn") or ""
        seen.setdefault(name.lower(), []).append(name)

        senses = w["senses"]
        if not senses or not senses[0][0]:
            issues.append(("问题", name, "解析不出词性：%r" % raw[:60]))
        for _pos, items in senses:
            for it in items:
                if POS_TOKEN_RE.match(it):
                    issues.append(("问题", name,
                                   "义项里混进了词性标记 %r（词性分块没切开）" % it))
        if not (w.get("accent") or "").strip():
            issues.append(("提示", name, "没有音标，悬停信息框会是空的"))

        text = danmaku.build_text(w, danmaku.DEFAULT_CONFIG)
        body = text[len(name):].strip()
        if not body:
            issues.append(("问题", name, "剥掉括号后没有释义了：%r" % raw[:60]))
        elif len(text) > max_text:
            issues.append(("提示", name, "弹幕文案 %d 字，读不完：%s"
                           % (len(text), text[:max_text] + "…")))

    for key, names in seen.items():
        if len(names) > 1:
            issues.append(("提示", names[0], "重复词 %d 次" % len(names)))
    return issues


def main():
    ap = argparse.ArgumentParser(description="词书体检")
    ap.add_argument("book", nargs="*", help="只看名字里含这些字样的词书（默认全部）")
    ap.add_argument("--max-text", type=int, default=DEFAULT_MAX_TEXT,
                    help="弹幕文案超过几个字就提示（默认 %d）" % DEFAULT_MAX_TEXT)
    ap.add_argument("--verbose", action="store_true", help="把“提示”级也逐条列出来")
    args = ap.parse_args()

    books = danmaku.list_books()
    if args.book:
        books = [(d, p) for d, p in books
                 if any(k in d or k in os.path.basename(p) for k in args.book)]
    if not books:
        print("books\\ 里没有匹配的词书")
        return 1

    total_problems = 0
    for display, path in books:
        issues = check_book(path, display, args.max_text)
        hard = [i for i in issues if i[0] == "问题"]
        soft = [i for i in issues if i[0] == "提示"]
        total_problems += len(hard)
        print("\n=== %s ===" % display)
        print("    问题 %d · 提示 %d" % (len(hard), len(soft)))
        for level, name, msg in hard:
            print("    [%s] %-18s %s" % (level, name, msg))
        if args.verbose:
            for level, name, msg in soft:
                print("    [%s] %-18s %s" % (level, name, msg))
        elif soft:
            # 提示太多就只报计数，用 --verbose 看细节
            head = soft[:5]
            for level, name, msg in head:
                print("    [%s] %-18s %s" % (level, name, msg))
            if len(soft) > len(head):
                print("    … 另有 %d 条提示（--verbose 看全部）" % (len(soft) - len(head)))

    print("\n共 %d 条问题。" % total_problems)
    return 1 if total_problems else 0


if __name__ == "__main__":
    sys.exit(main())
