# -*- coding: utf-8 -*-
r"""
把 audio\ 下的读音统一成**同一种 mp3 格式**。

    python tools\normalize_audio.py            # 检查 + 归一
    python tools\normalize_audio.py --check    # 只看分布，不动文件
    python tools\normalize_audio.py --jobs 6   # 并发（默认 4）

为什么需要它：
  · 有道同一个接口会吐不同容器 —— 绝大多数是 mp3，另有一批词只有 wav；
  · 就算是 mp3，采样率（48000 / 44100 / 24000 / 16000）、码率（64 / 128 / 160 kbps）、
    声道（mono / joint）、ID3 版本也都不统一。

做法：先扫一遍，取**出现最多的那种 mp3 格式**当目标，然后只把不合群的（包括 wav）
用 ffmpeg 重编过去 —— 符合目标格式的文件原样不动，不做无谓的二次压缩。
最后再扫一遍确认。ffmpeg 要在 PATH 里（winget install Gyan.FFmpeg）。
"""
import argparse
import collections
import concurrent.futures
import glob
import os
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIO_DIR = os.path.join(APP_DIR, "audio")
AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".flac", ".m4a")

# MPEG 帧头里的码率表（kbps），键 = (MPEG 版本组, layer)
BITRATE = {
    (1, 1): [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
    (1, 2): [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
    (1, 3): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    (2, 1): [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],
    (2, 2): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
    (2, 3): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}
SRATE = {1: [44100, 48000, 32000], 2: [22050, 24000, 16000], 25: [11025, 12000, 8000]}


def _syncsafe(b):
    return ((b[0] & 0x7F) << 21) | ((b[1] & 0x7F) << 14) | ((b[2] & 0x7F) << 7) | (b[3] & 0x7F)


def probe_mp3(path):
    """读出（ID3 版本, MPEG 版本, layer, 码率, 采样率, 声道）；不是 mp3 / 读不懂返回 None。"""
    try:
        with open(path, "rb") as f:
            raw = f.read(65536)
    except OSError:
        return None
    id3 = 0
    off = 0
    if raw[:3] == b"ID3" and len(raw) >= 10:
        id3 = raw[3]
        off = 10 + _syncsafe(raw[6:10])
    i = off
    while i + 4 <= len(raw):
        if raw[i] == 0xFF and (raw[i + 1] & 0xE0) == 0xE0:
            h1, h2, h3 = raw[i + 1], raw[i + 2], raw[i + 3]
            ver = {0: 25, 2: 2, 3: 1}.get((h1 >> 3) & 3)
            layer_bits = (h1 >> 1) & 3
            if ver is None or layer_bits == 0:
                i += 1
                continue
            layer = {1: 3, 2: 2, 3: 1}[layer_bits]
            br_i, sr_i = (h2 >> 4) & 0x0F, (h2 >> 2) & 3
            if br_i in (0, 15) or sr_i == 3:
                i += 1
                continue
            return (id3, ver, layer,
                    BITRATE[(1 if ver == 1 else 2, layer)][br_i],
                    SRATE[ver][sr_i],
                    {0: "stereo", 1: "joint", 2: "dual", 3: "mono"}[(h3 >> 6) & 3])
        i += 1
    return None


def fmt(p):
    return "ID3v2.%d  MPEG%d-L%d  %d kbps  %d Hz  %s" % p


def all_files():
    out = []
    for ext in AUDIO_EXTS:
        out += glob.glob(os.path.join(AUDIO_DIR, "*" + ext))
    return sorted(out)


def survey(files, label):
    stat = collections.Counter()
    other = []
    for f in files:
        p = probe_mp3(f)
        if p is None:
            other.append(f)
        else:
            stat[p] += 1
    print("%s（%d 个文件）：" % (label, len(files)))
    for k, n in stat.most_common():
        print("    %-46s x%d" % (fmt(k), n))
    if other:
        kinds = collections.Counter(os.path.splitext(f)[1] for f in other)
        print("    非 mp3（会被转掉）：%s" % ", ".join("%s x%d" % (e, n) for e, n in kinds.most_common()))
    return stat


def main():
    ap = argparse.ArgumentParser(description="统一 audio\\ 下读音的格式")
    ap.add_argument("--check", action="store_true", help="只看分布，不动文件")
    ap.add_argument("--jobs", type=int, default=4, help="并发数（默认 4）")
    args = ap.parse_args()

    files = all_files()
    if not files:
        print("audio\\ 里没有音频")
        return 1

    stat = survey(files, "归一前")
    if not stat:
        print("没有任何 mp3，没法定目标格式")
        return 1
    target, _n = stat.most_common(1)[0]
    print("\n目标格式（出现最多的那种）：%s" % fmt(target))
    if args.check:
        return 0

    todo = [f for f in files if probe_mp3(f) != target]
    print("需要转换：%d 个（其余 %d 个原样保留，不做二次压缩）" % (len(todo), len(files) - len(todo)))
    if not todo:
        print("已经统一了。")
        return 0

    id3v2, _mpeg, _layer, br, sr, ch = target      # 注意别拿 MPEG 版本当 ID3 版本用
    ac = "1" if ch == "mono" else "2"
    id3_ver = id3v2 if id3v2 in (3, 4) else 3
    done = {"ok": 0, "fail": 0}
    fails = []

    def convert(path):
        dest = os.path.splitext(path)[0] + ".mp3"
        tmp = dest + ".norm.mp3"
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", path,
               "-map_metadata", "-1", "-ac", ac, "-ar", str(sr),
               "-c:a", "libmp3lame", "-b:a", "%dk" % br,
               "-write_xing", "0",          # 别写 Xing 头帧，否则第一个帧不是音频帧
               "-write_id3v2", "1", "-id3v2_version", str(id3_ver),
               tmp]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            got = probe_mp3(tmp)
            if got != target:
                raise RuntimeError("转完仍不匹配：%s" % (fmt(got) if got else "读不出"))
            os.replace(tmp, dest)
            if os.path.normcase(dest) != os.path.normcase(path) and os.path.exists(path):
                os.remove(path)                       # wav/ogg → mp3 之后把原文件删掉
            done["ok"] += 1
        except Exception as e:                        # noqa: BLE001
            done["fail"] += 1
            fails.append((os.path.basename(path), str(e)[:140]))
            if os.path.exists(tmp):
                os.remove(tmp)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(convert, todo))

    print("转换完成 %d 个，失败 %d 个" % (done["ok"], done["fail"]))
    for n, why in fails[:10]:
        print("    %-24s %s" % (n, why))
    survey(all_files(), "归一后")
    return 1 if done["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
