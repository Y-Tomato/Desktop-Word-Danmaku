# -*- coding: utf-8 -*-
r"""
把 books\ 里每个单词的读音抓下来，存进 audio\。

用法：
    python tools\fetch_audio.py                 # 抓；已经有且合法的会跳过，可反复跑
    python tools\fetch_audio.py --force         # 全部重抓
    python tools\fetch_audio.py --type 1        # 换英式（默认 2 = 美式）
    python tools\fetch_audio.py --only-failed   # 只重跑 audio\_failed.txt 里的词
    python tools\fetch_audio.py --limit 20      # 先抓 20 条看看

几点说明：
  · 词表来自 books\ 下所有 csv，按出现顺序去重；文件名就是单词本身；
  · 先写 .part 再改名 —— 半截文件不会被当成"下好了"；
  · 音源是有道词典的 dictvoice 接口（网页上那个小喇叭）。同一个接口会吐**不止一种
    容器**：大多数 mp3，另有一些词只有 wav（RIFF），所以我们按文件头认格式、
    各自存成对应后缀，最后由 tools\normalize_audio.py 统一转成同一种 mp3；
  · 某个词要是主口音整个抓不到，会自动换另一种口音兜底（代价：那一小部分词的
    读音口音和其余的略不一致）；
  · 失败清单落在 audio\_failed.txt，下次跑（或 --only-failed）会自动带上。
"""
import argparse
import concurrent.futures
import csv
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS_DIR = os.path.join(APP_DIR, "books")
AUDIO_DIR = os.path.join(APP_DIR, "audio")
FAILED_LIST = os.path.join(AUDIO_DIR, "_failed.txt")

API = "https://dict.youdao.com/dictvoice?audio=%s&type=%d"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 20          # 单条超时（秒）
TRIES = 4             # 单个口音最多试几次
WORKERS = 4           # 并发（别开太大，别把人家当压测）
MIN_BYTES = 1000      # 小于这个字节数基本就是错误页
ACCENT_TYPE = 2       # 1 = 英式，2 = 美式
AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".flac", ".m4a")

_lock = threading.Lock()
_done = {"ok": 0, "skip": 0, "fail": 0, "fallback": 0}
_failed = []


def log(msg):
    with _lock:
        print(msg, flush=True)


