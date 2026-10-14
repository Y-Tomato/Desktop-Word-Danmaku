# -*- coding: utf-8 -*-
"""
单词弹幕的单元测试。

只依赖标准库，直接在项目根目录跑：

    python -m unittest discover -s tests -v
    python tests\test_danmaku.py            # 单跑这一个文件也行

覆盖的重点是**纯函数**和几个出过事 / 容易再犯的点：
  · parse_mean_cn —— 词性分块（acquire 的双空格坑，4 本词书全中过）
  · pick_meanings / shorten_cn —— 释义裁剪
  · text_cache_key —— 为什么不能用「词序号」
  · read_config / write_config —— 原子写 + 坏文件不许静默
  · 收藏夹 CSV 往返
  · 字体 cmap —— 萝莉体覆盖全角标点、IPA 至少有一支字体画得全
  · GDI 位图渲染 —— argtypes 声明错了会静默退回慢路径，必须有断言盯着
"""
import ctypes
import inspect
import os
import random
import shutil
import sys
import time
import unittest

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import danmaku  # noqa: E402

# 临时目录放在 tests\ 下面而不是系统 %TEMP%：
#   · 某些受限环境（比如带文件沙箱的）只允许在项目目录里写文件，用系统临时目录
#     会直接 PermissionError；
#   · 顺手也让跑测试产生的垃圾都在眼皮底下，tearDown 里清掉。
_TMP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")


def _mkdtemp():
    """建一个临时目录 —— 故意**不用 tempfile.mkdtemp**。

    mkdtemp 固定按 os.mkdir(path, 0o700) 建目录，而带文件沙箱的环境会把 0o700
    翻成「只有属主可写」的 DACL：进程跑在受限令牌下，连自己刚建的目录都写不进去
    （本机实测 PermissionError，默认 mode / 0o755 都没事）。用默认 mode 建就行，
    反正 tearDown 会把它删掉。
    """
    os.makedirs(_TMP_ROOT, exist_ok=True)
    for _ in range(100):
        path = os.path.join(_TMP_ROOT, "case%08x" % random.getrandbits(32))
        try:
            os.mkdir(path)
            return path
        except FileExistsError:
            continue
    raise RuntimeError("临时目录建不出来：%s" % _TMP_ROOT)


# ---------------------------------------------------------------- 释义解析

class ParseMeanCnTest(unittest.TestCase):

    def test_acquire_double_space_after_pos(self):
        """数据里词性后面跟了两个空格时，v. 不能掉出去当义项。

        百词斩的 acquire 就是 "v.  （通过努力、能力）获得；…" —— 那两个空格
        正好会被"词性块分隔符"吃掉，于是弹幕显示成 "acquire  v.；获得"。"""
        raw = "v.  （通过努力、能力）获得；学到；得到；购得；患上（疾病）"
        senses = danmaku.parse_mean_cn(raw)
        self.assertEqual(senses[0][0], "v.")
        self.assertNotIn("v.", senses[0][1])
        self.assertEqual(senses[0][1][:2], ["获得", "学到"])
        w = dict(word="acquire", accent="", mean_cn=raw, senses=senses)
        self.assertEqual(danmaku.build_text(w, danmaku.DEFAULT_CONFIG),
                         "acquire  v. 获得；学到")

    def test_two_pos_blocks(self):
        senses = danmaku.parse_mean_cn("v. 请求；上诉；  n. 呼吁；吸引力")
        self.assertEqual([p for p, _items in senses], ["v.", "n."])
        self.assertEqual(senses[0][1], ["请求", "上诉"])
        self.assertEqual(senses[1][1], ["呼吁", "吸引力"])

    def test_same_pos_blocks_merge_and_dedupe(self):
        senses = danmaku.parse_mean_cn("n. 观点；看法；  n. 见解；观点")
        self.assertEqual(len(senses), 1)
        self.assertEqual(senses[0][1], ["观点", "看法", "见解"])

    def test_bracketed_note_is_dropped(self):
        senses = danmaku.parse_mean_cn("v. 仔细考虑；研讨（读作/xx/）")
        self.assertEqual(senses[0][1], ["仔细考虑", "研讨"])

    def test_empty(self):
        self.assertEqual(danmaku.parse_mean_cn(""), [])
        self.assertEqual(danmaku.parse_mean_cn(None), [])


