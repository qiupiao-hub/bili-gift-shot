# -*- coding: utf-8 -*-
"""
B站直播 · 礼物自动截图（直播姬 / OBS / 浏览器通用）

监听直播间礼物、醒目留言、上舰事件，收到后延迟一小会儿，
把指定窗口的画面截下来（Windows Graphics Capture，被其他窗口挡住也能截），
同时把礼物信息写进 CSV，方便事后按时间点从录播里抽高清帧。

用法：
    python gift_shot.py                 # 按 config.json 运行
    python gift_shot.py --setup         # 设置向导：房间号 / 截哪个窗口 / 金额门槛
    python gift_shot.py --list-windows  # 列出当前窗口标题，用来填 window_title
    python gift_shot.py --test-shot     # 立刻截一张，检查窗口/裁剪对不对
    python gift_shot.py --simulate      # 不发礼物也走一遍"收礼物→截图→写CSV"
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import ctypes
import json
import logging
import os
import queue
import re
import sys
import threading
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))

import blivedm  # noqa: E402  (vendored)
import blivedm.models.web as web_models  # noqa: E402

log = logging.getLogger("gift_shot")

DEFAULT_CONFIG: dict[str, Any] = {
    "room_id": 0,
    "sessdata": "",
    "window_title": "夸克",
    "window_hwnd": 0,
    "delay_seconds": 1.0,
    "min_price_gift": 10.0,
    "min_price_sc": 0.0,
    "guard_levels": [1, 2, 3],
    "capture_gift": True,
    "capture_sc": True,
    "capture_guard": True,
    "include_silver_gift": False,
    "crop": None,
    "out_dir": "shots",
    "log_csv": "shots/gifts.csv",
    "image_format": "png",
    "window_timeout_seconds": 3.0,
}

# 上舰等级：1 总督 / 2 提督 / 3 舰长
GUARD_NAMES = {1: "总督", 2: "提督", 3: "舰长"}


# --------------------------------------------------------------------------- #
# Windows 窗口工具（ctypes，无第三方依赖）
# --------------------------------------------------------------------------- #
user32 = ctypes.WinDLL("user32", use_last_error=True)


def _window_text(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def enable_dpi_awareness() -> None:
    """让窗口坐标和截图都用物理像素，否则 125%/150% 缩放下 crop 会错位。"""
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:  # noqa: BLE001
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        return
    except Exception:  # noqa: BLE001
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)


def capture_printwindow(hwnd: int):
    """备用截图：PrintWindow(PW_RENDERFULLCONTENT)。浏览器/Electron 窗口通常能截到内容。"""
    import numpy as np

    _, _, w, h = _window_rect(hwnd)
    if w <= 0 or h <= 0 or w * h > 8192 * 8192:
        return None
    hdc = user32.GetWindowDC(hwnd)
    if not hdc:
        return None
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    try:
        if not user32.PrintWindow(hwnd, mdc, 0x00000002):
            return None
        bi = _BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bi.biWidth = w
        bi.biHeight = -h  # 负数 = 自上而下
        bi.biPlanes = 1
        bi.biBitCount = 32
        buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0):
            return None
        arr = np.frombuffer(buf.raw, np.uint8).reshape(h, w, 4)
        if not arr.any():  # 全黑 = 窗口没渲染（常见于最小化）
            return None
        # 整张只有一个颜色（PrintWindow 对最小化/未渲染的窗口常返回一片灰）也算失败
        sample = arr[:: max(1, h // 24), :: max(1, w // 24), :3].reshape(-1, 3)
        if int(sample.max()) - int(sample.min()) < 8:
            return None
        return arr.copy()
    finally:
        try:
            gdi32.SelectObject(mdc, old)
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mdc)
        finally:
            user32.ReleaseDC(hwnd, hdc)


def list_windows() -> list[dict[str, Any]]:
    """枚举所有可见的顶层窗口。"""
    items: list[dict[str, Any]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):  # noqa: ANN001
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _window_text(hwnd)
        if not title.strip():
            return True
        x, y, w, h = _window_rect(hwnd)
        items.append(
            {
                "hwnd": int(hwnd),
                "title": title,
                "class": _window_class(hwnd),
                "rect": (x, y, w, h),
                "minimized": bool(user32.IsIconic(hwnd)),
            }
        )
        return True

    user32.EnumWindows(_cb, 0)
    return items


def find_window(title_substr: str, hwnd: int = 0) -> Optional[dict[str, Any]]:
    """按 HWND 或标题关键字找窗口；同名的取面积最大的那个。

    关键字可以用 | 分隔多个候选，例如 "直播姬|直播间"。
    """
    wins = list_windows()
    if hwnd:
        for w in wins:
            if w["hwnd"] == hwnd:
                return w
        return None
    keys = [k.strip().lower() for k in str(title_substr).split("|") if k.strip()]
    if not keys:
        return None
    matched = [w for w in wins if any(k in w["title"].lower() for k in keys)]
    if not matched:
        return None
    matched.sort(key=lambda w: w["rect"][2] * w["rect"][3], reverse=True)
    return matched[0]


# --------------------------------------------------------------------------- #
# 截图（Windows Graphics Capture，窗口被遮挡也能截）
# --------------------------------------------------------------------------- #
class ShotWorker(threading.Thread):
    """串行的截图线程：一次只开一个 WGC 会话，避免并发把编码器打满。"""

    def __init__(self, cfg: dict[str, Any]) -> None:
        super().__init__(name="shot-worker", daemon=True)
        self.cfg = cfg
        self.q: "queue.Queue[Optional[dict[str, Any]]]" = queue.Queue(maxsize=8)
        self._stop = False

    def stop(self) -> None:
        self._stop = True
        try:
            self.q.put_nowait(None)
        except queue.Full:
            pass

    def run(self) -> None:
        while not self._stop:
            job = self.q.get()
            if job is None:
                break
            ok = False
            try:
                ok = self._shoot(job["hwnd"], job["path"])
            except Exception:  # noqa: BLE001
                log.exception("截图失败")
            job["cb"](ok, job["path"])

    def _shoot(self, hwnd: int, path: Path) -> bool:
        if user32.IsIconic(hwnd):
            log.warning("窗口已最小化，截不到画面（请还原窗口）：hwnd=%s", hwnd)
            return False
        img = None
        try:
            img = self._capture_wgc(hwnd)
        except Exception as exc:  # noqa: BLE001
            log.debug("WGC 截图失败：%s", exc)
        if img is None:
            img = capture_printwindow(hwnd)
            if img is not None:
                log.info("WGC 没拿到画面，已用 PrintWindow 备用方式截到")
        if img is None:
            log.warning("窗口没有返回画面（最小化时 Windows 截不到，请还原）：hwnd=%s", hwnd)
            return False

        crop = self.cfg.get("crop")
        if crop:
            x, y, w, h = [int(v) for v in crop]
            part = img[y : y + h, x : x + w]
            if part.size:
                img = part
            else:
                log.warning("crop 超出画面范围，按原图保存")

        return self._save(img, path)

    def _capture_wgc(self, hwnd: int):
        from windows_capture import WindowsCapture

        timeout = float(self.cfg.get("window_timeout_seconds", 3.0))
        holder: dict[str, Any] = {}
        done = threading.Event()

        cap = WindowsCapture(
            window_hwnd=int(hwnd),
            cursor_capture=False,
            draw_border=False,
        )

        @cap.event
        def on_frame_arrived(frame, control):  # noqa: ANN001
            try:
                holder["img"] = frame.frame_buffer.copy()  # BGRA
                holder["w"], holder["h"] = frame.width, frame.height
            finally:
                control.stop()
                done.set()

        @cap.event
        def on_closed():
            done.set()

        control = cap.start_free_threaded()
        finished = done.wait(timeout)
        try:
            control.stop()
            control.wait()
        except Exception:  # noqa: BLE001
            pass
        return holder.get("img") if finished else None

    def _save(self, img, path: Path) -> bool:  # noqa: ANN001
        import cv2
        import numpy as np

        bgr = np.ascontiguousarray(img[:, :, :3])
        ext = path.suffix.lower()
        if ext in (".jpg", ".jpeg"):
            ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        else:
            ok, buf = cv2.imencode(".png", bgr)
        if not ok:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        # 用 numpy.tofile 写，避免 cv2.imwrite 不认中文路径
        buf.tofile(str(path))
        return path.exists()


# --------------------------------------------------------------------------- #
# CSV 记录
# --------------------------------------------------------------------------- #
CSV_HEADER = ["时间", "类型", "UID", "昵称", "礼物", "数量", "金额元", "图片", "详情"]


class CsvLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        new = not self.path.exists() or self.path.stat().st_size == 0
        self._fh = open(self.path, "a", newline="", encoding="utf-8-sig")
        self._writer = csv.writer(self._fh)
        if new:
            self._writer.writerow(CSV_HEADER)
            self._fh.flush()

    def write(self, row: list[Any]) -> None:
        with self.lock:
            self._writer.writerow(row)
            self._fh.flush()

    def close(self) -> None:
        with self.lock:
            try:
                self._fh.close()
            except Exception:  # noqa: BLE001
                pass


# --------------------------------------------------------------------------- #
# 事件 → 截图调度
# --------------------------------------------------------------------------- #
_SAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f\s]+')


def safe_name(s: str, limit: int = 40) -> str:
    s = _SAFE.sub("_", s or "").strip("_")
    return s[:limit] or "unknown"


class Scheduler:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        cfg: dict[str, Any],
        worker: ShotWorker,
        csvlog: CsvLogger,
        out_dir: Path,
    ) -> None:
        self.loop = loop
        self.cfg = cfg
        self.worker = worker
        self.csvlog = csvlog
        self.out_dir = out_dir
        self.pending: dict[str, asyncio.TimerHandle] = {}
        self.payloads: dict[str, dict[str, Any]] = {}
        self.delay = float(cfg.get("delay_seconds", 1.0))
        self.count = 0
        # GUI 用：每写一行 CSV 就回调一次（在截图线程里调用）
        self.on_row: Optional[Callable[[dict[str, Any]], None]] = None

    # -- 调度 ---------------------------------------------------------------
    def schedule(self, key: str, payload: dict[str, Any]) -> None:
        """同一 key（同一个人连击同一礼物）只保留最后一次，避免刷屏式连拍。"""
        handle = self.pending.pop(key, None)
        if handle is not None:
            handle.cancel()
            payload = self._merge_payload(self.payloads.get(key), payload)
        self.payloads[key] = payload
        self.pending[key] = self.loop.call_later(self.delay, self._fire, key)

    def _merge_payload(self, old: Optional[dict[str, Any]], new: dict[str, Any]) -> dict[str, Any]:
        if not old:
            return new
        merged = dict(new)
        merged["num"] = int(old.get("num", 0)) + int(new.get("num", 0))
        merged["amount"] = float(old.get("amount", 0.0)) + float(new.get("amount", 0.0))
        merged["combo"] = int(old.get("combo", 1)) + 1
        return merged

    def _fire(self, key: str) -> None:
        payload = self.payloads.pop(key, None)
        self.pending.pop(key, None)
        if not payload:
            return
        fire_time = datetime.now()
        stem = "{}_{}_{}_{}".format(
            fire_time.strftime("%Y%m%d_%H%M%S"),
            payload["uid"],
            safe_name(payload["uname"], 20),
            safe_name(payload["gift"], 24),
        )
        ext = ".jpg" if self.cfg.get("image_format") == "jpg" else ".png"
        path = self.out_dir / f"{stem}{ext}"

        win = find_window(str(self.cfg.get("window_title", "")), int(self.cfg.get("window_hwnd", 0) or 0))
        if win is None:
            log.warning("找不到窗口 %r，跳过截图", self.cfg.get("window_title"))
            self._log_row(fire_time, payload, "", "窗口未找到")
            return
        if win["minimized"]:
            log.warning("窗口 %r 已最小化，截不到画面", win["title"])
            self._log_row(fire_time, payload, "", "窗口最小化")
            return

        def _cb(ok: bool, p: Path) -> None:
            self._log_row(fire_time, payload, str(p) if ok else "", "" if ok else "截图失败")
            if ok:
                log.info("已截图 %s", p)

        try:
            self.worker.q.put_nowait(
                {"hwnd": win["hwnd"], "path": path, "cb": _cb}
            )
        except queue.Full:
            log.warning("截图队列已满，丢弃本次")
            self._log_row(fire_time, payload, "", "队列已满")

    def _log_row(self, ts: datetime, p: dict[str, Any], image: str, note: str) -> None:
        self.count += 1
        detail = p.get("detail", "")
        if p.get("combo", 1) > 1:
            detail = f"{detail} 连击x{p['combo']}".strip()
        self.csvlog.write(
            [
                ts.strftime("%Y-%m-%d %H:%M:%S"),
                p["type"],
                p["uid"],
                p["uname"],
                p["gift"],
                p["num"],
                f"{p['amount']:.2f}",
                image,
                note or detail,
            ]
        )
        if self.on_row is not None:
            try:
                self.on_row(
                    {
                        "time": ts.strftime("%Y-%m-%d %H:%M:%S"),
                        "type": p["type"],
                        "uid": p["uid"],
                        "uname": p["uname"],
                        "gift": p["gift"],
                        "num": p["num"],
                        "amount": float(p["amount"]),
                        "image": image,
                        "detail": note or detail,
                    }
                )
            except Exception:  # noqa: BLE001
                log.exception("GUI 回调失败")

    # -- 入口 ---------------------------------------------------------------
    def on_gift(self, m: web_models.GiftMessage) -> None:
        gold = (m.coin_type or "gold") == "gold"
        if gold:
            amount = float(m.total_coin) / 1000.0
            if amount < float(self.cfg.get("min_price_gift", 0)):
                return
        else:
            # 银瓜子/免费礼物：金额按 0 算，只要开了 include_silver_gift 就截
            if not self.cfg.get("include_silver_gift", False):
                return
            amount = 0.0
        payload = {
            "type": "礼物",
            "uid": m.uid,
            "uname": m.uname or "匿名",
            "gift": m.gift_name,
            "num": int(m.num) or 1,
            "amount": amount,
            "combo": 1,
            "detail": f"coin={m.total_coin}",
        }
        # 有些观众隐藏了 UID（m.uid == 0），这时用昵称区分，免得把不同人的连击合并到一起
        who = m.uid if m.uid else f"n:{m.uname or ''}"
        self.schedule(f"gift:{who}:{m.gift_id}", payload)

    def on_guard(self, m: web_models.GuardBuyMessage) -> None:
        levels = [int(x) for x in self.cfg.get("guard_levels", [1, 2, 3])]
        if int(m.guard_level) not in levels:
            return
        payload = {
            "type": "上舰",
            "uid": m.uid,
            "uname": m.username or "匿名",
            "gift": GUARD_NAMES.get(int(m.guard_level), f"guard{m.guard_level}"),
            "num": 1,
            "amount": float(m.price) / 1000.0,
            "combo": 1,
            "detail": f"guard_level={m.guard_level} price={m.price}",
        }
        who = m.uid if m.uid else f"n:{m.username or ''}"
        self.schedule(f"guard:{who}:{int(time.time()) // 10}", payload)

    def on_sc(self, m: web_models.SuperChatMessage) -> None:
        if float(m.price) < float(self.cfg.get("min_price_sc", 0)):
            return
        payload = {
            "type": "醒目留言",
            "uid": m.uid,
            "uname": m.uname or "匿名",
            "gift": "SC",
            "num": 1,
            "amount": float(m.price),
            "combo": 1,
            "detail": (m.message or "")[:60],
        }
        who = m.uid if m.uid else f"n:{m.uname or ''}"
        self.schedule(f"sc:{who}:{m.id}", payload)


# --------------------------------------------------------------------------- #
# blivedm 处理器
# --------------------------------------------------------------------------- #
class GiftHandler(blivedm.BaseHandler):
    def __init__(self, sched: Scheduler) -> None:
        super().__init__()
        self.sched = sched

    def _on_gift(self, client, message):  # noqa: ANN001
        try:
            self.sched.on_gift(message)
        except Exception:  # noqa: BLE001
            log.exception("处理礼物事件失败")

    def _on_buy_guard(self, client, message):  # noqa: ANN001
        try:
            self.sched.on_guard(message)
        except Exception:  # noqa: BLE001
            log.exception("处理上舰事件失败")

    def _on_super_chat(self, client, message):  # noqa: ANN001
        try:
            self.sched.on_sc(message)
        except Exception:  # noqa: BLE001
            log.exception("处理SC事件失败")


class FakeGift:
    def __init__(self) -> None:
        self.uid = 12345
        self.uname = "测试用户"
        self.gift_name = "小电视飞船"
        self.num = 1
        self.total_coin = 100000
        self.coin_type = "gold"
        self.gift_id = 999
        self.action = "feed"


# --------------------------------------------------------------------------- #
# 配置 / 启动
# --------------------------------------------------------------------------- #
def load_config(path: Path) -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8-sig")))
        except Exception as e:  # noqa: BLE001
            log.error("读取 %s 失败：%s", path, e)
    else:
        path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("已生成默认配置 %s，请先填 room_id", path)
    return cfg


def save_config(path: Path, cfg: dict[str, Any]) -> None:
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def setup_console() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:  # noqa: BLE001
        pass
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    logging.getLogger("blivedm").setLevel(logging.ERROR)  # 未知 cmd 的 WARNING 太吵
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


def do_list_windows() -> None:
    wins = list_windows()
    wins.sort(key=lambda w: w["rect"][2] * w["rect"][3], reverse=True)
    print(f"{'HWND':>10}  {'尺寸':>12}  {'最小化':<4}  标题")
    for w in wins:
        x, y, width, height = w["rect"]
        print(f"{w['hwnd']:>10}  {f'{width}x{height}':>12}  {'是' if w['minimized'] else '否':<4}  {w['title']}")
    print("\n把标题里的关键字填到 config.json 的 window_title（或直接填 window_hwnd）")


def do_test_shot(cfg: dict[str, Any], out_dir: Path) -> int:
    win = find_window(str(cfg.get("window_title", "")), int(cfg.get("window_hwnd", 0) or 0))
    if not win:
        print(f"没找到标题包含 {cfg.get('window_title')!r} 的窗口，先运行 --list-windows 看看")
        return 1
    print(f"目标窗口：{win['title']}  hwnd={win['hwnd']}  rect={win['rect']}")
    if win["minimized"]:
        print("窗口是最小化状态，Windows 截不到，请先还原")
        return 1
    out = out_dir / f"_test_{datetime.now():%H%M%S}.png"
    worker = ShotWorker(cfg)
    worker.start()
    result: dict[str, bool] = {}
    ev = threading.Event()

    def cb(ok: bool, p: Path) -> None:
        result["ok"] = ok
        result["path"] = p  # type: ignore[assignment]
        ev.set()

    worker.q.put({"hwnd": win["hwnd"], "path": out, "cb": cb})
    ev.wait(float(cfg.get("window_timeout_seconds", 3.0)) + 2)
    worker.stop()
    if result.get("ok"):
        p = Path(str(result["path"]))
        print(f"成功：{p}  ({p.stat().st_size / 1024:.0f} KB)")
        return 0
    print("失败：窗口没返回画面（最小化 / 受保护窗口 / 显卡驱动问题）")
    return 1


def do_setup(cfg_path: Path) -> int:
    cfg = load_config(cfg_path)
    print("\n=== 设置向导：直接回车 = 保留方括号里的值 ===\n")

    def ask(label: str, default: Any) -> str:
        try:
            v = input(f"{label} [{default}]: ").strip()
        except EOFError:
            v = ""
        return v or str(default)

    def yes(label: str, default: bool = True) -> bool:
        d = "y" if default else "n"
        return ask(f"{label} (y/n)", d).lower().startswith("y")

    room = ask("直播间号（地址栏 live.bilibili.com/ 后面那串数字）", cfg.get("room_id") or "")
    try:
        cfg["room_id"] = int(str(room).strip("/ ").split("/")[0])
    except ValueError:
        print("房间号得是数字")
        return 1

    print("\n要截哪个窗口？")
    print("  1) 浏览器里的直播间网页（礼物横幅/特效最全，推荐）")
    print("  2) 直播姬的「直播间」窗口（官方客户端）")
    print("  3) 自己输入窗口标题关键字")
    choice = ask("选 1/2/3", "1").strip() or "1"
    if choice == "2":
        title = "直播姬|直播间"
    elif choice == "3":
        title = ask("窗口标题关键字（可用 | 分隔多个，取面积最大的匹配）", cfg.get("window_title", ""))
    else:
        default = str(cfg.get("window_title") or "")
        if default in ("", "直播姬|直播间"):
            default = "夸克"
        title = ask("浏览器窗口标题里的关键字（夸克 / Edge / Chrome …）", default)

    cfg["window_title"] = title
    cfg["window_hwnd"] = 0
    win = find_window(title, 0)
    if win:
        print(f"\n已找到：{win['title']}")
        size = f"{win['rect'][2]}x{win['rect'][3]}"
        print(f"  尺寸 {size}，{'最小化中 —— Windows 截不到，记得还原' if win['minimized'] else '可以截图'}")
    else:
        print(f"\n⚠ 现在没有标题含 {title!r} 的窗口，直播时记得先打开它、别最小化")

    price = ask("\n礼物金额门槛（元；0 = 所有礼物都截，含免费小花花）", cfg.get("min_price_gift", 10))
    try:
        cfg["min_price_gift"] = float(price)
    except ValueError:
        print("金额得是数字")
        return 1
    cfg["include_silver_gift"] = yes("银瓜子礼物（小花花、人气票这类）也截吗？", False)
    cfg["capture_sc"] = yes("醒目留言 SC 也截吗？", True)
    cfg["capture_guard"] = yes("上舰（舰长/提督/总督）也截吗？", True)

    save_config(cfg_path, cfg)
    print(f"\n已写入 {cfg_path}")
    print(f"  直播间 {cfg['room_id']}｜窗口 {cfg['window_title']!r}｜门槛 {cfg['min_price_gift']:g} 元")

    if yes("\n现在截一张试试？", True):
        out_dir = (ROOT / str(cfg.get("out_dir", "shots"))).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        return do_test_shot(cfg, out_dir)
    return 0


async def main_async(cfg: dict[str, Any], simulate: bool) -> int:
    out_dir = (ROOT / str(cfg.get("out_dir", "shots"))).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    csvlog = CsvLogger((ROOT / str(cfg.get("log_csv", "shots/gifts.csv"))).resolve())
    worker = ShotWorker(cfg)
    worker.start()

    loop = asyncio.get_running_loop()
    sched = Scheduler(loop, cfg, worker, csvlog, out_dir)

    if simulate:
        log.info("模拟模式：1 秒后伪造一条礼物，%.1f 秒后截图", float(cfg["delay_seconds"]))
        await asyncio.sleep(1)
        sched.on_gift(FakeGift())  # type: ignore[arg-type]
        await asyncio.sleep(float(cfg["delay_seconds"]) + 3)
        worker.stop()
        csvlog.close()
        return 0

    room_id = int(cfg.get("room_id") or 0)
    if room_id <= 0:
        log.error("config.json 里的 room_id 还没填（直播间 URL 里那串数字）")
        worker.stop()
        csvlog.close()
        return 2

    import aiohttp

    session = aiohttp.ClientSession()
    sessdata = str(cfg.get("sessdata") or "").strip()
    if sessdata:
        session.cookie_jar.update_cookies({"SESSDATA": sessdata})

    client = blivedm.BLiveClient(room_id, session=session)
    client.set_handler(GiftHandler(sched))
    client.start()
    log.info("正在监听直播间 %s，礼物门槛 ≥ %.2f 元，截图窗口 %r", room_id,
             float(cfg.get("min_price_gift", 0)), cfg.get("window_title"))
    win = find_window(str(cfg.get("window_title", "")), int(cfg.get("window_hwnd", 0) or 0))
    if not win:
        log.warning("现在没找到标题含 %r 的窗口，礼物来了会截不到；先把它打开再开跑", cfg.get("window_title"))
    elif win["minimized"]:
        log.warning("截图窗口现在是最小化的，Windows 截不到，请还原：%s", win["title"])
    else:
        log.info("截图目标：%s（%dx%d）", win["title"], win["rect"][2], win["rect"][3])
    log.info("按 Ctrl+C 退出")

    try:
        await client.join()
    finally:
        try:
            await client.stop_and_close()
        except Exception:  # noqa: BLE001
            pass
        await session.close()
        worker.stop()
        csvlog.close()
        log.info("共记录 %d 条，CSV: %s", sched.count, csvlog.path)
    return 0


def main() -> int:
    setup_console()
    enable_dpi_awareness()
    parser = argparse.ArgumentParser(description="B站直播礼物自动截图")
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--setup", action="store_true", help="设置向导（房间号/窗口/门槛）")
    parser.add_argument("--list-windows", action="store_true", help="列出所有可见窗口")
    parser.add_argument("--test-shot", action="store_true", help="立即截一张测试图")
    parser.add_argument("--simulate", action="store_true", help="伪造一条礼物，测试截图+CSV")
    parser.add_argument("--room", type=int, default=0, help="临时覆盖 room_id")
    parser.add_argument("--window", default="", help="临时覆盖 window_title")
    parser.add_argument("--min-price", type=float, default=-1, help="临时覆盖 min_price_gift（元）")
    parser.add_argument("--silver", action="store_true", help="临时把银瓜子/免费礼物也纳入截图")
    args = parser.parse_args()

    setup_logging()

    if args.setup:
        return do_setup(Path(args.config))

    if args.list_windows:
        do_list_windows()
        return 0

    cfg = load_config(Path(args.config))
    if args.room:
        cfg["room_id"] = args.room
    if args.window:
        cfg["window_title"] = args.window
    if args.min_price >= 0:
        cfg["min_price_gift"] = args.min_price
    if args.silver:
        cfg["include_silver_gift"] = True
    out_dir = (ROOT / str(cfg.get("out_dir", "shots"))).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.test_shot:
        return do_test_shot(cfg, out_dir)

    try:
        return asyncio.run(main_async(cfg, args.simulate))
    except KeyboardInterrupt:
        print("\n已退出")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