def load_words():
    """按出现顺序去重所有词书里的 word。"""
    seen, words = set(), []
    for name in sorted(os.listdir(BOOKS_DIR)):
        if not name.lower().endswith(".csv"):
            continue
        with open(os.path.join(BOOKS_DIR, name), encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                w = (row.get("word") or "").strip()
                if w and w not in seen:
                    seen.add(w)
                    words.append(w)
    return words


def sniff(data):
    """
    按文件头认容器，返回 (后缀, 说明)；认不出来返回 None。

    AVI/MP3 都有可能不带 ID3 标签而以 MPEG 帧同步字开头，所以两种都认。
    """
    if len(data) >= 3 and data[:3] == b"ID3":
        return ".mp3", "mp3/ID3"
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return ".mp3", "mp3/MPEG帧"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return ".wav", "wav"
    if data[:4] == b"OggS":
        return ".ogg", "ogg"
    if data[:4] == b"fLaC":
        return ".flac", "flac"
    if len(data) >= 8 and data[4:8] == b"ftyp":
        return ".m4a", "m4a"
    return None


def existing_path(word):
    """已经有这个单词的音频就返回路径（顺带校验一下没坏）。"""
    for ext in AUDIO_EXTS:
        p = os.path.join(AUDIO_DIR, word + ext)
        if os.path.exists(p) and os.path.getsize(p) >= MIN_BYTES:
            with open(p, "rb") as f:
                if sniff(f.read(12)):
                    return p
    return None


def fetch_type(word, accent):
    """按指定口音抓一条，失败会自己重试 TRIES 次。"""
    url = API % (urllib.parse.quote(word), accent)
    last = None
    for attempt in range(TRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                       "Referer": "https://dict.youdao.com/"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                ctype = (resp.headers.get("Content-Type") or "").lower()
                data = resp.read()
            if resp.status != 200:
                raise ValueError("HTTP %s" % resp.status)
            if "audio" not in ctype and "octet-stream" not in ctype:
                raise ValueError("Content-Type=%s" % ctype)
            if len(data) < MIN_BYTES:
                raise ValueError("只有 %d 字节" % len(data))
            if not sniff(data):
                raise ValueError("认不出的容器（%d 字节, %s）" % (len(data), data[:4].hex()))
            return data
        except Exception as e:                       # noqa: BLE001 - 网络什么都可能抛
            last = e
            if attempt < TRIES - 1:
                time.sleep(0.6 * (2 ** attempt) + random.random() * 0.3)
    raise RuntimeError(str(last))


def download(word, accent):
    """
    先按指定口音抓；整条都抓不到就换另一种口音兜底。

    有道那边有的词只有单口音（比如 systematic(al) 的美式直接 500、英式正常），
    兜底能把这些救回来 —— 代价是这一小部分词的读音口音和其余的不一致。
    返回 (数据, 实际用的口音)。
    """
    try:
        return fetch_type(word, accent), accent
    except Exception as first:                       # noqa: BLE001
        other = 1 if accent == 2 else 2
        try:
            return fetch_type(word, other), other
        except Exception:                            # noqa: BLE001
            raise first


def one(word, accent, force):
    if not force and existing_path(word):
        with _lock:
            _done["skip"] += 1
        return
    try:
        data, used = download(word, accent)
    except Exception as e:                           # noqa: BLE001
        with _lock:
            _done["fail"] += 1
            _failed.append((word, str(e)))
        return
    ext, _what = sniff(data)
    path = os.path.join(AUDIO_DIR, word + ext)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)                            # 原子落地
    with _lock:
        _done["ok"] += 1
        if used != accent:
            _done["fallback"] += 1


def main():
    ap = argparse.ArgumentParser(description="抓单词读音")
    ap.add_argument("--type", type=int, default=ACCENT_TYPE, choices=(1, 2),
                    help="1 = 英式，2 = 美式（默认）")
    ap.add_argument("--force", action="store_true", help="已有的也重抓")
    ap.add_argument("--only-failed", action="store_true", help="只重跑 _failed.txt 里的词")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个（试跑用）")
    ap.add_argument("--workers", type=int, default=WORKERS)
    args = ap.parse_args()

    os.makedirs(AUDIO_DIR, exist_ok=True)
    if args.only_failed and os.path.exists(FAILED_LIST):
        with open(FAILED_LIST, encoding="utf-8") as f:
            words = [ln.strip() for ln in f if ln.strip()]
    else:
        words = load_words()
    if args.limit:
        words = words[:args.limit]

    total = len(words)
    print("待处理 %d 个词 -> %s（%s，%d 并发）"
          % (total, AUDIO_DIR, "英式" if args.type == 1 else "美式", args.workers))
    if not total:
        print("没有要处理的词。")
        return 0

    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(one, w, args.type, args.force) for w in words]
        for i, _ in enumerate(concurrent.futures.as_completed(futs), 1):
            if i % 200 == 0 or i == total:
                el = time.perf_counter() - t0
                log("[%5d/%d] 新下 %d · 跳过 %d · 换口音 %d · 失败 %d · 用时 %.0fs · 预计还需 %.0fs"
                    % (i, total, _done["ok"], _done["skip"], _done["fallback"],
                       _done["fail"], el, el / i * (total - i)))
        for f in futs:
            f.result()                               # 把池子里没冒出来的异常也带上来

    if _failed:
        with open(FAILED_LIST, "w", encoding="utf-8") as f:
            for w, why in sorted(_failed):
                f.write("%s\n" % w)
        print("\n有 %d 个没抓到，清单：%s" % (len(_failed), FAILED_LIST))
        for w, why in sorted(_failed)[:20]:
            print("    %-22s %s" % (w, why))
        if len(_failed) > 20:
            print("    …… 其余见清单")
    else:
        if os.path.exists(FAILED_LIST):
            os.remove(FAILED_LIST)                   # 全好了就把旧清单清掉
        print("\n全部就绪。")
    print("新下 %d · 跳过 %d · 换口音兜底 %d · 失败 %d · 总用时 %.0fs"
          % (_done["ok"], _done["skip"], _done["fallback"], _done["fail"],
             time.perf_counter() - t0))
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