class ShortenCnTest(unittest.TestCase):

    def test_short_text_untouched(self):
        self.assertEqual(danmaku.shorten_cn("请求；上诉", 30), "请求；上诉")

    def test_cut_on_semicolon(self):
        self.assertEqual(danmaku.shorten_cn("请求；上诉；有吸引力", 6), "请求；上诉…")

    def test_single_long_segment_hard_cut(self):
        self.assertEqual(danmaku.shorten_cn("abcdefghij", 4), "abcd…")

    def test_empty(self):
        self.assertEqual(danmaku.shorten_cn("", 30), "")
        self.assertEqual(danmaku.shorten_cn(None, 30), "")


class PickMeaningsTest(unittest.TestCase):

    SENSES = [("v.", ["a", "b", "c"]), ("n.", ["d", "e", "f"]), ("adj.", ["g"])]

    def test_total_budget(self):
        self.assertEqual(danmaku.pick_meanings(self.SENSES, 2, 2, 2),
                         [("v.", ["a"]), ("n.", ["d"])])

    def test_every_pos_gets_one(self):
        self.assertEqual(danmaku.pick_meanings(self.SENSES, 3, 3, 1),
                         [("v.", ["a"]), ("n.", ["d"]), ("adj.", ["g"])])

    def test_per_pos_cap(self):
        self.assertEqual(danmaku.pick_meanings(self.SENSES, 4, 3, 2),
                         [("v.", ["a", "b"]), ("n.", ["d"]), ("adj.", ["g"])])


# ---------------------------------------------------------------- 缓存 key

class TextCacheKeyTest(unittest.TestCase):
    """key 必须只认单词本身 + 全部影响文案的参数（不能用词序号）。"""

    def setUp(self):
        self.cfg = dict(danmaku.DEFAULT_CONFIG)
        self.word = {"word": "appeal"}

    def test_same_word_same_key(self):
        self.assertEqual(danmaku.text_cache_key("a.csv", self.word, self.cfg),
                         danmaku.text_cache_key("a.csv", dict(self.word), self.cfg))

    def test_different_word_different_key(self):
        self.assertNotEqual(danmaku.text_cache_key("a.csv", self.word, self.cfg),
                            danmaku.text_cache_key("a.csv", {"word": "appeal2"}, self.cfg))

    def test_different_book_different_key(self):
        self.assertNotEqual(danmaku.text_cache_key("a.csv", self.word, self.cfg),
                            danmaku.text_cache_key("b.csv", self.word, self.cfg))

    def test_every_build_text_param_is_in_the_key(self):
        """build_text 读的每个参数都必须进 key：以前漏了 per_pos_meanings。"""
        base = danmaku.text_cache_key("a.csv", self.word, self.cfg)
        for k in ("max_meanings", "max_pos", "per_pos_meanings", "max_cn_len"):
            cfg2 = dict(self.cfg)
            cfg2[k] = (cfg2.get(k) or 0) + 1
            self.assertNotEqual(base, danmaku.text_cache_key("a.csv", self.word, cfg2), k)


# ---------------------------------------------------------------- 配置读写

