# -*- coding: utf-8 -*-
"""
单词弹幕 · Danmaku Words
========================
在电脑屏幕上方 15% 的范围内飘过「英语单词 + 词性 + 中文释义」弹幕。

零第三方依赖：仅用 Python 标准库 tkinter + ctypes。
词库放在 books\\ 目录（一本词书一个 .csv），允许放多本并在面板里切换。

用法
----
    双击  启动单词弹幕.bat
    或者  pythonw.exe danmaku.py
    开机自启时加上 --run：pythonw.exe danmaku.py --run（直接开跑并收起面板）

热键
----
    Ctrl+Alt+H   显示 / 隐藏控制面板
    Ctrl+Alt+P   暂停 / 继续
    Ctrl+Alt+Q   退出
"""

import csv
import json
import math
import os
import random
import re
import sys
import time
import ctypes
import ctypes.wintypes
import struct
import tkinter as tk
from tkinter import ttk, font as tkfont, messagebox

try:
    import winreg          # 从注册表按「字体族名」反查字体文件
except ImportError:        # 非 Windows 环境（理论上用不到）
    winreg = None

# ---------------------------------------------------------------- 常量

APP_TITLE = "单词弹幕"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
# 多词书：books\ 下每个 .csv 就是一本词书，面板里可切换
BOOKS_DIR = os.path.join(APP_DIR, "books")
DATA_CSV = os.path.join(BOOKS_DIR, "六级词汇大全（已学·152词）.csv")
# 没在 config 里记过词书时优先用它（宇原本用的就是"六级已学"）
DEFAULT_BOOK_NAME = os.path.basename(DATA_CSV)
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
FONT_DIR = os.path.join(APP_DIR, "fonts")

# 大写锁定：开着的时候弹幕层不再鼠标穿透，可以悬停看音标、点星收藏
VK_CAPITAL = 0x14
CAPS_POLL_MS = 100        # 轮询大写锁定的周期（毫秒）；要短于一次按键，才能抓到按下沿
HOVER_POLL_MS = 90        # 悬停命中检测的周期（毫秒）

# 新弹幕的入场点（spawn 里 x = sw + 10）与两条弹幕之间要留的最小水平空隙
ENTER_X_PAD = 10
# 悬停结束时，压在它身上的那条弹幕要用多少倍速**冲刺让路**。
# 原来是把悬停词冻在原地、等对方慢慢飘过去（好几秒，看着像卡死），
# 现在换成给挡路的那条临时加速，让它快速越过去、悬停词立刻恢复移动。
BOOST_MULT = 2.6
# 兜底：万一加速会追尾前面的邻居，还是退回"原地排队等"，最多等这么久（秒）。
UNFREEZE_WAIT_MAX = 8.0

# 音标固定用微软雅黑（常规字重 —— 花底 + 小字号下粗体笔画会糊成一团）
PHON_FACE = "Microsoft YaHei"

# 收藏夹词书：悬停时点★收进来的词，全部整理进这一本
FAV_BOOK_NAME = "已收藏单词.csv"
FAV_BOOK_PATH = os.path.join(BOOKS_DIR, FAV_BOOK_NAME)
# 旧名，仅为兼容：启动时若发现它存在会就地改名，config 里存了旧名也能认
LEGACY_FAV_NAME = "favourite.csv"
# 词书只留这三列：单词 / 音标 / 「词性 + 释义」。
# 百词斩原表还有 topic_id（词条唯一 id，用于同步学习状态）、freq（词频）、
# word_length、is_favorite，App 一行都不读 —— 留着只是给 CSV 涨体积
# （6203 词那本能省掉三分之一），所以全砍。
BOOK_FIELDS = ["word", "accent", "mean_cn"]

# 透明色键：该颜色会被 Windows 完全抠掉，窗口其余部分照常绘制
TRANSPARENT_KEY = "#010203"

# 图标（用户放在 logo/ 里的番茄女孩）
LOGO_PATH = os.path.join(APP_DIR, "logo", "TomatoGirl_Logo.png")
# 把手的放大版：高分屏下 32px 原图只有半个逻辑厘米，太小了点不着 / 拖不动
LOGO_HANDLE_PATH = os.path.join(APP_DIR, "logo", "TomatoGirl_96.png")
# 把手窗口边长（物理像素）
HANDLE_SIZE = 88
# 字体下拉里「自动」那一项的显示文案（≠ 任何真实字体族名）
AUTO_FONT_LABEL = "（自动 · 优先萝莉体）"

# 弹幕文字候选色（随机模式下使用）
PALETTE = [
    "#FFFFFF", "#FFF3B0", "#A0E7E5", "#FFB7B2",
    "#C7CEEA", "#B5EAD7", "#FFDAC1", "#E2F0CB",
]

# ---------------------------------------------------------------- 主题色
# 全部取自 logo\TomatoGirl_Logo.png 的实际像素：
#   主红 #E64F3B / 暗红 #C93522 / 深红 #9C2010 / 浅红 #FDAA9A
#   叶绿 #4F8527 / 深绿 #3D6A1E
#   肤色 #FCD6BE 用来调出暖白背景，避免原来那套冷灰配色跟番茄打架。
CLR_RED      = "#E64F3B"   # 番茄主红：标题、主按钮、滑轨激活
CLR_RED_DARK = "#C93522"   # 暗红：按压态、主按钮 hover
CLR_RED_DEEP = "#9C2010"   # 深红：强调文字
CLR_RED_SOFT = "#FDAA9A"   # 浅红：次要/禁用
CLR_GREEN     = "#4F8527"  # 番茄叶绿：运行中状态、次按钮、强调边
CLR_GREEN_DK  = "#3D6A1E"
CLR_BG        = "#FDF7F3"  # 暖白背景（肤色系）
CLR_BAR       = "#FFF1EA"  # 标题栏底
CLR_CARD      = "#FFFFFF"
CLR_BORDER    = "#F2DCD2"
CLR_TROUGH    = "#FAEDE6"  # 滑块槽
CLR_TEXT      = "#3A2620"  # 暖深棕正文
CLR_MUTED     = "#8C7A72"
# —— 弹幕悬停信息框（悬停时才出现的那块）——
# 底色故意压得很深：stipple 只填一半像素，另一半透出桌面，
# 底越深，白字（尤其是没有描边的音标）压在花底上才越看得清。
CLR_HOVER_BG   = "#262626"
CLR_HOVER_BRD  = "#EDEDED"  # 圆角描边
CLR_HOVER_TEXT = "#FFFFFF"  # 音标字色
CLR_STAR_ON    = "#FFC53D"  # 已收藏：实心金黄
CLR_STAR_OFF   = "#E9E9E9"  # 未收藏：实心浅灰
CLR_STAR_ON_BR = "#B07A00"  # 星的描边：花底上没描边就发飘
CLR_STAR_OFF_BR = "#7A7A7A"

DEFAULT_CONFIG = {
    # 弹幕出现的纵向区域 = 屏幕顶部 15% 高度的一条带（不是"字号占 15%"）
    "band_ratio": 0.15,      # 区域高度 = 屏幕高度 × 该比例
    "band_mode": "top",      # top(默认=屏幕上方) / middle / bottom / random
    # 每条弹幕按「固定间隔」出现，不再要求上一条离屏后才出下一条
    "spawn_interval": 2.5,   # 固定出现间隔（秒）
    "one_at_a_time": False,  # 保留开关：True 时才回到"上一条离屏再出下一条"
    "font_ratio": 0.03501,   # 字号 = 屏幕高度 × 该比例
    "speed_ratio": 0.10309,  # 移动速度 = 屏幕宽度 × 该比例 / 秒
    "opacity": 0.90499,      # 弹幕不透明度
    "text_color": "#FFFFFF", # 固定颜色
    "random_color": True,    # 是否随机取色
    "max_cn_len": 30,        # 中文释义最大长度，超出截断
    "max_on_screen": 5,      # 同屏最多弹幕数（固定间隔下允许几条同时在场）
    # —— 释义裁剪 ——
    "max_meanings": 2,       # 一个单词最多展示几个义项（取考频靠前的）
    "max_pos": 3,            # 最多串联几个词性（多词性：词性+释义 后接下一个词性+释义）
    "per_pos_meanings": 2,   # 单个词性下最多取几个义项
    # —— 字体 ——
    # font_family 为具体字体族名时用它渲染（"Lolita" 即萝莉体）；
    # 空串 = 自动：有 fonts\ 自定义字体就优先它，否则用 font_face。
    "font_family": "",
    "use_custom_font": True, # 兼容旧配置（旧版只有这个开关）
    "font_face": "Microsoft YaHei",   # 缺字回退 / 无自定义字体时的字体
    # —— 词书 ——
    "book": "六级核心过考版（全部·2551词）.csv",   # books\ 下的文件名；空串 = 默认那本
    # —— 右下角把手位置 ——
    # 其余出厂值都取自实际调好的一份配置；唯独这里保持 -1：把手坐标是**屏幕
    # 绝对像素**，写死成某一台机器的值，换个分辨率/外接屏就跑到屏幕外找不着了。
    "handle_x": -1,
    "handle_y": -1,
}

POS_RE = re.compile(r"^\s*([a-zA-Z]{1,6}\.)\s*(.+)$")

# 标点归一化表：把「主字体画不出」的标点换成它自带的等价符号。
#
# 现状：**空表，不替换任何标点**。
# 早期版本这里塞了 ；，（）：。 等一整套映射，依据是"萝莉体缺全角标点"——
# 那个结论来自一次错误的 cmap 解析（把字形索引当成了字符码）。
# 重测后萝莉体对 ；，。（）：【】／｜～？！．、… — · 全部有字形，
# 直接用中文标点渲染即可，用户也明确要求分号用中文标点。
# 换其它字体时如果真撞上缺标点，缺字回退机制（split_runs）会自动兜住，
# 这个表只作应急用。
PUNCT_MAP = {}

# 出现区域：内部值 -> 面板显示
BAND_LABELS = {
    "top": "屏幕上方",
    "middle": "屏幕中部",
    "bottom": "屏幕下方",
    "random": "随机位置",
}
BAND_VALUES = {v: k for k, v in BAND_LABELS.items()}


# ---------------------------------------------------------------- 系统工具