class ConfigIOTest(unittest.TestCase):

    def setUp(self):
        self.dir = _mkdtemp()
        self.path = os.path.join(self.dir, "config.json")
        self._log = danmaku.LOG_PATH
        danmaku.LOG_PATH = os.path.join(self.dir, "error.log")

    def tearDown(self):
        danmaku.LOG_PATH = self._log
        shutil.rmtree(self.dir, ignore_errors=True)

    def _log_text(self):
        if not os.path.exists(danmaku.LOG_PATH):
            return ""
        with open(danmaku.LOG_PATH, "r", encoding="utf-8") as f:
            return f.read()

    def test_round_trip(self):
        self.assertTrue(danmaku.write_config({"opacity": 0.5}, self.path))
        self.assertEqual(danmaku.read_config(self.path), {"opacity": 0.5})

    def test_atomic_write_leaves_no_tmp(self):
        danmaku.write_config({"a": 1}, self.path)
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_missing_file_is_empty_dict(self):
        self.assertEqual(danmaku.read_config(os.path.join(self.dir, "无.json")), {})

    def test_corrupt_file_falls_back_and_logs(self):
        """现场真的出现过 0 字节的 config.json：必须留痕，不许静默。"""
        with open(self.path, "w", encoding="utf-8"):
            pass
        self.assertEqual(danmaku.read_config(self.path), {})
        self.assertIn("config", self._log_text())

    def test_non_object_top_level_is_ignored(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("[1, 2, 3]")
        self.assertEqual(danmaku.read_config(self.path), {})
        self.assertIn("config", self._log_text())


# ---------------------------------------------------------------- 词书 IO

class FavouriteBookTest(unittest.TestCase):

    def setUp(self):
        self.dir = _mkdtemp()
        self._books, self._fav = danmaku.BOOKS_DIR, danmaku.FAV_BOOK_PATH
        danmaku.BOOKS_DIR = self.dir
        danmaku.FAV_BOOK_PATH = os.path.join(self.dir, danmaku.FAV_BOOK_NAME)

    def tearDown(self):
        danmaku.BOOKS_DIR, danmaku.FAV_BOOK_PATH = self._books, self._fav
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_header_only_book_loads_empty(self):
        self.assertTrue(danmaku.ensure_fav_book())
        self.assertEqual(danmaku.load_words(danmaku.FAV_BOOK_PATH), [])

    def test_write_then_load_round_trip(self):
        rows = [danmaku.fav_row({"word": "zeta", "accent": "/z/", "mean_cn": "n. 泽塔"}),
                danmaku.fav_row({"word": "alpha", "accent": "/a/", "mean_cn": "n. 阿尔法"})]
        self.assertTrue(danmaku.write_fav_rows(rows))
        words = danmaku.load_words(danmaku.FAV_BOOK_PATH)
        self.assertEqual([w["word"] for w in words], ["alpha", "zeta"])   # 按字母序
        self.assertEqual(words[0]["mean_cn"], "n. 阿尔法")                 # 原始串要留着
        self.assertEqual(words[0]["senses"], [("n.", ["阿尔法"])])

    def test_bom_and_crlf(self):
        danmaku.write_fav_rows([danmaku.fav_row({"word": "a", "mean_cn": "n. 甲"})])
        with open(danmaku.FAV_BOOK_PATH, "rb") as f:
            raw = f.read()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))   # UTF-8 BOM，Excel 双击不乱码
        self.assertIn(b"\r\n", raw)


class ResolveBookTest(unittest.TestCase):

    def setUp(self):
        self.dir = _mkdtemp()
        self._books = danmaku.BOOKS_DIR
        danmaku.BOOKS_DIR = self.dir

    def tearDown(self):
        danmaku.BOOKS_DIR = self._books
        shutil.rmtree(self.dir, ignore_errors=True)

    def _touch(self, name):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8-sig") as f:
            f.write("word,accent,mean_cn\r\n")

    def test_no_books(self):
        self.assertEqual(danmaku.resolve_book({}), (None, None))

    def test_prefers_default_book(self):
        self._touch("zzz.csv")
        self._touch(danmaku.DEFAULT_BOOK_NAME)
        self.assertEqual(danmaku.resolve_book({})[0], os.path.splitext(danmaku.DEFAULT_BOOK_NAME)[0])

    def test_unknown_name_falls_back(self):
        self._touch("zzz.csv")
        self._touch(danmaku.DEFAULT_BOOK_NAME)
        self.assertEqual(danmaku.resolve_book({"book": "没这本.csv"})[0],
                         os.path.splitext(danmaku.DEFAULT_BOOK_NAME)[0])

    def test_falls_back_to_first_book(self):
        self._touch("zzz.csv")
        self._touch("aaa.csv")
        self.assertEqual(danmaku.resolve_book({})[0], "aaa")     # 没有默认那本就用第一本


# ---------------------------------------------------------------- 字体

IPA_SAMPLE = "/əˈpiːl/"


class FontCmapTest(unittest.TestCase):

    def test_lolita_covers_full_width_punct(self):
        path = os.path.join(danmaku.FONT_DIR, "Lolita.ttf")
        if not os.path.exists(path):
            self.skipTest("fonts/Lolita.ttf 不在")
        cov = danmaku._ttf_codepoints(path)
        self.assertGreater(len(cov), 1000)
        for ch in "；，。（）：【】／｜～？！．、…—·":
            self.assertIn(ord(ch), cov, ch)

    def test_ipa_has_at_least_one_covering_face(self):
        """PHON_FACE_FALLBACK 这条退路的前提：本机至少有一支字体能画全 IPA。

        注意微软雅黑**不满足**（GDI 实测 ə ɜ ɪ ʊ ˈ ː 都无字形），现在音标能显示
        靠的是系统 font linking 逐字兜底 —— 所以这个断言针对的是"退路存在"，
        不是说雅黑自己行。"""
        for face in (danmaku.PHON_FACE, "Segoe UI", "Arial"):
            path = danmaku.font_file_for_family(face)
            if not path:
                continue
            cov = danmaku._ttf_codepoints(path)
            if cov and all(ord(ch) in cov for ch in IPA_SAMPLE):
                return
        self.skipTest("本机没找到能画全 IPA 的字体文件")


# ---------------------------------------------------------------- GDI 位图

class RenderBitmapTest(unittest.TestCase):

    def test_renders_png(self):
        if not danmaku._GDI_OK:
            self.skipTest("GDI 路径在本机不可用")
        out = danmaku.render_text_bitmap([(True, "appeal"), (True, " v. 请求")], 40,
                                         danmaku.PHON_FACE, "Microsoft YaHei",
                                         (255, 255, 255), 32, 48)
        self.assertIsNotNone(out, "GDI 位图没渲染出来（argtypes 写错会静默退回慢路径）")
        w, h, png, ox, oy = out
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(danmaku._GDI_OK, "渲染过程中 _GDI_OK 被打掉了")


# ---------------------------------------------------------------- 时钟 / 热键

class PauseClockTest(unittest.TestCase):

    def test_pause_resets_the_same_clock_tick_reads(self):
        """set_paused 重置的基线必须和 tick 读的是同一个时钟。

        老代码 set_paused 写 time.monotonic()、tick 读 time.perf_counter()，
        两个时钟在 Windows 上基准不同（本机实测差 35ms），于是每次「继续」
        第一帧都会按那 35ms 多走一步。"""
        # 只看代码、不看注释 —— 注释里正好会提到那个被换掉的旧时钟名
        def code(fn):
            return "\n".join(line for line in inspect.getsource(fn).splitlines()
                              if not line.strip().startswith("#"))

        self.assertIn("perf_counter", code(danmaku.DanmakuLayer.set_paused))
        self.assertNotIn("monotonic", code(danmaku.DanmakuLayer.set_paused))
        self.assertIn("perf_counter", code(danmaku.DanmakuLayer.tick))


class GlobalHotkeysTest(unittest.TestCase):

    def test_register_and_dispatch(self):
        """注册 + WM_HOTKEY 分发这条链路要能跑通。

        用 Ctrl+Alt+F11 这种没人占的组合；注册不到就跳过（被别的程序占着是
        正常情况，调用方此时会退回 bind_all）。"""
        got = []
        hk = danmaku.GlobalHotkeys(got.append)
        try:
            if not hk.start([("probe", 0x7A)]):      # VK_F11
                self.skipTest("热键被别的程序占着")
            self.assertTrue(hk._tid)
            ctypes.windll.user32.PostThreadMessageW(
                hk._tid, danmaku.GlobalHotkeys.WM_HOTKEY, 1, 0)
            for _ in range(100):
                if got:
                    break
                time.sleep(0.02)
            self.assertEqual(got, ["probe"])
        finally:
            hk.stop()