def enable_dpi_awareness():
    """让 tkinter 拿到真实物理分辨率，避免高分屏下坐标错位 / 字体发虚。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_screen_size():
    enable_dpi_awareness()
    try:
        w = ctypes.windll.user32.GetSystemMetrics(0)
        h = ctypes.windll.user32.GetSystemMetrics(1)
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass
    return 1920, 1080


# 描边副本数：8 = 八边形膨胀（推荐，拐角与曲线不台阶化）；
# 4 = 只留四个对角副本（省一半 canvas item，但斜向笔画会出现 ov 像素的台阶）。
# 之所以做成可调常量，是因为**每帧重绘的文本 item 数是本程序唯一的帧率瓶颈**
# （实测 9 个 item / 104fps → 45 个 item / 58fps），调它就是在"画质 vs 帧率"上取舍。
STROKE_DIRS = 8


def stroke_offsets(ov, ov2):
    """描边副本的偏移量表（ov=正交步长，ov2=斜角步长）。"""
    if STROKE_DIRS >= 8:
        return ((-ov, 0), (ov, 0), (0, -ov), (0, ov),
                (-ov2, -ov2), (ov2, -ov2), (-ov2, ov2), (ov2, ov2))
    return ((-ov2, -ov2), (ov2, -ov2), (-ov2, ov2), (ov2, ov2))


# ---------- GDI 预渲染：把「8 向描边 + 正文」画成 1 张位图 ----------
#
# 为什么值得为它写这段 ctypes：弹幕每帧的开销**几乎全在** Tk 重新光栅化
# text item 上。实测同屏 5 条 = 45 个 text item → 58fps（帧间隔 p95 34ms），
# 同屏 1 条 = 9 个 item → 104fps，帧率基本与 item 数成反比。
# 改成"每条弹幕先画成一张位图、每帧只 blit 1 个 image item"后，
# 帧率与条数脱钩，而描边质量与原来**完全一致**（同一套 8 向膨胀参数）。

_GDI = ctypes.windll.gdi32
_KEY_RGB = (1, 2, 3)          # 与 TRANSPARENT_KEY = "#010203" 同色
_TA_BASELINE = 24             # SetTextAlign: 让 y 表示"基线"，而不是字符格顶
_ANTIALIASED = 4              # 灰度抗锯齿；ClearType 会在色键底上留彩边
_GDI_OK = True                # 一旦失败就整体退回逐段 text 路径


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


class _LOGFONTW(ctypes.Structure):
    _fields_ = [("lfHeight", ctypes.c_long), ("lfWidth", ctypes.c_long),
                ("lfEscapement", ctypes.c_long), ("lfOrientation", ctypes.c_long),
                ("lfWeight", ctypes.c_long), ("lfItalic", ctypes.c_byte),
                ("lfUnderline", ctypes.c_byte), ("lfStrikeOut", ctypes.c_byte),
                ("lfCharSet", ctypes.c_byte), ("lfOutPrecision", ctypes.c_byte),
                ("lfClipPrecision", ctypes.c_byte), ("lfQuality", ctypes.c_byte),
                ("lfPitchAndFamily", ctypes.c_byte),
                ("lfFaceName", ctypes.c_wchar * 32)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


def _gdi_font(px, face, bold=False):
    """
    px = **设备像素**字高，直接用。

    ⚠️ 别按 GetDeviceCaps(LOGPIXELSY) 换算：画进去的是 CreateCompatibleDC +
    DIBSection（MM_TEXT 1:1 映射），逻辑单位就是设备像素；拿屏幕 DC 的 DPI
    （本机 192）去换算会把字高缩掉一半，整条弹幕变成半大。
    """
    lf = _LOGFONTW()
    lf.lfHeight = -int(round(px))
    lf.lfWeight = 700 if bold else 400
    lf.lfQuality = _ANTIALIASED
    lf.lfCharSet = 1
    lf.lfFaceName = face[:31]
    return _GDI.CreateFontIndirectW(ctypes.byref(lf))


def _hex_rgb(color):
    """"#RRGGBB" → (r, g, b)；容忍 "#RGB" 与大小写。"""
    h = (color or "#FFFFFF").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return 255, 255, 255


def _bgra_to_ppm(w, h, bgra):
    """32bpp BGRA → 二进制 PPM(P6)。Tk 原生就吃 PPM，比 PNG 少一步 zlib。"""
    stride = w * 4
    raw = bytearray(w * h * 3)
    for y in range(h):
        row = bgra[y * stride:(y + 1) * stride]
        base = y * w * 3
        end = base + w * 3
        # bytearray 的带步长切片赋值走 C 层，比逐像素循环快两个数量级
        raw[base:end:3] = row[2::4]
        raw[base + 1:end:3] = row[1::4]
        raw[base + 2:end:3] = row[0::4]
    return b"P6\n%d %d\n255\n" % (w, h) + bytes(raw)


def render_text_bitmap(runs, font_px, face_main, face_fall, color_rgb,
                       ascent, linespace):
    """
    把整条弹幕（所有段 + 8 向描边）画成一张位图，背景填色键色（会被抠掉）。

    返回 (w, h, ppm, off_x, off_y)：位图贴到 (cx - off_x, ys - off_y) 时，
    文字的落点与"逐段 text + anchor=nw"**逐像素重合**（用 TA_BASELINE 对齐基线，
    位图高度取 linespace，所以 canvas bbox 两者一致 —— 悬停信息框那些按 bbox
    排版的代码一行都不用改）。
    """
    global _GDI_OK
    if not _GDI_OK:
        return None
    hdc = None
    f_main = f_fall = hbm = None
    try:
        hdc = _GDI.CreateCompatibleDC(0)
        f_main = _gdi_font(font_px, face_main)
        f_fall = _gdi_font(font_px, face_fall, True)

        ov = max(1, font_px // 22)
        ov2 = max(1, (ov * 7) // 10)
        offs = ((-ov, 0), (ov, 0), (0, -ov), (0, ov),
                (-ov2, -ov2), (ov2, -ov2), (-ov2, ov2), (ov2, ov2))
        pad = ov + 1

        total = 0
        for ok, s in runs:
            old = _GDI.SelectObject(hdc, f_main if ok else f_fall)
            sz = _SIZE()
            _GDI.GetTextExtentPoint32W(hdc, s, len(s), ctypes.byref(sz))
            _GDI.SelectObject(hdc, old)
            total += sz.cx

        w = int(total) + pad * 2
        h = int(linespace) + pad * 2
        if w <= 0 or h <= 0:
            return None

        bi = _BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bi.biWidth = w
        bi.biHeight = -h                  # 负 = top-down，省掉翻行
        bi.biPlanes = 1
        bi.biBitCount = 32
        bits = ctypes.c_void_p()
        hbm = _GDI.CreateDIBSection(hdc, ctypes.byref(bi), 0,
                                    ctypes.byref(bits), None, 0)
        if not hbm:
            return None
        _GDI.SelectObject(hdc, hbm)
        _GDI.SetBkMode(hdc, 1)            # TRANSPARENT
        _GDI.SetTextAlign(hdc, _TA_BASELINE)

        n = w * h
        ctypes.memmove(bits.value,
                       bytes((_KEY_RGB[2], _KEY_RGB[1], _KEY_RGB[0], 255)) * n,
                       n * 4)

        base_y = pad + int(ascent)        # 位图内基线
        x = pad
        for ok, s in runs:
            _GDI.SelectObject(hdc, f_main if ok else f_fall)
            _GDI.SetTextColor(hdc, 0x000000)
            for dx, dy in offs:
                _GDI.TextOutW(hdc, x + dx, base_y + dy, s, len(s))
            _GDI.SetTextColor(hdc, (color_rgb[2] << 16) | (color_rgb[1] << 8)
                              | color_rgb[0])
            _GDI.TextOutW(hdc, x, base_y, s, len(s))
            sz = _SIZE()
            _GDI.GetTextExtentPoint32W(hdc, s, len(s), ctypes.byref(sz))
            x += sz.cx

        data = ctypes.string_at(bits.value, n * 4)
        return w, h, _bgra_to_ppm(w, h, data), pad, pad
    except Exception:
        _GDI_OK = False
        return None
    finally:
        for obj in (hbm, f_main, f_fall):
            if obj:
                try:
                    _GDI.DeleteObject(obj)
                except Exception:
                    pass
        if hdc:
            try:
                _GDI.DeleteDC(hdc)
            except Exception:
                pass


def set_timer_resolution(ms=1):
    """
    Windows 默认时钟分辨率是 15.625 ms，tkinter 的 after(16) 会被拖成 31 ms，
    动画直接掉到 30fps。把分辨率提到 1 ms 才能让高频调度真正生效。
    """
    try:
        ctypes.windll.winmm.timeBeginPeriod(ms)
        return True
    except Exception:
        return False


def end_timer_resolution(ms=1):
    try:
        ctypes.windll.winmm.timeEndPeriod(ms)
    except Exception:
        pass


def apply_layered(hwnd, key_hex, click_through=True, alpha=255):
    """
    手动实现「色键透明 + 鼠标穿透」。

    为什么不用 tkinter 的 `wm attributes -transparentcolor`？
    实测在 Windows 上它**不生效**——窗口会糊成一块实心黑底（已用对照组验证）。
    必须自己调 SetLayeredWindowAttributes，并且注意：
      · COLORREF 是 0x00BBGGRR 顺序，不是 RGB，写反了颜色键就对不上；
      · 改完 WS_EX 样式后要**立刻重设** layered 属性，否则窗口可能整块不可见。
    """
    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_TOOLWINDOW = 0x00000080   # 不出现在 Alt+Tab，避免干扰
    LWA_COLORKEY = 0x00000001
    LWA_ALPHA = 0x00000002
    try:
        r = int(key_hex[1:3], 16)
        g = int(key_hex[3:5], 16)
        b = int(key_hex[5:7], 16)
        colorref = (b << 16) | (g << 8) | r

        u = ctypes.windll.user32
        ex = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ex |= WS_EX_LAYERED | WS_EX_TOOLWINDOW
        if click_through:
            ex |= WS_EX_TRANSPARENT
        else:
            ex &= ~WS_EX_TRANSPARENT
        u.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
        # 色键 + 整体 alpha 可以同时生效：色键区全透明，文字按 alpha 半透明
        a = max(0, min(255, int(alpha)))
        u.SetLayeredWindowAttributes(hwnd, colorref, a,
                                     LWA_COLORKEY | (LWA_ALPHA if a < 255 else 0))
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 字体

def _read_ttf_tables(path, index=0):
    """
    读 TTF/OTF 的表目录。顺便支持 .ttc（字体集合）——系统里很多中文字体
    （msyh.ttc / simsun.ttc）都是集合，不处理的话会直接判定"不是字体文件"。
    index 选集合里的第几支字体，越界则回落到第 0 支。
    """
    with open(path, "rb") as f:
        data = f.read()
    base = 0
    if data[:4] == b"ttcf":
        n = struct.unpack(">I", data[8:12])[0] if len(data) >= 12 else 0
        if index >= n or index < 0:
            index = 0
        base = struct.unpack(">I", data[12 + index * 4:16 + index * 4])[0]
    if data[base:base + 4] not in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
        raise ValueError("not a TTF/OTF: %s" % path)
    num = struct.unpack(">H", data[base + 4:base + 6])[0]
    tables = {}
    for i in range(num):
        off = base + 12 + i * 16
        tag = data[off:off + 4].decode("latin-1")
        o, l = struct.unpack(">II", data[off + 8:off + 16])
        tables[tag] = (o, l, data[o:o + l])
    return tables


def _ttf_family_name(path):
    """
    读 name 表 id=1 拿到字体 family 名（换字体文件时不用改代码）。

    坑：name 表里 pid=1（Macintosh）的记录常常排在 pid=3（Windows）前面，
    而它是**单字节**编码——按 UTF-16 解码会把 "Lolita" 读成 "䱯汩瑡"。
    所以必须按 platformID 选解码方式，并且优先用 Windows/Unicode 的那条。
    """
    try:
        nd = _read_ttf_tables(path)["name"][2]
        cnt = struct.unpack(">H", nd[2:4])[0]
        so = struct.unpack(">H", nd[4:6])[0]
        recs = []
        for i in range(cnt):
            o = 6 + i * 12
            pid, _eid, _lid, nid, ln, off = struct.unpack(">HHHHHH", nd[o:o + 12])
            if nid == 1 and ln > 0:
                recs.append((pid, nd[so + off:so + off + ln]))
        # Windows(3) / Unicode(0) 用 UTF-16-BE；Macintosh(1) 是单字节
        for want in (3, 0, 1):
            for pid, raw in recs:
                if pid != want:
                    continue
                try:
                    v = raw.decode("utf-16-be") if want in (3, 0) else raw.decode("latin-1")
                except Exception:
                    continue
                v = v.strip("\x00").strip()
                if v:
                    return v
    except Exception:
        pass
    return None


def _ttf_codepoints(path):
    """解析 cmap，返回字体能画出来的所有码位。用于缺字检测。"""
    try:
        cd = _read_ttf_tables(path)["cmap"][2]
    except Exception:
        return set()
    n = struct.unpack(">H", cd[2:4])[0]
    best = None
    for i in range(n):
        off = 4 + i * 8
        pid, eid, so = struct.unpack(">HHI", cd[off:off + 8])
        if pid == 3 and eid in (1, 10):
            best = so
            if eid == 10:
                break
        if best is None and pid == 0:
            best = so
    if best is None:
        return set()
    fmt = struct.unpack(">H", cd[best:best + 2])[0]
    chars = set()
    try:
        if fmt == 4:
            seg = struct.unpack(">H", cd[best + 6:best + 8])[0] // 2
            base = best + 14
            end = struct.unpack(">%dH" % seg, cd[base:base + seg * 2])
            sp = base + seg * 2 + 2
            start = struct.unpack(">%dH" % seg, cd[sp:sp + seg * 2])
            dp = sp + seg * 2
            delta = struct.unpack(">%dh" % seg, cd[dp:dp + seg * 2])
            rp = dp + seg * 2
            rng = struct.unpack(">%dH" % seg, cd[rp:rp + seg * 2])
            for i in range(seg):
                s, e = start[i], end[i]
                if s == 0xFFFF or e == 0xFFFF and s == 0xFFFF:
                    continue
                if rng[i] == 0:
                    for c in range(s, min(e, 0xFFFE) + 1):
                        g = (c + delta[i]) & 0xFFFF
                        if g:
                            chars.add(c)
                else:
                    for c in range(s, min(e, 0xFFFE) + 1):
                        gp = rp + i * 2 + rng[i] + (c - s) * 2
                        if gp + 2 > len(cd):
                            continue
                        g = struct.unpack(">H", cd[gp:gp + 2])[0]
                        if g:
                            chars.add(c)
        elif fmt == 12:
            ngroups = struct.unpack(">I", cd[best + 12:best + 16])[0]
            for i in range(ngroups):
                o = best + 16 + i * 12
                s, e, _g = struct.unpack(">III", cd[o:o + 12])
                for c in range(s, min(e, s + 0x40000) + 1):
                    chars.add(c)
    except Exception:
        pass
    return chars


class FontSet(object):
    """
    字体管理：
      · 注册 fonts/ 下的自带字体（默认萝莉体），并算出它覆盖哪些字；
      · 按「字体族名」从注册表反查任意系统字体文件，同样算覆盖范围。

    覆盖范围用来做**逐字符缺字回退**：一支字体画不出的字（萝莉体缺全角标点、
    装饰字体缺简体字）自动改用回退字体单独画，避免整条弹幕变豆腐块。
    """

    def __init__(self):
        self.custom_path = None
        self.custom_family = None
        self.covered = set()
        self.available = False
        self._cov_cache = {}     # 小写族名 -> set | None（None = 查不到，不做回退）

    def load(self):
        if not os.path.isdir(FONT_DIR):
            return False
        ttfs = [f for f in os.listdir(FONT_DIR)
                if f.lower().endswith((".ttf", ".otf", ".ttc"))]
        if not ttfs:
            return False
        path = os.path.join(FONT_DIR, sorted(ttfs)[0])
        family = _ttf_family_name(path)
        if not family:
            return False
        FR_PRIVATE = 0x00000010
        try:
            ctypes.windll.gdi32.AddFontResourceExW(path, FR_PRIVATE, 0)
        except Exception:
            pass
        self.custom_path = path
        self.custom_family = family
        self.covered = _ttf_codepoints(path)
        self.available = True
        return True

    def family(self, cfg):
        """当前生效的字体族名。font_family 有值就用它，否则自动（优先萝莉体）。"""
        want = (cfg.get("font_family") or "").strip()
        if want:
            return want
        if self.available and cfg.get("use_custom_font", True):
            return self.custom_family
        return cfg.get("font_face", "Microsoft YaHei")

    def coverage(self, family):
        """family 能渲染的码位集合；None = 查不到（此时不做回退，交给系统）。"""
        if not family:
            return None
        key = family.strip().lower()
        if key in self._cov_cache:
            return self._cov_cache[key]
        cov = None
        if self.available and family == self.custom_family:
            cov = self.covered
        else:
            path = font_file_for_family(family)
            if path:
                try:
                    cov = _ttf_codepoints(path)
                except Exception:
                    cov = None
        self._cov_cache[key] = cov
        return cov

    def split_runs(self, text, covered):
        """
        把文本按「covered（主字体的覆盖集合）能否显示」切成 [(ok, 子串), ...]。
        ok=True 用主字体，False 用回退字体。covered 为 None/空 → 整段主字体。
        """
        if not covered:
            return [(True, text)]
        runs = []
        buf = ""
        cur = None
        for ch in text:
            ok = ord(ch) in covered
            if cur is None:
                cur = ok
                buf = ch
            elif ok == cur:
                buf += ch
            else:
                runs.append((cur, buf))
                cur = ok
                buf = ch
        if buf:
            runs.append((cur, buf))
        return runs


FONTS = FontSet()


def _strip_font_suffix(name):
    return re.sub(r"\s*\((?:TrueType|OpenType|All res|Noto)\)\s*$", "", name,
                  flags=re.I).strip()


def font_file_for_family(family):
    """
    按字体族名从注册表反查字体文件路径（含用户自装字体）。

    注册表两项：HKLM 是系统字体，HKCU 是「为当前用户安装」的字体——
    用户自己装的那些装饰字体就只在 HKCU 里，漏了会找不到。
    值名形如 "Microsoft YaHei & Microsoft YaHei UI (TrueType)"，
    所以要剥掉后缀、按 & / , 拆开逐个比对族名。
    """
    if winreg is None or not family:
        return None
    want = _strip_font_suffix(family).lower()
    windir = os.environ.get("WINDIR", r"C:\Windows")
    found = []
    for hive, sub in ((winreg.HKEY_LOCAL_MACHINE,
                       r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
                      (winreg.HKEY_CURRENT_USER,
                       r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")):
        try:
            key = winreg.OpenKey(hive, sub)
        except OSError:
            continue
        i = 0
        while True:
            try:
                name, val, _ = winreg.EnumValue(key, i)
            except OSError:
                break
            i += 1
            base = _strip_font_suffix(name)
            parts = [p.strip().lower() for p in re.split(r"[&,]", base)]
            if want in parts:
                if isinstance(val, str) and val:
                    found.append(val)
    for val in found:
        p = val if os.path.isabs(val) else os.path.join(windir, "Fonts", val)
        if os.path.exists(p):
            return p
    return None


def list_font_families():
    """Tk 能用的字体族列表（去掉 @ 开头的东亚竖排族名）。"""
    try:
        return sorted(set(f for f in tkfont.families() if not f.startswith("@")))
    except Exception:
        return []


# ---------------------------------------------------------------- 图标

class IconSet(object):
    """
    载入 logo/ 里的番茄女孩，供窗口图标、面板角标、右下角把手共用。

    注意：tk.PhotoImage 必须在 Tk 实例建好之后才能创建，所以不能放模块级。
    另外 PhotoImage 会被 GC 回收变成空白图，必须由本对象长期持有引用。
    """

    def __init__(self):
        self.big = None       # 原尺寸（32px），用于面板角标与窗口图标
        self.mid = None       # 缩小一半
        self.handle = None    # 64px 放大版，用于右下角把手
        self.path = None

    def load(self, master):
        if not os.path.exists(LOGO_PATH):
            return False
        try:
            img = tk.PhotoImage(master=master, file=LOGO_PATH)
        except Exception:
            return False
        self.path = LOGO_PATH
        self.big = img
        # 32px 的图放进 38px 标题栏里略显臃肿，缩一半更精致
        try:
            self.mid = img.subsample(2, 2)
        except Exception:
            self.mid = img
        self.handle = img
        if os.path.exists(LOGO_HANDLE_PATH):
            try:
                self.handle = tk.PhotoImage(master=master, file=LOGO_HANDLE_PATH)
            except Exception:
                pass
        return True

    @property
    def ok(self):
        return self.big is not None


ICONS = IconSet()


# ---------------------------------------------------------------- 数据

def normalize_punct(s):
    """把自定义字体没有的全角标点换成它自带的等价符号。"""
    return "".join(PUNCT_MAP.get(c, c) for c in s)


def clean_item(s):
    """释义清洗：去掉括号/学科标注里的补充说明，保持弹幕简短。"""
    s = re.sub(r"[（(].*?[)）]", "", s)
    s = re.sub(r"[【\[].*?[】\]]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().strip("；;· ").strip()


def parse_mean_cn(mean_cn):
    """
    把 "v. 请求；上诉；有吸引力；  n. 呼吁；吸引力"
    解析成 [("v.", ["请求", "上诉", "有吸引力"]), ("n.", ["呼吁", "吸引力"])]。
    双空格分隔词性块，分号分隔义项——百词斩的义项顺序本身就是按考频排的。
    """
    if not mean_cn:
        return []
    parts = [p.strip() for p in re.split(r"\s{2,}", str(mean_cn)) if p.strip()]
    senses = []
    for p in parts:
        m = POS_RE.match(p)
        if m:
            pos = m.group(1).lower()
            body = m.group(2).strip()
            items = [clean_item(x) for x in re.split(r"[；;]", body)]
            items = [x for x in items if x]
            senses.append((pos, items))
        else:
            extra = [clean_item(x) for x in re.split(r"[；;]", p)]
            extra = [x for x in extra if x]
            if senses:
                senses[-1][1].extend(extra)
            elif extra:
                senses.append(("", extra))

    # 百词斩的数据里同一个词性偶尔会分成好几块（如 viewpoint 有两个 n.），
    # 合并同词性并去重，否则弹幕上会出现「n.… n.…」这种重复词性。
    merged = []
    seen_pos = {}
    for pos, items in senses:
        if pos and pos in seen_pos:
            tgt = merged[seen_pos[pos]][1]
            for it in items:
                if it not in tgt:
                    tgt.append(it)
        else:
            if pos:
                seen_pos[pos] = len(merged)
            merged.append((pos, list(items)))
    return [s for s in merged if s[1]]


def pick_meanings(senses, max_total=2, max_pos=2, per_pos=2):
    """
    按考频顺序挑义项，多词性依次串联。

    规则：总义项数不超过 max_total；每个词性至少分到 1 个（保证多词性都露脸），
    剩下的名额再按顺序往前补，单个词性不超过 per_pos。
    """
    ps = list(senses[:max(1, max_pos)])
    out = []
    budget = max(1, int(max_total))
    for i, (pos, items) in enumerate(ps):
        if budget <= 0:
            break
        reserve = max(0, len(ps) - i - 1)      # 给后面的词性留名额
        can = min(len(items), max(1, per_pos), max(1, budget - reserve))
        can = min(can, budget)
        if can <= 0:
            break
        out.append((pos, items[:can]))
        budget -= can
    return out


def shorten_cn(cn, max_len):
    """过长释义按分号截断，保留尽量完整的前几个义项。"""
    if not cn:
        return ""
    if len(cn) <= max_len:
        return cn
    segs = [s for s in re.split(r"[；;]", cn) if s.strip()]
    out = ""
    for s in segs:
        if out:
            if len(out) + 1 + len(s) > max_len:
                break
            out += "；" + s          # 义项之间用中文分号（用户要求）
        else:
            if len(s) > max_len:
                return s[:max_len] + "…"
            out = s
    return (out + "…") if out else cn[:max_len] + "…"


def ensure_books_dir():
    """保证 books 目录存在（词书都在它下面，一本 .csv 就是一本）。"""
    try:
        if not os.path.isdir(BOOKS_DIR):
            os.makedirs(BOOKS_DIR)
    except Exception:
        return False
    return True


def ensure_fav_book():
    """保证 books\\已收藏单词.csv 存在（只写表头），这样它总会出现在词书下拉里。"""
    try:
        if not os.path.isdir(BOOKS_DIR):
            os.makedirs(BOOKS_DIR)
        # 旧版叫 favourite.csv：就地改名，别让宇已经收藏的词凭空消失
        old = os.path.join(BOOKS_DIR, LEGACY_FAV_NAME)
        if os.path.exists(old):
            if os.path.exists(FAV_BOOK_PATH):
                try:
                    os.remove(old)          # 两边都有（不该发生）→ 以新名为准
                except Exception:
                    pass
            else:
                try:
                    os.replace(old, FAV_BOOK_PATH)
                except Exception:
                    pass
        if not os.path.exists(FAV_BOOK_PATH):
            with open(FAV_BOOK_PATH, "w", encoding="utf-8-sig", newline="") as f:
                csv.DictWriter(f, fieldnames=BOOK_FIELDS,
                               lineterminator="\r\n").writeheader()
    except Exception:
        return False
    return True


def fav_row(w):
    """把一个弹幕词条整理成收藏词书的一行（列与其它词书完全一致）。"""
    return {
        "word": (w.get("word") or "").strip(),
        "accent": (w.get("accent") or "").strip(),
        # 原样保留 mean_cn（含词性块之间的双空格），否则词性会被合并
        "mean_cn": (w.get("mean_cn") or "").strip(),
    }


def write_fav_rows(rows):
    """
    整本重写收藏夹：UTF-8 BOM + CRLF + 按字母序 —— 与其它词书保持同一种手感
    （Excel 双击不乱码、行序稳定、便于肉眼 diff）。
    """
    try:
        ensure_fav_book()
        rows = sorted(rows, key=lambda r: (r.get("word") or "").lower())
        tmp = FAV_BOOK_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=BOOK_FIELDS,
                                lineterminator="\r\n")
            wr.writeheader()
            for r in rows:
                wr.writerow({k: r.get(k, "") for k in BOOK_FIELDS})
        os.replace(tmp, FAV_BOOK_PATH)     # 原子替换，别让半截文件留在盘上
        return True
    except Exception:
        return False


def list_books():
    """books\\ 下的词书列表：[(显示名, 完整路径), ...]，显示名 = 去掉扩展名的文件名。"""
    names = []
    try:
        names = [f for f in os.listdir(BOOKS_DIR) if f.lower().endswith(".csv")]
    except Exception:
        names = []
    out = [(os.path.splitext(f)[0], os.path.join(BOOKS_DIR, f)) for f in sorted(names)]
    return out


def resolve_book(cfg):
    """
    按 config 的 book 字段选出当前词书。存的是文件名；找不到（被删/改名）
    就退回第一本，保证永远有一本可用。
    """
    books = list_books()
    if not books:
        return None, None
    want = str(cfg.get("book") or "").strip()
    if want == LEGACY_FAV_NAME:          # 收藏夹改过名，旧 config 照样认得
        want = FAV_BOOK_NAME
    if want:
        for disp, path in books:
            if os.path.basename(path) == want or disp == want:
                return disp, path
    for disp, path in books:                  # 没记录过 → 用默认那本
        if os.path.basename(path) == DEFAULT_BOOK_NAME:
            return disp, path
    return books[0]


def load_words(path=DATA_CSV):
    """读取已学单词 CSV，构造弹幕条目。返回 list[dict]。"""
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            word = (r.get("word") or "").strip()
            if not word:
                continue
            senses = parse_mean_cn(r.get("mean_cn"))
            if not senses:
                senses = [("", [""])]
            rows.append(dict(
                word=word,
                accent=(r.get("accent") or "").strip(),
                # 原始释义串也要留着：收藏进 已收藏单词.csv 时要原样回写
                mean_cn=r.get("mean_cn") or "",
                senses=senses,
            ))
    return rows


def build_text(w, cfg):
    """
    单词 + 词性 + 中文释义；多词性时「词性+释义」后面接下一个「词性+释义」。
    例：appeal v. 请求  n. 呼吁
    """
    picked = pick_meanings(
        w["senses"],
        max_total=int(cfg.get("max_meanings", 2)),
        max_pos=int(cfg.get("max_pos", 2)),
        per_pos=int(cfg.get("per_pos_meanings", 2)),
    )
    segs = []
    for pos, items in picked:
        cn = shorten_cn("；".join(items), int(cfg.get("max_cn_len", 30)))
        segs.append(("%s %s" % (pos, cn)) if pos else cn)
    txt = w["word"] + "  " + "  ".join([s for s in segs if s.strip()])
    return normalize_punct(txt).strip()


# ---------------------------------------------------------------- 弹幕层

class DanmakuLayer(object):
    """
    透明、鼠标穿透的弹幕画布。

    性能要点：窗口**只有弹幕带那么高**，不是整屏。
    整屏 layered 窗口每帧都要重新合成 3120×2080 像素，掉帧就是这么来的；
    缩到一条带后合成量降一个数量级，配合 1ms 时钟分辨率能稳定跑满帧。
    """

    def __init__(self, master, cfg, sw, sh, fonts):
        self.cfg = cfg
        self.sw = sw
        self.sh = sh
        self.fonts = fonts
        self.win = tk.Toplevel(master)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        # 注意：这里**故意不用** -transparentcolor，它在 Windows 上不生效（实测会糊成黑块），
        # 统一改用下面的 apply_layered() 手动上色键。
        self.win.config(bg=TRANSPARENT_KEY)
        self.canvas = tk.Canvas(self.win, width=sw, height=100,
                                bg=TRANSPARENT_KEY, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self.items = []       # [dict(tag, x, y, w, slot, word, frozen)]
        self.paused = False   # 暂停 = 冻结移动与出新词，**不清屏**
        # 大写锁定打开时 interactive=True：撤掉穿透，弹幕可悬停 / 可点收藏
        self.interactive = False
        self.fav_state = None     # (word) -> bool，由 App 注入
        self.fav_toggle = None    # (word_dict) -> bool，切换收藏并返回新状态
        self._hover = None        # 当前被悬停、已冻结的那一条
        self._hover_job = None
        self._seq = 0
        self._last_t = time.perf_counter()
        self._acc = 0.0       # 亚像素余量，保证每次只按整数像素移动

        # —— 渲染缓存 ——
        # 掉帧的头号元凶不是「移动」，而是 spawn 那一瞬间：
        # 新建 tkfont.Font、对长文本反复 measure、拼字符串，全在 Tk 主线程上，
        # 一次能卡住十几毫秒（肉眼就是「顿一下」）。这些结果都能按 key 复用。
        self._font_cache = {}    # (family, px, bold) -> tkfont.Font
        self._width_cache = {}   # (font_key, 文本) -> 像素宽度
        self._applied_alpha = None   # 上次设过的 alpha，相同就别再调 SetLayered…
        self._applied_through = None # 上次设过的穿透态：切模式时 alpha 常常没变，
                                     # 只比 alpha 会把「切回穿透」整个跳过去

        self.band_h = 0
        self.top = 0
        self._geo = None      # 当前窗口 geometry 字符串，用于 relayout 幂等判断
        self.relayout()

        self.win.update_idletasks()
        self.win.update()
        hwnd = self.win.winfo_id()
        # tkinter 的 Toplevel 有时需要先取父级句柄，才是真正的顶层 HWND
        parent = ctypes.windll.user32.GetParent(hwnd)
        self.hwnd = parent if parent else hwnd
        self.refresh_layered()
        # 点星星收藏；悬停靠定时查光标位置，不用 <Motion>（见 _hover_poll）
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self._hover_job = self.win.after(HOVER_POLL_MS, self._hover_poll)

    def refresh_layered(self):
        """
        色键穿透 + 整体不透明度。

        穿透与否由 self.interactive 决定：
          大写锁定关 = 穿透（弹幕不挡桌面操作，这是默认手感）；
          大写锁定开 = 不穿透（弹幕可悬停、可点击收藏）。

        alpha 没变、穿透态也没变就**直接返回**：拖不透明度滑块时每次改参数都重设
        layered 属性，会让整块窗口强制重绘一次，这正是拖动卡顿的来源之一。
        注意 through 也必须一起比 —— 从「穿透」切回「不穿透」时 alpha 常常恰好
        没变，只比 alpha 的话这次切换就被跳过了，弹幕永远点不着。
        """
        a = int(float(self.cfg.get("opacity", 0.92)) * 255)
        through = not self.interactive
        if a == self._applied_alpha and through == self._applied_through:
            return
        self._applied_alpha = a
        self._applied_through = through
        apply_layered(self.hwnd, TRANSPARENT_KEY, through, a)

    def set_interactive(self, enabled):
        """切换「可交互」模式（大写锁定开）。"""
        enabled = bool(enabled)
        if enabled == self.interactive:
            return
        self.interactive = enabled
        if not enabled:
            self._set_hover(None)      # 退出交互态：解冻并收起信息框
        self.refresh_layered()

    def set_paused(self, paused):
        """
        暂停 / 继续。暂停只冻结运动与出新词，画面上的弹幕停在原地
        （用户明确要求：暂停后不能清屏，继续时接着走）。
        """
        self.paused = bool(paused)
        self._last_t = time.monotonic()   # 重置时间基线，继续的那一帧不会瞬移
        self._acc = 0.0

    # -- 布局 ----------------------------------------------------

    def _font_px(self):
        return max(10, int(self.sh * float(self.cfg.get("font_ratio", 0.036))))

    def _band_span(self):
        """弹幕带的像素高度与纵向起点。"""
        font_px = self._font_px()
        band = max(int(self.sh * float(self.cfg.get("band_ratio", 0.15))),
                   int(font_px * 1.7))
        band = int(min(band, self.sh))
        mode = self.cfg.get("band_mode", "top")
        if mode == "middle":
            top = int((self.sh - band) / 2.0)
        elif mode == "bottom":
            top = int(self.sh - band)
        elif mode == "random":
            top = int(random.uniform(0, max(0, self.sh - band)))
        else:  # top —— 默认：屏幕上方
            top = 0
        return band, max(0, top)

    def relayout(self):
        """重设窗口为「一条带」的大小与位置；配置变化或 random 模式换带时调用。"""
        band, top = self._band_span()
        geo = "%dx%d+%d+%d" % (self.sw, band, 0, top)
        if geo == self._geo:      # 幂等：位置尺寸没变就不动窗口，省一次重绘
            return
        self._geo = geo
        self.band_h, self.top = band, top
        self.win.geometry(geo)
        self.canvas.config(width=self.sw, height=band)

    # -- 渲染缓存 ------------------------------------------------

    def _font(self, family, px, bold=False):
        """按 (族名, 像素, 粗体) 复用 tkfont.Font —— 新建字体对象是一次 Tcl 往返。"""
        key = (family, px, bool(bold))
        f = self._font_cache.get(key)
        if f is None:
            if len(self._font_cache) > 48:    # 拖字号滑块会造一堆，及时回收
                self._font_cache.clear()
                self._width_cache.clear()
            f = tkfont.Font(family=family, size=-px,
                            weight="bold" if bold else "normal")
            self._font_cache[key] = f
        return f

    def _measure(self, font, font_key, s):
        """缓存文本宽度：缩略到 78% 屏宽的那个 while 循环会反复量同一批子串。"""
        k = (font_key, s)
        v = self._width_cache.get(k)
        if v is None:
            v = font.measure(s)
            if len(self._width_cache) > 3000:
                self._width_cache.clear()
            self._width_cache[k] = v
        return v

    def _pick_y(self, font_px):
        """
        在弹幕带里挑一个纵向位置，返回 (轨道号, y)。
        一次一条时带内连续随机（更自然）；多条同屏时按轨道分配。

        判定标准不是「这行现在有没有词」，而是「这条放进去会不会撞上」：
        所有弹幕**同速左移**，入场瞬间不重叠就永远不重叠，所以只要已有那条
        的右边缘离入场点还有一个身位，这行就能再排一条 —— 不必等它整条走完
        （这也是为什么不用传入新弹幕的宽度：它一定在最右侧入场）。

        唯一的例外是**被悬停冻住的那条**：它不动，新弹幕迟早追上去叠在一起。
        所以冻结期间整行视为占用 —— 这正是要的「悬停时才允许重叠」：
        重叠只发生在悬停期间，而且悬停结束后它能干干净净地走掉，不会被新来的
        一条接一条地续上、永远等不到空隙。

        全部轨道都排不进去才返回 (None, None)。
        """
        band = self.band_h
        line_h = font_px * 1.25
        margin = max(2, int(band * 0.05))
        ymax = max(margin, band - line_h - margin)
        slots = max(1, int((band - 2 * margin) // line_h))
        if int(self.cfg.get("max_on_screen", 1)) <= 1 or slots <= 1:
            y = margin if ymax <= margin else random.uniform(margin, ymax)
            return -1, y

        enter_x = float(self.sw + ENTER_X_PAD)
        gap = max(12, int(font_px * 0.45))
        same_row = font_px * 1.05        # 纵向差在这个范围内算同一行
        cand = []
        for s in range(slots):
            y0 = margin + s * line_h
            ok = True
            for it in self.items:
                if abs(float(it["y"]) - y0) >= same_row:
                    continue
                if it.get("frozen"):     # 静止不动 → 迟早被追上，整行放弃
                    ok = False
                    break
                if float(it["x"]) + float(it["w"]) + gap > enter_x:
                    ok = False           # 入场瞬间就会贴上，等它再走远一点
                    break
            if ok:
                cand.append(s)
        if not cand:
            return None, None
        s = random.choice(cand)
        y = margin + s * line_h + random.uniform(0, line_h * 0.12)
        return s, min(y, ymax)

    # -- 生成 ----------------------------------------------------

    def drop_oldest(self):
        """销毁最早放出的那一条（「来一条」撞上同屏上限时的替换策略）。"""
        if not self.items:
            return False
        it = self.items[0]
        if it is self._hover:      # 别把焦点留在一条马上要被删掉的弹幕上
            self._set_hover(None)
        self.items.remove(it)
        self.canvas.delete(it["tag"])
        self._drop_park_ui(it)
        return True

    def spawn(self, text, color=None, replace_oldest=False, word=None):
        """
        放一条弹幕。

        replace_oldest=True（面板上「来一条」专用）：同屏已满或者轨道占满时，
        先**销毁最老的那条**再放新词，而不是把这次点击悄悄丢掉。
        自动节奏仍走 replace_oldest=False —— 该跳过的拍子照旧跳过，节奏才稳定。

        word = 这个词的原始词条（dict）。悬停信息框要拿它的音标，
        点收藏时还要靠它把整行写进 books\\已收藏单词.csv，所以必须一起带上。
        """
        cfg = self.cfg
        max_on = int(cfg.get("max_on_screen", 1))
        if len(self.items) >= max_on:
            if not replace_oldest:
                return False
            self.drop_oldest()
        if cfg.get("band_mode", "top") == "random":
            self.relayout()          # 随机模式：每次换一条带

        font_px = self._font_px()
        # 注意：tkfont 的 size 传正数是「点」，会在高分屏上被再放大数倍；
        # 传负数才是「像素」，这也是我们要的精确控制方式。
        fam = self.fonts.family(cfg)
        fall = cfg.get("font_face", "Microsoft YaHei")
        fk_main, fk_fall = (fam, font_px, False), (fall, font_px, True)
        f_main = self._font(fam, font_px)          # 走缓存，别每次 new
        f_fall = self._font(fall, font_px, True)
        # 主字体的覆盖范围：画不出的字（如萝莉体缺全角分号）自动走回退字体
        covered = self.fonts.coverage(fam)

        pad = max(8, font_px // 3)  # 描边余量
        # 兜底：释义再长也不能让单条弹幕宽过屏幕的 78%，否则会横穿整屏看不清
        limit = self.sw * 0.78

        def layout(t):
            rs = self.fonts.split_runs(t, covered)
            tot = sum(self._measure(f_main if ok else f_fall,
                                    fk_main if ok else fk_fall, s)
                      for ok, s in rs) + pad
            return rs, tot

        runs, total = layout(text)
        while total > limit and len(text) > 6:
            text = text[:-2] + "…"
            runs, total = layout(text)

        slot, y = self._pick_y(font_px)
        if slot is None:
            if not replace_oldest:
                return False     # 带里没空轨道了，这一拍不弹（避免叠字）
            self.drop_oldest()   # 手动「来一条」：腾一条轨道也要弹出来
            slot, y = self._pick_y(font_px)
            if slot is None:
                return False

        if color is None:
            color = (random.choice(PALETTE) if cfg.get("random_color")
                     else cfg.get("text_color", "#FFFFFF"))

        self._seq += 1
        tag = "dm%d" % self._seq
        x = float(self.sw + 10)
        ys = int(y)
        # 首选路径：整条弹幕（8 向描边 + 正文）预渲染成**一张位图**。
        # 这样一条弹幕在 canvas 上只占 1 个 image item —— 每帧的重绘成本从
        # "9 × 段数 次文本光栅化"降到"1 次位图 blit"，帧率与同屏条数脱钩。
        img = None
        met = f_main.metrics()
        bmp = render_text_bitmap(runs, font_px, fam, fall, _hex_rgb(color),
                                 met.get("ascent", int(font_px * 0.8)),
                                 met.get("linespace", int(font_px * 1.2)))
        if bmp is not None:
            bw, bh, ppm, ox, oy = bmp
            try:
                img = tk.PhotoImage(data=ppm)
                self.canvas.create_image(x - ox, ys - oy, anchor="nw",
                                         image=img, tags=(tag, "dm"))
            except Exception:
                img = None
        if img is None:
            # 退路：GDI 出问题时仍走逐段 text + 8 向描边（慢，但画质一模一样）
            ov = max(1, font_px // 22)
            ov2 = max(1, (ov * 7) // 10)     # 斜角副本略短一点，抵掉 √2 的几何拉伸
            offs = stroke_offsets(ov, ov2)
            cx = x
            for ok, s in runs:
                f = f_main if ok else f_fall
                for dx, dy in offs:
                    self.canvas.create_text(cx + dx, ys + dy, text=s, anchor="nw",
                                            fill="#000000", font=f, tags=(tag, "dm"))
                self.canvas.create_text(cx, ys, text=s, anchor="nw",
                                        fill=color, font=f, tags=(tag, "dm"))
                cx += self._measure(f, fk_main if ok else fk_fall, s)

        # 新建的 item 天然就在最上层，原先那句 tag_raise("dm") 纯属多余的开销
        # _img 是 PhotoImage 的**强引用**：Tk 只管画，Python 一回收图片就变空白
        self.items.append(dict(tag=tag, x=float(x), y=float(ys), w=float(total),
                               slot=slot, word=word, frozen=False, _img=img))
        # 但悬停期间别让新来的盖住焦点：新弹幕是后画的，不提一把就会压在
        # 信息框上面（悬停的信息框会探到相邻轨道去，所以跨行也得提）。
        self._raise_hover()
        return True

    # -- 每帧 ----------------------------------------------------

    def tick(self):
        # 按真实时间差推进，而不是「假设 60fps 每帧固定步长」：
        # tkinter 的 after() 在默认 15.6ms 时钟分辨率下只有 30fps 左右。
        # perf_counter 是最高精度的单调时钟，monotonic 在 Windows 上精度略逊。
        now = time.perf_counter()
        dt = now - self._last_t
        self._last_t = now
        if self.paused:
            self._acc = 0.0     # 暂停：弹幕保持在原位，等继续
            return
        if not self.items:
            self._acc = 0.0
            return
        dt = min(dt, 0.25)   # 卡顿/休眠后不要一次跳很远
        self._acc += self.sw * float(self.cfg.get("speed_ratio", 0.11)) * dt
        step = int(self._acc)        # 只按整数像素移动：避免亚像素导致每帧重新抗锯齿
        if step < 1:
            return
        self._acc -= step
        # 一条 Tcl 命令移动全体：所有弹幕（含描边）共用 "dm" tag，
        # 逐条 canvas.move() 时同屏 8 条就是每帧 8 次 Tcl 往返，合并后只剩 1 次。
        self.canvas.move("dm", -step, 0)
        i = 0
        while i < len(self.items):
            it = self.items[i]
            # 被悬停冻结的那条停在原地；正在冲刺让路的那条已从 "dm" 组摘走，
            # 位移由 _tick_boost 自己算（这里再减一次就会和实际位置对不上）
            if not it.get("frozen") and not it.get("boost"):
                it["x"] -= step
            if it["x"] + it["w"] < -20:
                if it is self._hover:
                    self._set_hover(None)
                self.canvas.delete(it["tag"])
                self._drop_park_ui(it)
                del self.items[i]        # 别用 list() 再 remove()，就地删更省
            else:
                i += 1
        # 正在冲刺让路的那几条：补上超出常速的位移
        self._tick_boost(step)
        # 悬停结束后还在排队等让路的那几条：挡路的走过去了就放行
        self._retry_waiting()

    # -- 悬停交互（大写锁定开启时）-------------------------------
    #
    # 命中检测不走 <Motion> 事件，而是每 HOVER_POLL_MS 主动查一次真实光标位置：
    # 弹幕层是色键抠洞的 layered 窗口，被抠掉的像素会让鼠标"漏"过去，
    # 洞口边缘的 crossing 事件会时有时无；直接拿 winfo_pointerxy 和窗口原点相减，
    # 与事件派发完全无关，掉帧或鼠标不动时也不会漏判。

    def _stop_hover_poll(self):
        if self._hover_job is not None:
            try:
                self.win.after_cancel(self._hover_job)
            except Exception:
                pass
            self._hover_job = None

    def _hover_poll(self):
        self._hover_job = None
        try:
            if not self.win.winfo_exists():
                return
        except Exception:
            return
        try:
            if self.interactive:
                it = self._item_at_cursor()
                if it is not self._hover:
                    self._set_hover(it)
            elif self._hover is not None:
                self._set_hover(None)
        except Exception:
            pass
        try:
            self._hover_job = self.win.after(HOVER_POLL_MS, self._hover_poll)
        except Exception:
            self._hover_job = None

    @staticmethod
    def _inside(bb, cx, cy, pad=0):
        return bool(bb) and (bb[0] - pad <= cx <= bb[2] + pad
                             and bb[1] - pad <= cy <= bb[3] + pad)

    def _item_at_cursor(self):
        """光标（画布坐标）压在哪条弹幕上；没有就 None。"""
        try:
            px, py = self.win.winfo_pointerxy()
            cx = px - self.win.winfo_rootx()
            cy = py - self.win.winfo_rooty()
        except Exception:
            return None
        if cx < -6 or cy < -6 or cx > self.sw + 6 or cy > self.band_h + 6:
            return None
        # 已在悬停的那条**优先判定**，而且两步都走：
        # ① 整块信息框 —— 鼠标移到下面的音标/星上不算离开（否则刚想点星就先失焦）；
        # ② 文字本身 —— hitbox 万一因绘制失败缺了，还有个兜底。
        # 这一步必须排在遍历之前：悬停期间允许别的弹幕从它身后穿过，
        # 那条路过的即使此刻也压在光标下，也不该把焦点抢走 ——
        # 用户看到的最上层始终是这一条，焦点就得跟视觉一致。
        if self._hover is not None:
            if self._inside(self._hover.get("_hitbox"), cx, cy):
                return self._hover
            if self._inside(self.canvas.bbox(self._hover["tag"]), cx, cy, 5):
                return self._hover
        for it in reversed(self.items):        # 后放的在上层，优先命中
            if it is self._hover:
                continue
            if self._inside(self.canvas.bbox(it["tag"]), cx, cy, 5):
                return it
        return None

    def _set_hover(self, it):
        old = self._hover
        if old is not None and old is not it:
            self._unfreeze(old)      # 可能转成 waiting：原地排队等挡路的过去
        self._hover = it
        # 悬停结束、但那条还在排队让路 —— 灰框得**继续挂着**，一直挂到它真的动起来。
        # 一撤框就变成「停着不动的裸单词」，看着像卡死了。
        if old is not None and old is not it and old.get("waiting"):
            self._park_hover_ui(old)
        try:
            self.canvas.delete("hoverui")
        except Exception:
            pass
        if it is None:
            return
        if it.get("_park_tag"):
            # 又悬停回还在排队的那条：它一直没动，框也不用重画，认领回来就行
            self._claim_hover_ui(it)
            return
        it.pop("_hitbox", None)
        it.pop("_star_box", None)
        w = it.get("word")
        if self.fav_state and w:
            it["_fav"] = bool(self.fav_state(w.get("word")))
        self._freeze(it)
        try:
            self._draw_hover(it)
        except Exception:
            pass

    # -- 灰框的「留存 / 认领 / 撤下」 ------------------------------------
    # 排队让路的那条是静止的，但它的灰框要一直挂着。而框默认只挂在全局
    # "hoverui" 这一个 tag 上，下一次 _set_hover 会把整组删掉 —— 所以留存时
    # 必须改挂到这一条自己的 tag 上，等它恢复移动了再撤。

    def _park_hover_ui(self, it):
        """把当前信息框从 hoverui 上摘下来，改挂到这一条的私有 tag 上留存。"""
        self._seq += 1
        tag = "hoveruip%d" % self._seq
        try:
            for i in self.canvas.find_withtag("hoverui"):
                self.canvas.dtag(i, "hoverui")
                self.canvas.addtag_withtag(tag, i)
                self.canvas.addtag_withtag("hoveruipark", i)
        except Exception:
            return
        it["_park_tag"] = tag

    def _claim_hover_ui(self, it):
        """重新悬停回等待中的那条：把它自己那块框认领成当前 hoverui。"""
        tag = it.pop("_park_tag", None)
        if not tag:
            return
        try:
            for i in self.canvas.find_withtag(tag):
                self.canvas.dtag(i, tag)
                self.canvas.dtag(i, "hoveruipark")
                self.canvas.addtag_withtag("hoverui", i)
        except Exception:
            pass

    def _drop_park_ui(self, it):
        """这一条恢复移动（或被删掉）了 —— 挂着的灰框到此为止。"""
        tag = it.pop("_park_tag", None)
        if tag:
            try:
                self.canvas.delete(tag)
            except Exception:
                pass

    def _freeze(self, it):
        """
        把这条从「运动组」里摘出去。

        tick 里用一句 canvas.move("dm") 移动全体，省掉逐条 Tcl 往返；
        要冻结某一条就只能改它的标签，不能为它把整条快路径废掉。
        """
        if it.get("frozen"):
            return
        it["frozen"] = True
        self.canvas.dtag(it["tag"], "dm")
        self.canvas.addtag_withtag("dmfrozen", it["tag"])

    def _raise_hover(self):
        """
        把「悬停信息框 + 被悬停的那一条」顶到最上层。
        新弹幕是后画的，天然压在老弹幕上面；悬停期间同轨道允许后来者穿过，
        所以每放一条都要把焦点这一组重新提上来，否则它会被路过的弹幕盖住。
        排队让路期间挂着的那些灰框（hoveruipark）同样要提 —— 它们此刻没有焦点，
        但还在画面上，被路过的弹幕盖掉一半比留着更丑。
        """
        try:
            self.canvas.tag_raise("hoveruipark")
        except Exception:
            pass
        if self._hover is None:
            return
        try:
            self.canvas.tag_raise("hoverui")
            self.canvas.tag_raise(self._hover["tag"])
        except Exception:
            pass

    def _row_gap(self):
        """判定「同一行」的纵向阈值 + 两条弹幕之间要留的水平空隙。"""
        fp = self._font_px()
        return fp * 1.05, max(12, int(fp * 0.45))

    def _blockers(self, it):
        """
        此刻压在 it 身上的那几条（同一行且水平相交 —— 差距在 gap 之内就算压上）。

        当前悬停的那条要排除在外：它自己是静止的，如果把它算成障碍，
        就会出现「A 等 B、B 等 A」的死等（两个都不动，谁也不让谁）。
        让别的弹幕从悬停那条身上穿过去是没问题的 —— 悬停那条永远在最上层，
        视觉上就是"路过的那条从它身后飘过"，不会糊。
        """
        row, gap = self._row_gap()
        out = []
        for o in self.items:
            if o is it or o is self._hover:
                continue
            if abs(float(o["y"]) - float(it["y"])) >= row:
                continue
            if (float(o["x"]) < float(it["x"]) + float(it["w"]) + gap
                    and float(it["x"]) < float(o["x"]) + float(o["w"]) + gap):
                out.append(o)
        return out

    def _blocked(self, it):
        return bool(self._blockers(it))

    def _boost_safe(self, b):
        """
        给 b 加速前先看它**正前方**（左边）有没有贴得太近的邻居。

        冲刺只是临时倍速，追尾了反而更糊，那还不如老实等（退回 waiting）。
        """
        row, gap = self._row_gap()
        bx = float(b["x"])
        for o in self.items:
            if o is b:
                continue
            if abs(float(o["y"]) - float(b["y"])) >= row:
                continue
            right = float(o["x"]) + float(o["w"])
            if right <= bx and bx - right < gap:
                return False
        return True

    def _release(self, it):
        """真正恢复移动：从冻结组回到运动组，并收掉排队的灰框。"""
        it["waiting"] = False
        it.pop("_wait_t", None)
        if it.get("frozen"):
            it["frozen"] = False
            self.canvas.dtag(it["tag"], "dmfrozen")
            self.canvas.addtag_withtag("dm", it["tag"])
        self._drop_park_ui(it)

    def _unfreeze(self, it):
        """
        解除冻结，恢复移动。

        悬停期间允许后来者从它身上穿过去，鼠标一移开要是立刻同速跟上，就会和
        正压在身上的那条**糊在一起飘走**。老办法是把悬停词冻在原地等对方走完，
        但一等就是好几秒，看着像卡死。

        现在的做法：**让挡路的那条冲刺让路** —— 给它一个临时倍速（BOOST_MULT），
        快速从悬停词身上越过去，悬停词当场恢复移动。只有当冲刺会追尾前面的
        邻居时，才退回"原地排队等"的老兜底（由 _retry_waiting 每帧复查）。
        """
        if not it.get("frozen"):
            return
        blockers = self._blockers(it)
        if not blockers:
            self._release(it)
            return
        if all(self._boost_safe(b) for b in blockers):
            for b in blockers:
                b["boost"] = BOOST_MULT
                b["_boosting"] = it["tag"]
                # 从整体运动组摘出来单独加速（同 _freeze 的手法：换标签不动快路径）
                self.canvas.dtag(b["tag"], "dm")
                self.canvas.addtag_withtag("dmboost", b["tag"])
            self._release(it)
            return
        it["waiting"] = True
        it["_wait_t"] = time.perf_counter()

    def _end_boost(self, b):
        """冲刺结束：回到常速运动组。"""
        b.pop("boost", None)
        b.pop("_bacc", None)
        b.pop("_boosting", None)
        self.canvas.dtag(b["tag"], "dmboost")
        self.canvas.addtag_withtag("dm", b["tag"])

    def _tick_boost(self, step):
        """
        推进正在冲刺让路的那几条（它们已从 "dm" 组摘出来，整体那句
        canvas.move("dm") 不再管它们，所以从常速到加速全在这里走）。

        位移按**浮点累计后取整**，而不是每帧 int(step*mult)：慢速时 step 小，
        取整会把倍速吃掉（int(1*2.6)=2 还行，int(1*1.3)=1 就等于没加速）。
        """
        if not any(it.get("boost") for it in self.items):
            return
        row, gap = self._row_gap()
        for b in self.items:
            mult = b.get("boost")
            if not mult:
                continue
            b["_bacc"] = b.get("_bacc", 0.0) + step * mult
            ex = int(b["_bacc"])
            if ex:
                b["_bacc"] -= ex
                self.canvas.move(b["tag"], -ex, 0)
                b["x"] -= ex
            tgt = None
            for o in self.items:
                if o["tag"] == b.get("_boosting"):
                    tgt = o
                    break
            # 目标没了（飘出屏幕/被顶掉），或者已经整个越过去了 → 收工
            if tgt is None or not (
                    float(b["x"]) < float(tgt["x"]) + float(tgt["w"]) + gap
                    and float(tgt["x"]) < float(b["x"]) + float(b["w"]) + gap):
                self._end_boost(b)

    def _retry_waiting(self):
        """每帧复查排队等让路的那几条：挡路的走过去了就放行。"""
        if not any(it.get("waiting") for it in self.items):
            return
        now = time.perf_counter()
        for it in self.items:
            if not it.get("waiting"):
                continue
            waited = now - it.get("_wait_t", now)
            # 超时兜底：叠得再离谱也不能让它永远停在原地不动
            if not self._blocked(it) or waited > UNFREEZE_WAIT_MAX:
                self._release(it)      # 真动起来了 —— 灰框这时候才收

    # -- 悬停信息框的绘制 -----------------------------------------

    def _round_rect(self, x0, y0, x1, y1, r, **kw):
        """Tk 没有圆角矩形：用 smooth 折线凑一个（相邻两点重合处被抹成圆角）。"""
        r = max(0.0, min(r, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
               x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
               x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        kw.setdefault("tags", ("hoverui",))
        return self.canvas.create_polygon(pts, smooth=True, splinesteps=10, **kw)

    @staticmethod
    def _star_pts(cx, cy, r, inner=0.44):
        """五角星的 10 个顶点（外/内交替），尖角朝上。"""
        pts = []
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5
            rr = r if i % 2 == 0 else r * inner
            pts += [cx + rr * math.cos(ang), cy + rr * math.sin(ang)]
        return pts

    def _fit(self, font, s, max_w):
        """把字符串裁到 max_w 像素内，超了补省略号。"""
        if max_w <= 8 or font.measure(s) <= max_w:
            return s
        out = s
        while out and font.measure(out + "…") > max_w:
            out = out[:-1]
        return (out + "…") if out else ""

    def _draw_hover(self, it):
        """
        悬停信息框：圆角灰底 + 下方一行「音标 … ★」。

        半透明为什么用 stipple 而不是 alpha？
        layered 窗口只有一个**全局** alpha，做不到"只有这块半透明"；
        而 stipple 是把填充按棋盘格漏空，漏空的像素露出画布底色 ——
        那正是色键色，会被整块抠掉。于是一半像素直接透出桌面，
        视觉上就是半透明的，而且是真·逐像素（不是靠猜灰阶）。
        """
        c = self.canvas
        bb = c.bbox(it["tag"])
        if not bb:
            return
        fp = self._font_px()
        pad = max(10, int(fp * 0.34))          # 框与弹幕文字之间的外留白
        ipad = pad + max(6, int(fp * 0.22))    # 信息行内容再往里收一档，别贴边
        gap = max(10, int(fp * 0.30))          # 音标与星星之间也要留口气
        row_h = max(22, int(fp * 0.82))
        # 竖直留白要按**墨迹**算：字体行盒（bbox）上下各有一截"字体自己留的白"，
        # 直接拿 bbox 当下沿 → 信息行会贴着框底、看着比上面挤。
        asc_pad = int(fp * 0.16)
        desc_pad = int(fp * 0.28)
        vgap = max(8, int(fp * 0.24))          # 单词墨迹↔音标墨迹 / 信息行↔框边，两边一样
        x0, y0, x1, y1 = bb
        ink_top, ink_bot = float(y0 + asc_pad), float(y1 - desc_pad)
        bx0, bx1 = float(x0 - pad), float(x1 + pad)
        # 音标是 anchor="w"（居中的是**行盒**不是墨迹）再叠 ty 的光学修正，
        # 所以墨迹在行盒里整体偏上：行盒顶往下 `ink_top_in_row` 才是音标墨迹顶。
        # 翻到文字上方时必须按墨迹算行盒 —— 否则会白留出那一截，
        # 看着就是"最下行的音标离单词比上面两行远"。
        fpx0 = max(12, int(fp * 0.62))
        ink_top_in_row = row_h / 2.0 - 0.62 * fpx0
        # 翻到文字上方时要用「行盒顶 → 墨迹**底**」：≈ 墨迹顶 + 墨迹高（0.94em）。
        # 这个数是从**实拍像素**里标定的（`_debug\_hovgap.py` 会把三行的墨迹间距
        # 都量出来），别在纸上推 —— 推出来的值会让上面那行近 4px。
        # 0.50 是在两种字号（fp≈45 / ≈74）下都量过一遍的折中值；这套坐标本身就
        # 有 ±1~2px 的噪声下限（画布取整 + 描边抗锯齿），所以两边间距差 ≤2px 即达标。
        ink_bot_in_row = row_h / 2.0 + 0.41 * fpx0
        if ink_bot + vgap + (row_h - ink_top_in_row) + vgap <= self.band_h - 2:
            # 默认：文字下方。音标墨迹顶离单词墨迹底正好 vgap
            row_top = ink_bot + vgap - ink_top_in_row
            top, bot = ink_top - pad, row_top + row_h + vgap
        else:                                  # 已经贴到带底，整条翻到文字上方
            # 镜像：音标墨迹**底**离单词墨迹**顶**也是 vgap —— 与下方那种逐像素对称
            row_top = ink_top - vgap - ink_bot_in_row
            top, bot = row_top - vgap, ink_bot + pad
        top, bot = max(0.0, top), min(float(self.band_h), bot)
        cy = row_top + row_h / 2.0

        word = it.get("word") or {}
        acc = (word.get("accent") or "").strip()
        fpx = fpx0                      # 音标字号（上面算行盒位置时已经取过同一个值）
        # 音标**固定微软雅黑**，不跟弹幕正文的萝莉体走 —— 萝莉体画 IPA 又细又飘。
        # 字重用**常规**、不加粗：花底 + 小字号下粗体笔画容易糊成一团，反而难认
        # （`_hovercheck.py` 里有断言盯着「必须是常规字重」）。
        # 也别再按"缺字"把音标拆成多段：实测 msyh.ttc 的 cmap 会被自己的解析器
        # **误报**（ə ɜ ɪ ˈ ː 全判成缺），一拆就混进 Segoe UI，两段字距肉眼可见地不齐。
        # 而雅黑本身这些 IPA 符号一个不缺（`_debug\\_fonttest.py` 渲染对照过）。
        phf = self._font(PHON_FACE, fpx, False)
        sr = max(8, int(fp * 0.32))

        # 信息行比正文还宽时（短单词 + 长音标），把框往右撑到装得下
        need = ipad + (phf.measure(acc) if acc else 0) + gap + sr * 2 + ipad
        if bx1 - bx0 < need:
            bx1 = bx0 + need
        bx1 = min(bx1, float(self.sw - 2))
        bx0 = max(0.0, min(bx0, bx1 - 40))

        box = self._round_rect(bx0, top, bx1, bot, max(6, int(fp * 0.22)),
                               fill=CLR_HOVER_BG, stipple="gray50",
                               outline=CLR_HOVER_BRD,
                               width=max(1, int(fp * 0.03)))
        # 框刚建出来就在最上层：先把被悬停的那条文字提到框上面（文字不能被糊住），
        # 再画下面的音标和星。这样其它路过的弹幕都在框底下 —— 只有被悬停的这一条
        # 会压在框上，不会出现"灰底上又叠着别人家的字"那种乱。
        try:
            c.tag_raise(it["tag"])
        except Exception:
            pass

        txt_l = bx0 + ipad
        txt_r = bx1 - ipad - sr * 2 - gap
        # 光学修正：anchor="w" 是把**字体行盒**按 cy 居中，而音标的墨迹（x 高区
        # 加上 / 和 p 的下伸）整体偏下，实测比行盒中心低约 0.15em。不修的话
        # 音标看着比右边的星低半个笔画。星星是几何图形，它就在 cy 上。
        ty = cy - fpx * 0.15
        if acc and txt_r > txt_l:
            # 不描边、不打暗影：描边会把 IPA 符号糊成一坨，暗影又像"带边框"
            seg = self._fit(phf, acc, txt_r - txt_l)
            if seg:
                c.create_text(txt_l, ty, text=seg, anchor="w", fill=CLR_HOVER_TEXT,
                              font=phf, tags=("hoverui",))
        # 收藏星：一律实心。空心星看着更雅，但中间的可点区域是空的 ——
        # 抠洞像素会把点击漏给桌面，所以宁可用实心保证"点了就有反应"。
        scx = bx1 - ipad - sr
        fav = bool(it.get("_fav"))
        c.create_polygon(self._star_pts(scx, cy, sr),
                         fill=CLR_STAR_ON if fav else CLR_STAR_OFF,
                         outline=CLR_STAR_ON_BR if fav else CLR_STAR_OFF_BR,
                         width=max(1, int(sr * 0.20)), tags=("hoverui",))
        it["_star_box"] = (scx - sr - 3, cy - sr - 3, scx + sr + 3, cy + sr + 3)
        it["_hitbox"] = (bx0 - 6, top - 6, bx1 + 6, bot + 6)

    def _on_canvas_click(self, e):
        """点星星 = 收藏 / 取消收藏（只在可交互模式下生效）。"""
        if not self.interactive or not self.fav_toggle:
            return
        it = self._hover if self._hover is not None else self._item_at_cursor()
        if it is None:
            return
        sb = it.get("_star_box")
        if not sb or not (sb[0] <= e.x <= sb[2] and sb[1] <= e.y <= sb[3]):
            return
        w = it.get("word")
        if not w:
            return
        try:
            it["_fav"] = bool(self.fav_toggle(w))
        except Exception:
            return
        try:
            self._draw_hover(it)      # 立刻把星的颜色换掉，给出即时反馈
        except Exception:
            pass

    def clear(self):
        self._set_hover(None)
        for it in list(self.items):
            self.canvas.delete(it["tag"])
            self._drop_park_ui(it)
        self.items = []

    def destroy(self):
        self._stop_hover_poll()
        try:
            self.win.destroy()
        except Exception:
            pass


# ---------------------------------------------------------------- 番茄滑块

def _shade(hex_color, k):
    """把 #RRGGBB 按系数 k 调暗（k<1）/ 调亮（k>1），返回同格式字符串。

    番茄是画布图元画的，没有主题样式表可用，"按压变暗"只能自己算颜色。
    """
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    if k <= 1.0:
        r, g, b = int(r * k), int(g * k), int(b * k)
    else:                                   # 提亮走「向白色插值」，避免溢出偏色
        t = min(1.0, k - 1.0)
        r, g, b = (int(r + (255 - r) * t), int(g + (255 - g) * t),
                   int(b + (255 - b) * t))
    return "#%02X%02X%02X" % (min(255, r), min(255, g), min(255, b))


class TomatoSlider(tk.Frame):
    """
    自绘滑块：浅色轨道 + 红色已选段 + **扁圆的小番茄把手**。

    为什么不用 tk.Scale / ttk.Scale？
      · tk.Scale 的把手是系统绘制的灰方块，换不了样子；
      · ttk 的 slider 元素只能塞一张图片，没法随尺寸/主题走；
      · 更关键的是 emoji 字形：Tk 8.6 不渲染彩色 emoji（COLR/CBDT 表），
        写 "🍅" 只会得到一颗单色轮廓，所以这里用画布图元画一颗真·彩番茄。
    控件随容器宽度自动重画（面板现在可以自由拖拽缩放）。

    把手默认是**藏起来**的：只有鼠标悬停或按下拖动时才浮现 / 消失，
    两头都带轻微的缩放动画；按下瞬间再额外缩小 + 变暗，抬手弹回。
    """

    THUMB = 15          # 番茄半径（100% 缩放时）
    H = 34              # 控件高度
    # —— 动画时长（毫秒）——
    SHOW_MS = 190       # 浮现比消失慢一点，"弹出来"更明显
    HIDE_MS = 130       # 消失要干脆
    PRESS_MS = 90       # 按压 / 回弹
    FRAME_MS = 16       # ≈60fps
    # —— 按压态：缩小到 82%、亮度压到 70% ——
    PRESS_SCALE = 0.82
    PRESS_SHADE = 0.70
    # 悬停自检周期（毫秒），见 _watch 的注释
    WATCH_MS = 400

    def __init__(self, master, lo, hi, value, fmt, command=None, integer=False,
                 bg=None):
        self._bg = bg or CLR_BG
        tk.Frame.__init__(self, master, bg=self._bg)
        self.lo, self.hi = float(lo), float(hi)
        self.integer = bool(integer)
        self.fmt = fmt
        self.command = command
        self.value = self._clamp(float(value))
        # 注意：不能叫 self._w —— 那是 Tkinter 保留的「控件路径」属性，
        # 覆盖掉它会让后续子控件的命名直接崩掉。
        self._cw = 200
        self.canvas = tk.Canvas(self, height=self.H, width=self._cw, bg=self._bg,
                                highlightthickness=0, bd=0, cursor="hand2")
        self.canvas.pack(fill="x")
        self.canvas.bind("<Configure>", self._on_configure)
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        # 把手默认 invisible：靠这两个事件浮现 / 收起
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)
        # _vis = 把手可见度 0~1，_prs = 按压度 0~1（都是补间量的"当前值"）
        self._vis, self._vis_to = 0.0, 0.0
        self._prs, self._prs_to = 0.0, 0.0
        self._dragging = False
        self._anim = None
        self._watch_job = None
        self._last_t = None
        self._draw()

    def destroy(self):
        """面板会整体重建（切词书 / 恢复默认），别把 after 回调留给已死的控件。"""
        self._stop_watch()
        if self._anim is not None:
            try:
                self.after_cancel(self._anim)
            except Exception:
                pass
            self._anim = None
        tk.Frame.destroy(self)

    # -- 取值 --------------------------------------------------

    def get(self):
        return self.value

    def set(self, v, notify=False):
        self.value = self._clamp(float(v))
        self._draw()
        if notify:
            self._emit()

    def _clamp(self, v):
        v = min(max(v, self.lo), self.hi)
        return float(int(round(v))) if self.integer else v

    # -- 坐标换算 ----------------------------------------------

    def _span(self):
        return max(1, self._cw - 2 * (self.THUMB + 2))

    def _x_of(self, v):
        r = 0.0 if self.hi <= self.lo else (v - self.lo) / (self.hi - self.lo)
        return self.THUMB + 2 + r * self._span()

    def _value_of(self, x):
        r = (x - self.THUMB - 2) / float(self._span())
        r = min(max(r, 0.0), 1.0)
        return self.lo + r * (self.hi - self.lo)

    # -- 绘制 --------------------------------------------------

    def _on_configure(self, e):
        if int(e.width) != self._cw:
            self._cw = max(40, int(e.width))
            self._draw()

    def _draw(self):
        c = self.canvas
        c.delete("all")
        w, mid = self._cw, self.H // 2
        x = self._x_of(self.value)
        x0, x1 = self.THUMB + 2, w - self.THUMB - 2
        c.create_rectangle(x0, mid - 3, x1, mid + 3, fill=CLR_TROUGH, outline="")
        # 按下时整条槽跟着压暗一档，免得把手变暗了、轨道还是原色，看着脱节
        act = 1.0 - 0.22 * self._prs
        if x > x0:
            c.create_rectangle(x0, mid - 3, x, mid + 3,
                               fill=_shade(CLR_RED_SOFT, act), outline="")
            c.create_rectangle(x0, mid - 3, x, mid + 1,
                               fill=_shade(CLR_RED, act), outline="")
        # 把手：可见度 → 缩放倍率，_prs 再叠一层"缩小 + 变暗"
        s = self._ease(self._vis, self._vis_to > self._vis)
        if s > 0.015:
            sc = s * (1.0 - (1.0 - self.PRESS_SCALE) * self._prs)
            k = 1.0 - (1.0 - self.PRESS_SHADE) * self._prs
            self._draw_tomato(x, mid, sc, k)

    def _draw_tomato(self, x, y, s=1.0, k=1.0):
        """
        画一颗**扁**小番茄：果体 + 底部暗弧 + 高光 + 三片叶 + 蒂。

        为什么画扁的？真番茄和 🍅 emoji 本来就是宽略大于高的扁圆，
        之前画成正圆反而像个红皮球。emoji 走不通：Tk 8.6 不渲染彩色 emoji
        （GDI 没有 COLR 支持，"🍅" 只有单色轮廓，实测 Segoe UI Emoji /
        Segoe UI Symbol 都一样），logo 位图又是女孩头像，所以还是画布图元最像。

        s = 缩放倍率（浮现动画用），k = 明度系数（按压变暗用）。
        """
        c = self.canvas
        rx = self.THUMB * s
        ry = self.THUMB * 0.70 * s
        lw = max(1, int(round(2 * s)))
        red = _shade(CLR_RED, k)
        dark = _shade(CLR_RED_DARK, k)
        soft = _shade(CLR_RED_SOFT, k)
        grn = _shade(CLR_GREEN, k)
        grnd = _shade(CLR_GREEN_DK, k)
        off = 3 * s                      # 底部那圈"厚度"也要跟着缩放
        c.create_oval(x - rx, y - ry + off, x + rx, y + ry + off,
                      fill=dark, outline="")
        c.create_oval(x - rx, y - ry, x + rx, y + ry, fill=red, outline="")
        # 底部一道暗弧，球面感就出来了
        c.create_arc(x - rx * 0.86, y - ry * 0.1, x + rx * 0.86, y + ry * 1.25,
                     start=200, extent=140, style="arc",
                     outline=dark, width=lw)
        c.create_oval(x - rx * 0.62, y - ry * 0.62, x - rx * 0.08, y - ry * 0.02,
                      fill=soft, outline="")
        # 三片小叶：左右外翻 + 中间一片，再补一根短蒂
        for dx, dy, w, h in ((-0.42, -0.30, 0.34, 0.20), (0.42, -0.30, 0.34, 0.20),
                             (0.0, -0.52, 0.26, 0.22)):
            c.create_oval(x + (dx - w) * rx, y + (dy - h) * ry * 1.6,
                          x + (dx + w) * rx, y + (dy + h) * ry * 1.6,
                          fill=grn, outline="")
        c.create_line(x, y - ry * 0.85, x, y - ry * 1.5,
                      fill=grnd, width=lw)

    # -- 交互 --------------------------------------------------

    def _emit(self):
        if self.command:
            self.command(self.value)

    def _set_from_x(self, x):
        v = self._clamp(self._value_of(x))
        if v != self.value:
            self.value = v
            self._draw()
        return v

    # -- 浮现 / 按压动画（自建补间，依然是零依赖） --------------

    @staticmethod
    def _ease(v, rising):
        """可见度 → 缩放倍率。

        浮现走 easeOutBack：尾段轻微过冲到 ~1.09 再落回 1，果冻似的弹一下；
        隐藏走 v^1.8：越缩越快，等它小到看不见了才真正消失，不会"啪"地断掉。
        两端值在 v=0/1 时两条曲线重合，所以静止态用哪条都一样。
        """
        if rising:
            p = v - 1.0
            return max(0.0, 1.0 + 2.70158 * p * p * p + 1.70158 * p * p)
        return max(0.0, v ** 1.8)

    @staticmethod
    def _approach(cur, to, dt, dur):
        if cur == to:
            return to
        step = dt / max(1.0, dur)
        return to if abs(to - cur) <= step else (cur + step if to > cur
                                                 else cur - step)

    def _kick(self):
        """启动补间；已在跑就不重复排队（每帧重读目标值，可以中途改向）。"""
        if self._anim is None:
            self._last_t = None
            self._anim = self.after(0, self._tick)

    def _tick(self):
        self._anim = None
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        now = time.perf_counter()
        dt = 16.0 if self._last_t is None else (now - self._last_t) * 1000.0
        self._last_t = now
        # 切走再切回来会攒出一个巨大的 dt，钳一下免得动画瞬间跳完
        dt = min(64.0, max(1.0, dt))
        self._vis = self._approach(self._vis, self._vis_to, dt,
                                   self.SHOW_MS if self._vis_to > self._vis
                                   else self.HIDE_MS)
        self._prs = self._approach(self._prs, self._prs_to, dt, self.PRESS_MS)
        self._draw()
        if self._vis != self._vis_to or self._prs != self._prs_to:
            self._anim = self.after(self.FRAME_MS, self._tick)
        else:
            self._last_t = None

    def _set_visible(self, on):
        if self._vis_to != (1.0 if on else 0.0):
            self._vis_to = 1.0 if on else 0.0
            self._kick()
        if on:
            self._start_watch()
        else:
            self._stop_watch()

    # 滚轮翻页时，参数区里的控件会从指针底下"滑走"。X11 会补发 <Leave>，
    # 但 Windows 的 Tk 只在指针真的移动时才产生 crossing 事件 —— 于是把手会
    # 一直粘在某个滑块上。用个低频自检兜底：只在「正显示且没在拖」时才跑。
    def _start_watch(self):
        if self._watch_job is None:
            self._watch_job = self.after(self.WATCH_MS, self._watch)

    def _stop_watch(self):
        if self._watch_job is not None:
            try:
                self.after_cancel(self._watch_job)
            except Exception:
                pass
            self._watch_job = None

    def _watch(self):
        self._watch_job = None
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        if self._dragging or self._vis_to != 1.0:
            return
        inside = True       # 查不到就保守当"在里面"，宁可多留一会儿也别抖没
        try:
            px, py = self.canvas.winfo_pointerxy()
            inside = self.canvas.winfo_containing(px, py) is self.canvas
        except Exception:
            pass
        if inside:
            self._watch_job = self.after(self.WATCH_MS, self._watch)
        else:
            self._set_visible(False)

    def _set_pressed(self, on):
        if self._prs_to != (1.0 if on else 0.0):
            self._prs_to = 1.0 if on else 0.0
            self._kick()

    # -- 鼠标事件 ----------------------------------------------

    def _on_enter(self, _e):
        self._set_visible(True)

    def _on_leave(self, _e):
        # 拖到面板外面时别把把手收了 —— 手还摁着呢，收了就只能盲拖
        if not self._dragging:
            self._set_visible(False)

    def _on_press(self, e):
        self._dragging = True
        self._set_pressed(True)
        self._set_visible(True)
        self._set_from_x(e.x)
        self._emit()

    def _on_drag(self, e):
        self._set_from_x(e.x)
        self._emit()

    def _on_release(self, e):
        self._dragging = False
        self._set_pressed(False)
        # 松手时鼠标还在控件上就继续留着，不在就收起来
        inside = False
        try:
            inside = self.canvas.winfo_containing(e.x_root, e.y_root) is self.canvas
        except Exception:
            pass
        self._set_visible(inside)


# ---------------------------------------------------------------- 控制面板

class DanmakuApp(object):

    def __init__(self, autostart=False):
        self.cfg = self._load_config()
        # 演示/自检模式用的临时参数绝不能落盘：否则「同屏 8 条」这类压测设置
        # 会被写进 config.json，下次正常启动就变味了。
        ensure_books_dir()
        self.book_name, self.book_path = resolve_book(self.cfg)
        self.words = load_words(self.book_path) if self.book_path else []
        self.running = False      # 是否正在推进（出词 + 移动）
        self.started = False      # 是否已经启动过（用于区分「未启动」和「已暂停」）
        self.spawned = 0
        self.layer = None
        self._spawn_job = None
        self._tick_job = None
        self._save_job = None
        self._text_cache = {}      # (词书, 词序号, 影响文案的参数) -> 弹幕文案
        # 收藏夹（books\已收藏单词.csv）的内存镜像
        self._fav_rows = []
        self._fav_set = set()
        self._load_favorites()
        # 大写锁定状态：开机先取一次真值（GetKeyState 低位），之后靠 _poll_caps 维持；
        # 面板上那条提示也读它。
        self._caps_on = self._caps_true()
        self._caps_down = False    # 上一拍 VK_CAPITAL 是否物理按下（用来抓按下沿）
        self._caps_job = None

        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        # 面板允许拖拽边框自由缩放（用户要求）；内部全部用 pack + expand 自适应
        self.root.resizable(True, True)
        self.root.minsize(330, 430)
        self.root.configure(bg=CLR_BG)
        # 关掉主窗口 = 退出程序
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)

        ICONS.load(self.root)      # PhotoImage 必须在 Tk 之后才能建
        if ICONS.ok:
            try:
                self.root.iconphoto(True, ICONS.big)   # 窗口标题栏 + 任务栏图标
            except Exception:
                pass

        self._init_style()
        self._build_panel()
        self._build_handle()
        self._bind_hotkeys()
        self._poll_caps()          # 开始轮询大写锁定，控制弹幕是否穿透鼠标

        if not self.words:
            messagebox.showwarning(
                APP_TITLE,
                "没有读取到单词数据。\n\n请在 books\\ 目录里放至少一本词书（.csv）。",
            )

        if autostart and self.words:
            # 自启：直接开弹幕并收起面板，只在角落留 logo 把手
            self.root.after(400, self._autostart_run)

        self.root.mainloop()

    def _autostart_run(self):
        """启动即开跑：不再需要手动点「开始」，面板收起只在角落留 logo 把手。"""
        self.toggle()
        self.hide_panel()

    # -- 配置 --------------------------------------------------

    def _load_config(self):
        cfg = dict(DEFAULT_CONFIG)
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg.update(json.load(f))
            except Exception:
                pass
        # 迁移：旧的「离屏后随机间隔」两参数合并成单一固定间隔，
        # 否则老配置里的 min/max_interval 会让新的固定节奏读不到值。
        if "spawn_interval" not in cfg:
            cfg["spawn_interval"] = cfg.get("min_interval", DEFAULT_CONFIG["spawn_interval"])
        cfg.pop("min_interval", None)
        cfg.pop("max_interval", None)
        # 音标不再受开关控制（面板里的「显示音标」已删除）：弹幕正文只放
        # 单词 + 词性 + 释义，音标一律在悬停信息框里看。顺手清掉老配置的遗留键。
        cfg.pop("show_phonetic", None)
        # 固定间隔下同屏允许几条；但旧配置把上限压成 1 会让新行为看不出变化
        if cfg.get("one_at_a_time") and int(cfg.get("max_on_screen", 1)) <= 1:
            cfg["one_at_a_time"] = False
            cfg["max_on_screen"] = DEFAULT_CONFIG["max_on_screen"]
        return cfg

    def _save_config(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # -- 面板 --------------------------------------------------

    def _init_style(self):
        """ttk 控件的番茄配色（Combobox 用，tk 原生控件在下面直接上色）。"""
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")     # clam 才能让 Combobox 的配色真的生效
        except Exception:
            pass
        st.configure("Tomato.TCombobox",
                     fieldbackground=CLR_CARD, background=CLR_CARD,
                     foreground=CLR_TEXT, arrowcolor=CLR_RED,
                     bordercolor=CLR_BORDER, lightcolor=CLR_BORDER,
                     darkcolor=CLR_BORDER, padding=3)
        st.map("Tomato.TCombobox",
               fieldbackground=[("readonly", CLR_CARD)],
               foreground=[("readonly", CLR_TEXT)],
               bordercolor=[("focus", CLR_RED)])
        # 下拉列表是独立 Tk 窗口，只能用 option 数据库上色
        self.root.option_add("*TCombobox*Listbox.background", CLR_CARD)
        self.root.option_add("*TCombobox*Listbox.foreground", CLR_TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", CLR_RED)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
        self.root.option_add("*TCombobox*Listbox.font", ("Microsoft YaHei", 9))

    def _build_panel(self):
        r = self.root
        r.geometry("330x790+120+50")

        # 标题栏：暖白底 + 底部红线，番茄图标放右上角
        bar = tk.Frame(r, bg=CLR_BAR, height=38)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Label(bar, text="  单词弹幕", bg=CLR_BAR, fg=CLR_RED_DEEP,
                 font=("Microsoft YaHei", 12, "bold")).pack(side="left")
        if ICONS.ok:
            self.title_icon = tk.Label(bar, image=ICONS.big, bg=CLR_BAR, bd=0)
            self.title_icon.pack(side="right", padx=8)
        else:
            tk.Label(bar, text="🍅", bg=CLR_BAR, fg=CLR_RED,
                     font=("Segoe UI Emoji", 12)).pack(side="right", padx=12)
        self._make_draggable(bar)

        tk.Frame(r, bg=CLR_RED, height=3).pack(fill="x")   # 标题栏下的红色装饰线

        # 面板分两层：底部按钮永远贴底，中间所有调节项塞进可滚动视口 ——
        # 面板被拖小以后，用右侧滚动条或者鼠标滚轮就能翻到被挤掉的那些设置。
        self.sliders = {}      # key -> (控件, 数值 StringVar, 格式化函数, 是否整数)
        body = tk.Frame(r, bg=CLR_BG)
        body.pack(fill="both", expand=True)

        # 底部固定区：pack 的分配顺序就是优先级，先建的不会被后建的挤掉。
        foot = tk.Frame(body, bg=CLR_BG)
        foot.pack(side="bottom", fill="x", padx=16, pady=(8, 10))
        bf = tk.Frame(foot, bg=CLR_BG)
        bf.pack(fill="x")
        tk.Button(bf, text="隐藏面板", command=self.hide_panel,
                  bg=CLR_CARD, fg=CLR_TEXT, bd=1, relief="solid",
                  activebackground=CLR_TROUGH,
                  font=("Microsoft YaHei", 9), cursor="hand2").pack(side="left")
        tk.Button(bf, text="退出", command=self.quit_app,
                  bg=CLR_CARD, fg=CLR_RED_DEEP, bd=1, relief="solid",
                  activebackground=CLR_TROUGH,
                  font=("Microsoft YaHei", 9), cursor="hand2").pack(side="right")
        tk.Button(bf, text="恢复默认", command=self.restore_defaults,
                  bg=CLR_CARD, fg=CLR_RED, bd=1, relief="solid",
                  activebackground=CLR_TROUGH,
                  font=("Microsoft YaHei", 9), cursor="hand2").pack(side="right",
                                                                   padx=(0, 6))
        tk.Label(foot, text="热键 Ctrl+Alt+H 面板 / P 暂停 / Q 退出",
                 bg=CLR_BG, fg=CLR_MUTED,
                 font=("Microsoft YaHei", 8)).pack(pady=(8, 0))

        # —— 可滚动视口 ——
        # 滚动条用原生 tk.Scrollbar：这是功能件，造型越朴素越不会让人当成装饰，
        # 也正好和番茄把手区分开（用户明确要求这里别用番茄）。
        # 用 grid 而不用 pack：滚动条要按需隐藏/恢复，grid_remove 能记住原格位，
        # pack 的话 forget 之后再 pack 会被 expand 的 Canvas 挤到没地方。
        area = tk.Frame(body, bg=CLR_BG)
        area.pack(side="top", fill="both", expand=True, padx=(16, 4), pady=(10, 0))
        area.grid_rowconfigure(0, weight=1)
        area.grid_columnconfigure(0, weight=1)
        self.vsb = tk.Scrollbar(area, orient="vertical", width=12,
                                bg=CLR_BORDER, troughcolor=CLR_TROUGH,
                                activebackground=CLR_RED_SOFT,
                                relief="flat", bd=0, highlightthickness=0,
                                command=self._on_scroll)
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.sview = tk.Canvas(area, bg=CLR_BG, highlightthickness=0, bd=0,
                               yscrollincrement=24,
                               yscrollcommand=self._on_scroll_set)
        self.sview.grid(row=0, column=0, sticky="nsew")
        scroller = tk.Frame(self.sview, bg=CLR_BG)
        self._scroll_win = self.sview.create_window((0, 0), window=scroller,
                                                    anchor="nw")
        self._scroll_need = True
        scroller.bind("<Configure>", self._on_scroll_inner)
        self.sview.bind("<Configure>", self._on_scroll_canvas)

        body = scroller      # 之后所有控件都塞进滚动区，下面代码照旧写 body

        # 状态卡
        card = tk.Frame(body, bg=CLR_CARD, bd=0, highlightthickness=1,
                        highlightbackground=CLR_BORDER)
        card.pack(fill="x", pady=(0, 10))
        self.status_var = tk.StringVar(value="未启动")
        self.status_lbl = tk.Label(card, textvariable=self.status_var, bg=CLR_CARD,
                                   fg=CLR_MUTED, font=("Microsoft YaHei", 11, "bold"))
        self.status_lbl.pack(pady=(10, 2))
        self.info_var = tk.StringVar(value="已加载 %d 个单词" % len(self.words))
        tk.Label(card, textvariable=self.info_var, bg=CLR_CARD, fg=CLR_MUTED,
                 font=("Microsoft YaHei", 9)).pack(pady=(0, 10))

        # 控制按钮
        btnf = tk.Frame(body, bg=CLR_BG)
        btnf.pack(fill="x", pady=(0, 10))
        self.start_btn = tk.Button(btnf, text="开始弹幕", command=self.toggle,
                                   bg=CLR_RED, fg="#FFFFFF", bd=0,
                                   activebackground=CLR_RED_DARK,
                                   activeforeground="#FFFFFF",
                                   font=("Microsoft YaHei", 10, "bold"),
                                   height=2, cursor="hand2")
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        # 「来一条」用手动语义：同屏满了就把最老的那条顶掉，保证每次点击都有反馈
        self.one_btn = tk.Button(btnf, text="来一条",
                                 command=lambda: self.spawn_once(replace=True),
                                 bg=CLR_CARD, fg=CLR_GREEN_DK, bd=1, relief="solid",
                                 activebackground="#EAF3E1",
                                 font=("Microsoft YaHei", 10), height=2,
                                 cursor="hand2")
        self.one_btn.pack(side="left", fill="x", expand=True, padx=(6, 0))

        # 词书（books\ 目录下可以放多本，这里切换）
        bk = tk.Frame(body, bg=CLR_BG)
        bk.pack(fill="x", pady=(9, 2))
        tk.Label(bk, text="词书", bg=CLR_BG, fg=CLR_TEXT,
                 font=("Microsoft YaHei", 9, "bold")).pack(side="left")
        self.books = list_books()
        self.book_var = tk.StringVar(value=self.book_name or "")
        self.book_cb = ttk.Combobox(bk, textvariable=self.book_var, width=17,
                                    state="readonly", style="Tomato.TCombobox",
                                    values=[d for d, _p in self.books])
        self.book_cb.pack(side="right")
        self.book_cb.bind("<<ComboboxSelected>>", self._on_book_change)
        self.book_lbl = tk.Label(body, text="", bg=CLR_BG, fg=CLR_MUTED,
                                 font=("Microsoft YaHei", 8), justify="left")
        self.book_lbl.pack(anchor="w", pady=(2, 0))
        self._refresh_book_label()

        # 参数滑块
        self._slider(body, "速度（屏宽/秒）", "speed_ratio", 0.03, 0.35,
                     lambda v: "%.0f%%" % (v * 100))
        self._slider(body, "出现间隔（固定·秒）", "spawn_interval", 0.5, 12.0,
                     lambda v: "%.1f s" % v)
        self._slider(body, "顶部区域（屏高占比）", "band_ratio", 0.05, 0.50,
                     lambda v: "%.0f%%" % (v * 100))
        self._slider(body, "字号（屏高占比）", "font_ratio", 0.015, 0.09,
                     lambda v: "%.1f%%" % (v * 100))
        self._slider(body, "不透明度", "opacity", 0.25, 1.0,
                     lambda v: "%.0f%%" % (v * 100))
        self._int_slider(body, "同屏条数上限", "max_on_screen", 1, 8)
        self._int_slider(body, "释义条数（前 N 个）", "max_meanings", 1, 4)
        self._int_slider(body, "最多词性数", "max_pos", 1, 3)

        # 区域
        row = tk.Frame(body, bg=CLR_BG)
        row.pack(fill="x", pady=(8, 4))
        tk.Label(row, text="出现区域", bg=CLR_BG, fg=CLR_TEXT,
                 font=("Microsoft YaHei", 9, "bold")).pack(side="left")
        _bm = self.cfg.get("band_mode", "top")
        self.band_var = tk.StringVar(value=BAND_LABELS.get(_bm, BAND_LABELS["top"]))
        cb = ttk.Combobox(row, textvariable=self.band_var, width=10,
                          state="readonly", style="Tomato.TCombobox",
                          values=[BAND_LABELS["top"], BAND_LABELS["middle"],
                                  BAND_LABELS["bottom"], BAND_LABELS["random"]])
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", self._on_band_change)

        # 开关
        of = tk.Frame(body, bg=CLR_BG)
        of.pack(fill="x", pady=(6, 0))
        self.rc_var = tk.BooleanVar(value=bool(self.cfg.get("random_color")))
        self._check(of, "随机颜色", self.rc_var, self._on_rc_change).pack(side="left")

        # 大写锁定交互提示（顺带当收藏夹词数计数）
        self.hint_var = tk.StringVar(value="")
        self.hint_lbl = tk.Label(body, textvariable=self.hint_var, bg=CLR_BG,
                                 fg=CLR_MUTED, font=("Microsoft YaHei", 8),
                                 justify="left", wraplength=290)
        self.hint_lbl.pack(anchor="w", pady=(7, 0))
        self._refresh_hint()

        # 字体下拉：列出系统已装字体（含 fonts\ 里注册的萝莉体），默认自动=萝莉体
        ff = tk.Frame(body, bg=CLR_BG)
        ff.pack(fill="x", pady=(9, 2))
        tk.Label(ff, text="字体", bg=CLR_BG, fg=CLR_TEXT,
                 font=("Microsoft YaHei", 9, "bold")).pack(side="left")
        self.font_families = list_font_families()
        self.font_var = tk.StringVar(value=AUTO_FONT_LABEL)
        self.font_cb = ttk.Combobox(ff, textvariable=self.font_var, width=17,
                                    state="readonly", style="Tomato.TCombobox",
                                    values=[AUTO_FONT_LABEL] + self.font_families)
        self.font_cb.pack(side="right")
        self.font_cb.bind("<<ComboboxSelected>>", self._on_font_change)
        self._sync_font_combo()

        self.font_lbl = tk.Label(body, text="", bg=CLR_BG, fg=CLR_MUTED,
                                 font=("Microsoft YaHei", 8), justify="left")
        self.font_lbl.pack(anchor="w", pady=(2, 0))
        self._refresh_font_label()

        # 最后按内容实际需求定尺寸：写死高度会在不同 DPI / 字体下把底部按钮裁掉，
        # winfo_reqheight() 给的是内容真实所需，不受 geometry 约束。
        # 面板现在可自由缩放，所以再夹一次屏幕范围，避免初始就超出屏幕。
        r.update_idletasks()
        # Canvas 自身的请求尺寸不反映内容，得手动画进内部 frame 的高度，
        # 否则面板一开就只有一个巴掌高（用户拖小之后才需要滚动）。
        self.sview.configure(height=max(220, min(scroller.winfo_reqheight(),
                                                 int(get_screen_size()[1] * 0.8))))
        r.update_idletasks()   # 让 Canvas 新高度传导进整体需求，下面读 reqheight 才准
        sw, sh = get_screen_size()
        w = min(max(350, scroller.winfo_reqwidth() + 56), int(sw * 0.9))
        h = min(max(430, r.winfo_reqheight()), int(sh * 0.92))
        r.geometry("%dx%d+%d+%d" % (w, h, 120, 50))
        # 从 Canvas 起递归绑定滚轮：scroller 的 master 就是 Canvas，
        # winfo_children() 能一层层走到每个控件；顺带把 Canvas 空白区也覆盖到
        self._bind_wheel(self.sview)

    def _check(self, parent, text, var, cmd):
        """统一配色的复选框（tk 原生 Checkbutton 不吃 ttk 主题）。"""
        return tk.Checkbutton(parent, text=text, variable=var,
                              bg=CLR_BG, fg=CLR_TEXT, activebackground=CLR_BG,
                              activeforeground=CLR_TEXT, selectcolor=CLR_CARD,
                              highlightthickness=0, bd=0,
                              font=("Microsoft YaHei", 9), cursor="hand2",
                              command=cmd)

    def _refresh_font_label(self):
        fam = FONTS.family(self.cfg)
        if FONTS.available and fam == FONTS.custom_family:
            self.font_lbl.config(
                text="当前：%s（自带）· 字库 %d 码位 · 缺字自动回退"
                     % (fam, len(FONTS.covered)))
            return
        cov = FONTS.coverage(fam)
        if cov:
            self.font_lbl.config(
                text="当前：%s · 可显示 %d 码位 · 缺字自动回退" % (fam, len(cov)))
        else:
            self.font_lbl.config(text="当前：%s · 未找到字体文件，不做缺字回退" % fam)

    def _sync_font_combo(self):
        """把 config 里的字体映射回下拉框选项（默认萝莉体显示为「自动」）。"""
        want = (self.cfg.get("font_family") or "").strip()
        if not want or (FONTS.available and want == FONTS.custom_family):
            self.font_var.set(AUTO_FONT_LABEL)
        elif want in self.font_families:
            self.font_var.set(want)
        else:
            self.font_var.set(AUTO_FONT_LABEL)

    def _on_font_change(self, _e=None):
        v = self.font_var.get()
        self.cfg["font_family"] = "" if v == AUTO_FONT_LABEL else v
        # 换字体后旧弹幕的字形是旧的，直接清掉更干净
        if self.layer:
            self.layer.clear()
        self._apply_live()
        self._refresh_font_label()

    def _refresh_book_label(self):
        if self.book_path:
            self.book_lbl.config(text="当前词书：%s · %d 词"
                                      % (self.book_name, len(self.words)))
        else:
            self.book_lbl.config(text="books\\ 目录里没有 .csv 词书")

    def _on_book_change(self, _e=None):
        disp = self.book_var.get()
        for d, p in list_books():
            if d == disp:
                self.book_name, self.book_path = d, p
                self.cfg["book"] = os.path.basename(p)
                break
        self.words = load_words(self.book_path) if self.book_path else []
        self.spawned = 0
        if self.layer:
            self.layer.clear()      # 换书后旧词不再留在屏上
        self._apply_live()
        self._refresh_book_label()

    def _slider(self, parent, label, key, lo, hi, fmt):
        f = tk.Frame(parent, bg=CLR_BG)
        f.pack(fill="x", pady=(5, 0))
        head = tk.Frame(f, bg=CLR_BG)
        head.pack(fill="x")
        tk.Label(head, text=label, bg=CLR_BG, fg=CLR_TEXT,
                 font=("Microsoft YaHei", 9, "bold")).pack(side="left")
        val = self.cfg.get(key, lo)
        var = tk.StringVar(value=fmt(float(val)))
        tk.Label(head, textvariable=var, bg=CLR_BG, fg=CLR_GREEN_DK,
                 font=("Microsoft YaHei", 9, "bold")).pack(side="right")

        def on_change(v):
            fv = float(v)
            self.cfg[key] = fv
            var.set(fmt(fv))
            self._apply_live()

        s = TomatoSlider(f, lo, hi, float(val), fmt, command=on_change)
        s.pack(fill="x")
        self.sliders[key] = (s, var, fmt, False)   # 「恢复默认」要用它回写显示值
        return s

    def _int_slider(self, parent, label, key, lo, hi):
        f = tk.Frame(parent, bg=CLR_BG)
        f.pack(fill="x", pady=(5, 0))
        head = tk.Frame(f, bg=CLR_BG)
        head.pack(fill="x")
        tk.Label(head, text=label, bg=CLR_BG, fg=CLR_TEXT,
                 font=("Microsoft YaHei", 9, "bold")).pack(side="left")
        iv = int(self.cfg.get(key, lo))
        var = tk.StringVar(value=str(iv))
        tk.Label(head, textvariable=var, bg=CLR_BG, fg=CLR_GREEN_DK,
                 font=("Microsoft YaHei", 9, "bold")).pack(side="right")

        def on_change(v):
            n = int(round(float(v)))
            self.cfg[key] = n
            var.set(str(n))
            self._apply_live()

        s = TomatoSlider(f, lo, hi, iv, str, command=on_change, integer=True)
        s.pack(fill="x")
        self.sliders[key] = (s, var, str, True)
        return s

    def _make_draggable(self, widget):
        def start(e):
            widget._dx = e.x
            widget._dy = e.y

        def move(e):
            x = self.root.winfo_x() + e.x - widget._dx
            y = self.root.winfo_y() + e.y - widget._dy
            self.root.geometry("+%d+%d" % (x, y))

        widget.bind("<Button-1>", start)
        widget.bind("<B1-Motion>", move)

    # -- 滚动区（面板缩小后翻看被挤掉的设置）----------------------

    def _on_scroll(self, *args):
        self.sview.yview(*args)

    def _on_scroll_set(self, first, last):
        """Tk 滚动位置变化回调：顺带决定滚动条要不要露出来。"""
        self.vsb.set(first, last)
        try:
            need = not (float(first) <= 0.001 and float(last) >= 0.999)
        except (TypeError, ValueError):
            return
        if need != self._scroll_need:
            self._scroll_need = need
            if need:
                self.vsb.grid()          # grid() 回到 grid_remove 之前的原格位
            else:
                self.vsb.grid_remove()

    def _on_scroll_inner(self, _e=None):
        self.sview.configure(scrollregion=self.sview.bbox("all"))

    def _on_scroll_canvas(self, e):
        # 让内部 frame 始终跟视口一样宽，控件才能 fill="x" 铺满
        self.sview.itemconfig(self._scroll_win, width=max(1, int(e.width)))

    def _on_wheel(self, e):
        # 返回 "break"：既滚动视口，也顺手拦掉 Combobox 默认的「滚轮换选项」
        if self._scroll_need:
            self.sview.yview_scroll(-1 if e.delta > 0 else 1, "units")
        return "break"

    def _bind_wheel(self, widget):
        """递归给滚动区里的每个控件绑滚轮——Tk 的事件不会冒泡到父容器。"""
        widget.bind("<MouseWheel>", self._on_wheel, add="+")
        for ch in widget.winfo_children():
            self._bind_wheel(ch)

    # -- 恢复默认 ------------------------------------------------

    def restore_defaults(self):
        """
        把所有调节项一次性恢复成出厂值。

        只有把手位置（handle_x / handle_y）不动 —— 那是窗口摆哪儿，属于位置不属设置，
        把人辛辛苦苦拖到顺手的位置重置掉才是真添乱。
        """
        if not messagebox.askyesno(
                APP_TITLE,
                "把所有调节项恢复为默认设置？\n\n"
                "速度、间隔、区域、字号、不透明度、同屏上限、释义/词性条数、\n"
                "出现区域、随机颜色、字体、词书都会回到出厂值。\n"
                "（右下角把手的位置保持不变）"):
            return
        KEEP = ("handle_x", "handle_y")
        for k, v in DEFAULT_CONFIG.items():
            if k not in KEEP:
                self.cfg[k] = v
        # 滑块 + 数值标签回写
        for key, (widget, var, fmt, is_int) in self.sliders.items():
            v = self.cfg.get(key, 0)
            widget.set(v)
            var.set(fmt(int(round(float(v)))) if is_int else fmt(float(v)))
        # 复选框 / 下拉框回写
        self.rc_var.set(bool(self.cfg.get("random_color")))
        self.band_var.set(BAND_LABELS.get(self.cfg.get("band_mode"),
                                          BAND_LABELS["top"]))
        self._sync_font_combo()
        # 词书回默认并重载
        self.book_name, self.book_path = resolve_book(self.cfg)
        self.words = load_words(self.book_path) if self.book_path else []
        self.spawned = 0
        self.book_var.set(self.book_name or "")
        self._refresh_book_label()
        self._refresh_font_label()
        if self.layer:
            self.layer.clear()      # 屏上旧弹幕按的是旧字体/旧字号，留着没意义
        self._apply_live()
        self._refresh_status()
        self.info_var.set("已恢复默认设置 ✓")
        self.root.after(2200, self._refresh_status)

    # -- 把手（隐藏面板后的唤回入口）----------------------------

    def _build_handle(self):
        self.handle = tk.Toplevel(self.root)
        self.handle.overrideredirect(True)
        self.handle.attributes("-topmost", True)
        sw, sh = get_screen_size()
        size = HANDLE_SIZE
        hx, hy = self._handle_pos(sw, sh, size)
        self.handle.geometry("%dx%d+%d+%d" % (size, size, hx, hy))
        self.handle.configure(bg=TRANSPARENT_KEY)
        if ICONS.ok:
            lb = tk.Label(self.handle, image=ICONS.handle, bg=TRANSPARENT_KEY,
                          bd=0, cursor="hand2")
        else:
            lb = tk.Label(self.handle, text="🍅", bg=CLR_RED, fg="#FFFFFF",
                          font=("Segoe UI Emoji", 12), cursor="hand2")
        lb.pack(fill="both", expand=True)
        # 单击唤出面板；按住拖动 = 挪位置（松手后位置记进 config）
        lb.bind("<Button-1>", self._handle_press)
        lb.bind("<B1-Motion>", self._handle_drag)
        lb.bind("<ButtonRelease-1>", self._handle_release)
        self._h_off = (0, 0)
        self._h_moved = False
        self.handle.withdraw()

        # 用色键把背景抠掉，只留番茄本体（否则会是个红色方块）。
        # 注意 click_through=False —— 把手是要点的，不能穿透。
        self.handle.update_idletasks()
        self.handle.update()
        hwnd = self.handle.winfo_id()
        parent = ctypes.windll.user32.GetParent(hwnd)
        self.handle_hwnd = parent if parent else hwnd
        apply_layered(self.handle_hwnd, TRANSPARENT_KEY, False, 255)

    def _handle_pos(self, sw, sh, size):
        """把手位置：优先用 config 里记住的坐标，否则默认右下角。"""
        x = int(self.cfg.get("handle_x", -1))
        y = int(self.cfg.get("handle_y", -1))
        if x < 0 or y < 0:
            # 放右下角：避开顶部 15% 的弹幕区，也要**抬到任务栏上方**
            # （任务栏在 200% 缩放下约 96 物理像素高，压上去会盖住时钟）
            return sw - size - 20, sh - size - 130
        return (min(max(0, x), max(0, sw - size)),
                min(max(0, y), max(0, sh - size)))

    def _handle_press(self, e):
        self._h_moved = False
        self._h_off = (e.x_root - self.handle.winfo_x(),
                       e.y_root - self.handle.winfo_y())

    def _handle_drag(self, e):
        sw, sh = get_screen_size()
        size = HANDLE_SIZE
        x = min(max(0, e.x_root - self._h_off[0]), max(0, sw - size))
        y = min(max(0, e.y_root - self._h_off[1]), max(0, sh - size))
        if abs(x - self.handle.winfo_x()) + abs(y - self.handle.winfo_y()) > 3:
            self._h_moved = True       # 超过 3px 才算拖动，避免手抖变成挪位
        self.handle.geometry("+%d+%d" % (x, y))

    def _handle_release(self, _e):
        if self._h_moved:
            self.cfg["handle_x"] = self.handle.winfo_x()
            self.cfg["handle_y"] = self.handle.winfo_y()
            self._save_later()
        else:
            self.show_panel()

    # -- 收藏夹 + 大写锁定交互 -----------------------------------

    def _load_favorites(self):
        """
        读 books\\已收藏单词.csv 进内存镜像。

        用 list 保序 + set 做 O(1) 命中：弹幕层每次悬停都要问"这个词收藏了吗"，
        不能每帧去扫文件。
        """
        ensure_fav_book()
        rows, seen = [], set()
        try:
            with open(FAV_BOOK_PATH, "r", encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    w = (r.get("word") or "").strip()
                    if not w or w in seen:
                        continue
                    row = {k: r.get(k, "") for k in BOOK_FIELDS}
                    row["word"] = w
                    rows.append(row)
                    seen.add(w)
        except Exception:
            rows, seen = [], set()
        self._fav_rows = rows
        self._fav_set = seen

    def fav_state(self, word):
        """这个词在不在收藏夹里（弹幕层画星星前会问）。"""
        return bool(word) and word in self._fav_set

    def toggle_favorite(self, w):
        """
        收藏 / 取消收藏一个词，返回切换后的状态。

        收藏夹就是「一本普通词书」：写进 books\\已收藏单词.csv，列格式与别的书
        一模一样，所以面板的词书下拉里能直接选它当弹幕词书，不需要第二套机制。
        """
        word = (w.get("word") or "").strip()
        if not word:
            return False
        if word in self._fav_set:
            self._fav_rows = [r for r in self._fav_rows if r.get("word") != word]
            self._fav_set.discard(word)
            now = False
        else:
            self._fav_rows.append(fav_row(w))
            self._fav_set.add(word)
            now = True
        write_fav_rows(self._fav_rows)
        # 正在拿收藏夹当词书：词表变了，立刻重载，新词马上能弹出来
        if self.book_path and os.path.basename(self.book_path) == FAV_BOOK_NAME:
            self.words = load_words(self.book_path)
            self._refresh_book_label()
            self._refresh_status()
        self._refresh_book_list()
        self._refresh_hint()
        return now

    def _refresh_book_list(self):
        """books\\ 里新增/删了文件后，下拉框的可选项跟着更新。"""
        self.books = list_books()
        try:
            self.book_cb.config(values=[d for d, _p in self.books])
        except Exception:
            pass

    def _caps_true(self):
        """大写锁定的**真·切换态**：GetKeyState 的低位。读不到就返回 False。"""
        try:
            return bool(ctypes.windll.user32.GetKeyState(VK_CAPITAL) & 0x0001)
        except Exception:
            return False

    def _poll_caps(self):
        """
        轮询大写锁定：开着 = 弹幕不再鼠标穿透，可悬停看音标 / 点星收藏。

        ⚠️ 别用 `GetAsyncKeyState(VK_CAPITAL) & 1` 判切换态。实测（_debug\\_capstrack.py）：
        那个低位是**"自上次查询之后按下过"的易失位** —— 按下后立刻读到 1，
        0.5s 后再读就变 0（被自己上一次查询吃掉了）。拿它当开关的后果就是
        "按一下亮一瞬"，用起来像"必须按住大写锁定才能交互"。

        真值是 `GetKeyState(VK_CAPITAL) & 1`；同一个实验里它跟着注入的按键
        逐次翻转、且**后台无焦点进程也照样跟得上**（低位是全局切换态，不吃线程队列）。

        双保险：同时看 GetAsyncKeyState 的 0x8000（当前是否物理按下）抓"按下沿"。
        万一 GetKeyState 在某个环境里是陈旧的，就靠按下沿自己翻一次，不会卡死。
        """
        self._caps_job = self.root.after(CAPS_POLL_MS, self._poll_caps)
        try:
            raw = ctypes.windll.user32.GetAsyncKeyState(VK_CAPITAL) & 0xFFFF
        except Exception:
            raw = 0
        down = bool(raw & 0x8000)
        edge = down and not self._caps_down       # 按下沿 = 切换态翻转了一次
        self._caps_down = down
        true_on = self._caps_true()
        if edge and true_on == self._caps_on:
            on = not self._caps_on                # GetKeyState 没跟上 → 自己翻
        else:
            on = true_on
        if on != self._caps_on:
            self._caps_on = on
            if self.layer:
                self.layer.set_interactive(on)
            self._refresh_hint()

    def _refresh_hint(self):
        if self._caps_on:
            self.hint_var.set("大写锁定【开】· 弹幕可交互：悬停停滞看音标，"
                              "点 ★ 收藏（收藏夹 %d 词）" % len(self._fav_rows))
            self.hint_lbl.config(fg=CLR_GREEN_DK)
        else:
            self.hint_var.set("大写锁定【关】· 弹幕鼠标穿透；按一下 CapsLock 打开后"
                              "即可悬停 / 收藏（收藏夹 %d 词）" % len(self._fav_rows))
            self.hint_lbl.config(fg=CLR_MUTED)

    # -- 弹幕层 ------------------------------------------------

    def _ensure_layer(self):
        if self.layer is None:
            sw, sh = get_screen_size()
            self.layer = DanmakuLayer(self.root, self.cfg, sw, sh, FONTS)
            self.layer.fav_state = self.fav_state
            self.layer.fav_toggle = self.toggle_favorite
            self.layer.set_interactive(self._caps_on)
            self._tick()   # 关键：不显式启动，弹幕会永远停在生成点不动
        return self.layer

    def _text_for(self, idx):
        """
        弹幕文案缓存。

        build_text 里带正则清洗和多次拼接，同一本书、同一套参数下结果完全固定，
        没必要每隔几秒重算一遍 —— 这点开销正好落在 Tk 主线程上，是「顿一下」的帮凶。
        """
        key = (self.book_path, idx, self.cfg.get("max_meanings"),
               self.cfg.get("max_pos"), self.cfg.get("max_cn_len"))
        t = self._text_cache.get(key)
        if t is None:
            if len(self._text_cache) > 1500:
                self._text_cache.clear()
            t = build_text(self.words[idx], self.cfg)
            self._text_cache[key] = t
        return t

    def spawn_once(self, replace=False):
        if not self.words:
            return
        idx = random.randrange(len(self.words))
        txt = self._text_for(idx)
        layer = self._ensure_layer()
        # word 一起带过去：悬停信息框要音标，点收藏要把整行写进 已收藏单词.csv
        if layer.spawn(txt, replace_oldest=replace, word=self.words[idx]):
            self.spawned += 1
            self._refresh_status()

    # -- 循环 --------------------------------------------------

    def _schedule_spawn(self):
        """
        固定间隔：每条弹幕之间的时间恒定，不再等上一条离屏。
        节奏因此可预期，也不会被某条特别长的释义拖住整条队列。
        同屏条数由 max_on_screen 兜底，靠轨道分配避免文字叠在一起。
        """
        if not self.running:
            return
        sec = max(0.2, float(self.cfg.get("spawn_interval", 2.5)))
        self._spawn_job = self.root.after(int(sec * 1000), self._do_spawn)

    def _do_spawn(self):
        if not self.running:
            return
        # one_at_a_time 只在显式开启时才退回「等上一条离屏」的老行为
        if self.cfg.get("one_at_a_time", False) and self.layer and self.layer.items:
            self._spawn_job = self.root.after(200, self._do_spawn)
            return
        # 即使因为同屏已满而没弹出来，也照常排下一拍，保证节奏匀速
        self.spawn_once()
        self._schedule_spawn()

    def _tick(self):
        try:
            if self.layer:
                self.layer.tick()
            # 8ms 调度：配合 timeBeginPeriod(1) 才能真的跑到 ~100Hz，
            # 默认 15.6ms 时钟分辨率下写 16 也会被拖成 31ms。
            self._tick_job = self.root.after(8, self._tick)
        except tk.TclError:
            pass   # 窗口已销毁，正常结束动画循环

    # -- 状态 --------------------------------------------------

    def _refresh_status(self):
        """三态：未启动 / 运行中 / 已暂停。按钮文案与颜色跟着走。"""
        if self.running:
            self.status_var.set("● 运行中")
            self.status_lbl.config(fg=CLR_GREEN)
            self.info_var.set("已弹出 %d 条 · 词库 %d 词 · 每 %.1f s 一条"
                              % (self.spawned, len(self.words),
                                 float(self.cfg.get("spawn_interval", 2.5))))
            self.start_btn.config(text="暂停弹幕", bg=CLR_RED_DARK,
                                  activebackground=CLR_RED)
        elif self.started:
            self.status_var.set("● 已暂停")
            self.status_lbl.config(fg=CLR_RED)
            self.info_var.set("已弹出 %d 条 · 词库 %d 词 · 弹幕停在原位"
                              % (self.spawned, len(self.words)))
            self.start_btn.config(text="继续弹幕", bg=CLR_GREEN,
                                  activebackground=CLR_GREEN_DK)
        else:
            self.status_var.set("● 未启动")
            self.status_lbl.config(fg=CLR_MUTED)
            self.info_var.set("已弹出 %d 条 · 词库 %d 词"
                              % (self.spawned, len(self.words)))
            self.start_btn.config(text="开始弹幕", bg=CLR_RED,
                                  activebackground=CLR_RED_DARK)

    def _apply_live(self):
        """参数改动实时生效（重新读取 cfg 即可）。"""
        if self.layer:
            self.layer.cfg = self.cfg
            self.layer.relayout()      # 区域/字号变化会改变弹幕带的高度
            self.layer.refresh_layered()   # 不透明度变化时重设 alpha（穿透态保持）
        self._refresh_status()
        self._save_later()

    def _save_later(self, delay=700):
        """
        拖滑块会一次产生上百次改动，逐次写盘太浪费。
        延迟合并：700ms 内没有新改动才真正落盘。
        """
        if self._save_job:
            try:
                self.root.after_cancel(self._save_job)
            except Exception:
                pass
        self._save_job = self.root.after(delay, self._save_config_now)

    def _save_config_now(self):
        self._save_job = None
        self._save_config()

    def _on_band_change(self, _e=None):
        self.cfg["band_mode"] = BAND_VALUES.get(self.band_var.get(), "top")
        self._apply_live()

    def _on_rc_change(self):
        self.cfg["random_color"] = bool(self.rc_var.get())
        self._apply_live()

    def toggle(self):
        """
        开始 / 暂停 / 继续 三态。
        暂停 = 停止移动 + 停止出新词，**画面上的弹幕原地保留**（用户要求，别清屏）。
        """
        if self.running:
            self.pause()
        elif self.started:
            self.resume()
        else:
            self.start()
        self._refresh_status()

    def start(self):
        self.running = True
        self.started = True
        self._ensure_layer()
        if self.layer:
            self.layer.set_paused(False)
        self.spawn_once()
        self._schedule_spawn()

    def pause(self):
        self.running = False
        if self._spawn_job:
            try:
                self.root.after_cancel(self._spawn_job)
            except Exception:
                pass
            self._spawn_job = None
        if self.layer:
            self.layer.set_paused(True)     # 只冻结，不清屏

    def resume(self):
        self.running = True
        if self.layer:
            self.layer.set_paused(False)
        self._schedule_spawn()

    def hide_panel(self):
        self.root.withdraw()
        if self.started:          # 已启动过（含暂停）就留着把手，方便唤回
            self.handle.deiconify()
            self.handle.lift()
            self.handle.attributes("-topmost", True)

    def show_panel(self):
        self.root.deiconify()
        self.root.lift()
        self.handle.withdraw()

    # -- 热键 --------------------------------------------------

    def _bind_hotkeys(self):
        self.root.bind_all("<Control-Alt-h>", lambda e: (
            self.show_panel() if self.root.state() == "withdrawn" else self.hide_panel()))
        self.root.bind_all("<Control-Alt-H>", lambda e: (
            self.show_panel() if self.root.state() == "withdrawn" else self.hide_panel()))
        self.root.bind_all("<Control-Alt-p>", lambda e: self.toggle())
        self.root.bind_all("<Control-Alt-P>", lambda e: self.toggle())
        self.root.bind_all("<Control-Alt-q>", lambda e: self.quit_app())
        self.root.bind_all("<Control-Alt-Q>", lambda e: self.quit_app())

    # -- 退出 --------------------------------------------------

    def quit_app(self):
        self.running = False
        for job in (self._spawn_job, self._tick_job, self._save_job, self._caps_job):
            if job:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
        self._save_job = None
        self._save_config()          # 退出前把还没落盘的改动补上
        if self.layer:
            self.layer.destroy()     # 顺手停掉悬停轮询，别把 after 回调留给死窗口
        try:
            self.root.destroy()
        except Exception:
            pass


# ---------------------------------------------------------------- 入口

def main():
    # 必须早于第一个 tk.Tk()：否则 Tk 会按 DPI 缩放建立坐标系，
    # 弹幕窗口的 geometry 会和真实物理像素对不上，全部飘到屏幕外。
    enable_dpi_awareness()
    set_timer_resolution(1)
    # 字体也要在 Tk 建字体对象之前注册进进程
    FONTS.load()
    try:
        DanmakuApp(autostart=any(k in sys.argv for k in ("--run", "-r")))
    except Exception:
        # GUI 起不来时至少把原因落到日志，别静默消失
        try:
            with open(os.path.join(APP_DIR, "error.log"), "w", encoding="utf-8") as f:
                import traceback
                traceback.print_exc(file=f)
        except Exception:
            pass
        raise
    finally:
        end_timer_resolution(1)


if __name__ == "__main__":
    main()