class SliderWidgetTest(unittest.TestCase):
    """番茄滑块把「标题 + 数值」收进自己身上之后，数值标签得跟着 value 走。"""

    @classmethod
    def setUpClass(cls):
        try:
            cls.root = danmaku.tk.Tk()
        except Exception as e:          # 没有图形环境（比如 CI）就跳过
            raise unittest.SkipTest("没有可用的 Tk 环境：%r" % (e,))
        cls.root.withdraw()             # 别真的弹一个窗口出来

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def test_float_label_follows_value(self):
        s = danmaku.TomatoSlider(self.root, 0.0, 1.0, 0.5,
                                 lambda v: "%.0f%%" % (v * 100))
        self.assertEqual(s.display(), "50%")
        s.set(0.42)
        self.assertEqual(s.var.get(), "42%")
        s.set(2.0)                      # 超出范围要钳到上界
        self.assertEqual(s.get(), 1.0)
        self.assertEqual(s.var.get(), "100%")

    def test_int_label_is_integer(self):
        s = danmaku.TomatoSlider(self.root, 1, 8, 5, str, integer=True)
        self.assertEqual(s.display(), "5")
        s.set(3.7)                      # 整数档要四舍五入，而且不能显示成 "4.0"
        self.assertEqual(s.get(), 4)
        self.assertEqual(s.var.get(), "4")


# ---------------------------------------------------------------- 读音文件

class AudioLookupTest(unittest.TestCase):
    """
    点喇叭按单词找音频。这里用临时目录造几个文件来验，不碰真的 audio\\。

    查找必须宽容：词表里的词和抓下来的文件名未必字字相同（大小写、
    `a.m.` 这类带点的词），找一个都不中就静音，但**能对上就别放过**。
    """

    def setUp(self):
        self.dir = _mkdtemp()
        for name in ("verbal.mp3", "A.M..mp3", "well-being.mp3", "_failed.txt"):
            with open(os.path.join(self.dir, name), "wb") as f:
                f.write(b"x")
        danmaku._audio_index_cache.clear()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_exact_hit(self):
        p = danmaku.audio_path_for("verbal", self.dir)
        self.assertEqual(os.path.basename(p), "verbal.mp3")

    def test_case_insensitive(self):
        p = danmaku.audio_path_for("VERBAL", self.dir)
        self.assertEqual(os.path.basename(p), "verbal.mp3")

    def test_punctuation_fallback(self):
        """`a.m.` 里的点、连字符丢掉了也还能找回来。"""
        self.assertEqual(os.path.basename(danmaku.audio_path_for("a.m.", self.dir)),
                         "A.M..mp3")
        self.assertEqual(os.path.basename(danmaku.audio_path_for("well being", self.dir)),
                         "well-being.mp3")

    def test_non_audio_file_ignored(self):
        self.assertIsNone(danmaku.audio_path_for("_failed", self.dir))

    def test_missing_and_empty(self):
        self.assertIsNone(danmaku.audio_path_for("nothere", self.dir))
        self.assertIsNone(danmaku.audio_path_for("", self.dir))
        self.assertIsNone(danmaku.audio_path_for(None, self.dir))

    def test_broken_dir_is_silent(self):
        self.assertIsNone(danmaku.audio_path_for("verbal", os.path.join(self.dir, "无此目录")))


# ---------------------------------------------------------------- 信息行图标

class HoverIconLayoutTest(unittest.TestCase):
    """
    信息行右端「喇叭 · 放大镜 · 星」的坐标。

    这些数字以前是**两套**各写一遍的算式（框要撑多宽 / 图标画在哪），一旦对不上
    就是图标静悄悄跑到框外。下面几条断言专门盯这类漂移。
    """

    SR, MR, HR, IGAP, IPAD, GAP = 20, 18, 20, 14, 40, 20

    def _lay(self, bx1=1000.0):
        return danmaku.hover_icons(bx1, 100.0, self.IPAD, self.GAP,
                                   self.SR, self.MR, self.HR, self.IGAP)

    def test_left_to_right_order(self):
        ic = self._lay()
        self.assertLess(ic["sound"], ic["dict"])
        self.assertLess(ic["dict"], ic["star"])

    def test_icon_gaps_match_the_constants(self):
        ic = self._lay()
        self.assertAlmostEqual(ic["dict"] - ic["sound"], self.HR + self.IGAP + self.MR)
        self.assertAlmostEqual(ic["star"] - ic["dict"], self.MR + self.IGAP + self.SR)

    def test_star_sits_at_the_right_padding(self):
        ic = self._lay(1000.0)
        self.assertAlmostEqual(ic["star"] + self.SR, 1000.0 - self.IPAD)

    def test_back_is_just_wide_enough(self):
        """
        把框撑到 `ipad + 音标宽 + back` 之后，音标得到的可用宽度内**正好**装得下
        那么宽的音标 —— 这就是"框变宽但图标没跟着挪"那类漂移的守门断言。
        """
        bx0, acc_w = 0.0, 120.0
        need = self.IPAD + acc_w + self._lay()["back"]
        ic = danmaku.hover_icons(bx0 + need, 100.0, self.IPAD, self.GAP,
                                 self.SR, self.MR, self.HR, self.IGAP)
        self.assertAlmostEqual(ic["txt_r"] - (bx0 + self.IPAD), acc_w)
        self.assertGreater(ic["txt_r"], bx0)

    def test_every_icon_stays_inside_the_box(self):
        bx0, acc_w = 0.0, 120.0
        need = self.IPAD + acc_w + self._lay()["back"]
        bx1 = bx0 + need
        ic = danmaku.hover_icons(bx1, 100.0, self.IPAD, self.GAP,
                                 self.SR, self.MR, self.HR, self.IGAP)
        for key, r in (("sound", self.HR), ("dict", self.MR), ("star", self.SR)):
            self.assertGreaterEqual(ic[key] - r, bx0, "%s 跑到框左边外面了" % key)
            self.assertLessEqual(ic[key] + r, bx1, "%s 跑到框右边外面了" % key)

    def test_hit_boxes_do_not_overlap(self):
        """
        三个命中框各自外扩 3px，图标之间的空当（igap）要留得比这更大，
        否则会出现"点两个图标中间，却触发了其中一个"。
        """
        ic = self._lay()
        self.assertGreater(self.IGAP, 6)
        self.assertGreaterEqual(ic["dict"] - self.MR - 3 - (ic["sound"] + self.HR + 3), 0)
        self.assertGreaterEqual(ic["star"] - self.SR - 3 - (ic["dict"] + self.MR + 3), 0)

    def test_speaker_fits_in_its_half_size(self):
        """喇叭的顶点都该落在 ±r 里，_icon_box 的退路（按 r 估框）才是对的。"""
        pts = danmaku.speaker_pts(0.0, 0.0, 10.0)
        xs, ys = pts[0::2], pts[1::2]
        self.assertGreaterEqual(min(xs), -10.0)
        self.assertLessEqual(max(xs), 10.0)
        self.assertLessEqual(max(abs(v) for v in ys), 10.0)

    def test_click_boxes_use_the_drawn_ink(self):
        """
        镜片**圆圈内部**必须在放大镜命中框里（宇专门提过这条）。

        判定框取的是"画出来的墨迹"而不是推出来的尺寸，所以这条只能连真画布一起验：
        空心的圆里那一片空当也得算在判定区里。
        """
        try:
            root = danmaku.tk.Tk()
        except Exception as e:
            raise unittest.SkipTest("没有可用的 Tk 环境：%r" % (e,))
        try:
            root.withdraw()
            cfg = dict(danmaku.DEFAULT_CONFIG)
            layer = danmaku.DanmakuLayer(root, cfg, 1200, 800, danmaku.FONTS)
            layer.canvas.delete("all")
            sr, mr, hr = 20, 18, 20
            ic = danmaku.hover_icons(900.0, 60.0, 30, 20, sr, mr, hr, 14)
            c = layer.canvas
            dids = [c.create_oval(ic["dict"] - 11, 49, ic["dict"] + 11, 71,
                                  outline="#fff", width=5),
                    c.create_line(ic["dict"] + 8, 68, ic["dict"] + 20, 80,
                                  fill="#fff", width=6)]
            box = layer._icon_box(dids, ic["dict"], 60.0, mr)
            lens_cx, lens_cy = ic["dict"], 60.0        # 圆心：靠挪正保证落在这里
            self.assertTrue(box[0] <= lens_cx <= box[2] and box[1] <= lens_cy <= box[3],
                            "镜片圆心 %s 不在命中框 %s 里" % ((lens_cx, lens_cy), box))
            layer.destroy()
        finally:
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
