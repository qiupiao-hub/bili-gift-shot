# -*- coding: utf-8 -*-
"""
B站直播 · 送礼自动截图 · 三主题版（Kitty 粉 / 玉桂狗 蓝白 / 大耳狗 奶油黄）

主播打开就能用：填直播间号 → 选窗口 → 设金额门槛 → 开始监听。
礼物进来自动截图、自动命名、列表里双击就能看，右键直达文件夹。
右上角三个主题按钮，点一下立刻换肤（不用重启，监听不断）。
"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import queue
import random
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

if getattr(sys, "frozen", False):
    BASE = Path(sys.executable).resolve().parent          # exe 旁边：放 config.json / shots
    BUNDLE = Path(getattr(sys, "_MEIPASS", str(BASE)))    # 打包进去的资源：vendor
else:
    BASE = Path(__file__).resolve().parent
    BUNDLE = BASE

for _p in (BUNDLE, BUNDLE / "vendor"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import tkinter as tk  # noqa: E402
from tkinter import messagebox, ttk  # noqa: E402

import gift_shot as core  # noqa: E402

APP_NAME = "B站送礼自动截图"
AUTO_WINDOW = "自动找直播姬的「直播间」窗口"
FONT = "Microsoft YaHei UI"

# --------------------------------------------------------------------------- #
# 三套主题：颜色 + 吉祥物 + 文案
# --------------------------------------------------------------------------- #
THEMES: dict[str, dict[str, str]] = {
    "kitty": {
        "key": "kitty",
        "label": "Kitty · 粉",
        "full": "粉色 Kitty 猫",
        "title": "B站送礼自动截图 · 粉色 Kitty 版",
        "tagline": "粉红小猫陪你营业 ♥",
        "mascot": "kitty",
        "bg": "#FFF0F6", "pale": "#FFE3EF", "soft": "#FFC2D8", "main": "#FF83AE",
        "deep": "#FF5C8D", "dark": "#C93E6C", "card": "#FFFFFF",
        "ink": "#5A3A46", "ink_light": "#9C7383",
        "head1": "#FFE1EE", "head2": "#FFC3DA",
        "head3": "#FFD3E6",
        "title_fill": "#B23A63", "sub_fill": "#D46A90",
        "odd": "#FFF8FB", "shade": "#FFF7FA", "log_bg": "#FFFBFD", "log_fg": "#7A5563",
        "sel": "#FFD3E4", "sel_fg": "#8C2A4E",
        "guard": "#8250DF", "sc": "#D6336C",
        "off": "#F3D7E3", "soft_btn": "#FFE9F2", "soft_hover": "#FFD6E7",
        "ghost_hover": "#FFEFF6", "muted": "#B08A96",
        "green": "#35A97C", "red": "#E5484D",
        "accent2": "#FFD9E8",
    },
    "cinna": {
        "key": "cinna",
        "label": "玉桂狗 · 蓝白",
        "full": "蓝白玉桂狗",
        "title": "B站送礼自动截图 · 玉桂狗版",
        "tagline": "云朵上的小狗陪你营业 ☁",
        "mascot": "cinna",
        "bg": "#F2F7FF", "pale": "#E2EEFF", "soft": "#BBD7FF", "main": "#7FB2F0",
        "deep": "#5B95E0", "dark": "#33639E", "card": "#FFFFFF",
        "ink": "#3C5068", "ink_light": "#7D93AC",
        "head1": "#EAF3FF", "head2": "#C6DFFF",
        "head3": "#D8E9FF",
        "title_fill": "#2F5C96", "sub_fill": "#6C8DB5",
        "odd": "#F7FBFF", "shade": "#F7FBFF", "log_bg": "#FAFCFF", "log_fg": "#5A7086",
        "sel": "#D2E5FF", "sel_fg": "#2C5A93",
        "guard": "#6C5CE7", "sc": "#E0568A",
        "off": "#DCE8F5", "soft_btn": "#EAF3FF", "soft_hover": "#D8E9FF",
        "ghost_hover": "#EFF6FF", "muted": "#8AA5C0",
        "green": "#2E9E7A", "red": "#D9455B",
        "accent2": "#DCEDFF",
    },
    "pompom": {
        "key": "pompom",
        "label": "大耳狗 · 黄",
        "full": "奶油大黄狗",
        "title": "B站送礼自动截图 · 大耳狗版",
        "tagline": "奶油色小狗陪你营业 ✿",
        "mascot": "pompom",
        "bg": "#FFFAEC", "pale": "#FFF1D0", "soft": "#FFDE9E", "main": "#F7C04A",
        "deep": "#E9A62B", "dark": "#96671A", "card": "#FFFFFF",
        "ink": "#5C4A2E", "ink_light": "#9C8A6A",
        "head1": "#FFF8E1", "head2": "#FFE0A0",
        "head3": "#FFE9B8",
        "title_fill": "#8A5E14", "sub_fill": "#B98C3E",
        "odd": "#FFFCF2", "shade": "#FFFCF2", "log_bg": "#FFFDF7", "log_fg": "#7A6849",
        "sel": "#FFEBBF", "sel_fg": "#7C5410",
        "guard": "#8A6CE0", "sc": "#D6457A",
        "off": "#F3E6C8", "soft_btn": "#FFF6E0", "soft_hover": "#FFEAC0",
        "ghost_hover": "#FFF8EA", "muted": "#B7A47E",
        "green": "#3E9B6B", "red": "#D9483F",
        "accent2": "#FFEFC7",
    },
}

CUR: dict[str, str] = dict(THEMES["kitty"])


def apply_theme(key: str) -> str:
    global CUR
    if key not in THEMES:
        key = "kitty"
    CUR = dict(THEMES[key])
    CUR["key"] = key
    return key


def mix(c1: str, c2: str, t: float) -> str:
    a = tuple(int(c1[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(c2[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kw):  # noqa: ANN001
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


# --------------------------------------------------------------------------- #
# 吉祥物（纯 Canvas 手绘，任何分辨率都清晰，不依赖外部图片）
# --------------------------------------------------------------------------- #
def _draw_kitty(cv: tk.Canvas, cx: float, cy: float, r: float, c: dict[str, str]):
    """粉色 Kitty：三角耳朵 + 蝴蝶结 + 胡须。"""
    white, edge = "#FFFFFF", c["soft"]
    body: list[int] = []
    bow: list[int] = []
    body.append(cv.create_polygon(cx - r * 0.92, cy - r * 0.44, cx - r * 0.70, cy - r * 1.14,
                                  cx - r * 0.22, cy - r * 0.54, fill=white, outline=edge, width=2))
    body.append(cv.create_polygon(cx + r * 0.92, cy - r * 0.44, cx + r * 0.70, cy - r * 1.14,
                                  cx + r * 0.22, cy - r * 0.54, fill=white, outline=edge, width=2))
    body.append(cv.create_oval(cx - r * 0.92, cy - r * 0.66, cx + r * 0.92, cy + r * 0.86,
                               fill=white, outline=edge, width=2))
    bx, by = cx - r * 0.74, cy - r * 0.94
    bow.append(cv.create_polygon(bx - 27, by - 13, bx - 5, by - 1, bx - 27, by + 13,
                                 fill=c["main"], outline=c["deep"], width=1))
    bow.append(cv.create_polygon(bx + 27, by - 13, bx + 5, by - 1, bx + 27, by + 13,
                                 fill=c["main"], outline=c["deep"], width=1))
    bow.append(cv.create_oval(bx - 8, by - 8, bx + 8, by + 8, fill=c["deep"], outline=""))
    eye_open = [
        cv.create_oval(cx - r * 0.38, cy - r * 0.10, cx - r * 0.20, cy + r * 0.16,
                       fill=c["ink"], outline=""),
        cv.create_oval(cx + r * 0.20, cy - r * 0.10, cx + r * 0.38, cy + r * 0.16,
                       fill=c["ink"], outline=""),
    ]
    eye_closed = [
        cv.create_line(cx - r * 0.40, cy + r * 0.04, cx - r * 0.18, cy + r * 0.02,
                       fill=c["ink"], width=3, state="hidden", capstyle="round"),
        cv.create_line(cx + r * 0.18, cy + r * 0.02, cx + r * 0.40, cy + r * 0.04,
                       fill=c["ink"], width=3, state="hidden", capstyle="round"),
    ]
    body.extend(eye_open)
    body.extend(eye_closed)
    body.append(cv.create_oval(cx - 5, cy + r * 0.28, cx + 5, cy + r * 0.38,
                               fill=c["deep"], outline=""))
    body.append(cv.create_oval(cx - r * 0.62, cy + r * 0.20, cx - r * 0.40, cy + r * 0.34,
                               fill=c["accent2"], outline=""))
    body.append(cv.create_oval(cx + r * 0.40, cy + r * 0.20, cx + r * 0.62, cy + r * 0.34,
                               fill=c["accent2"], outline=""))
    for dy in (-8, 4, 16):
        body.append(cv.create_line(cx - r * 0.95, cy + r * 0.20 + dy,
                                   cx - r * 0.52, cy + r * 0.26 + dy,
                                   fill="#E39CB8", width=2, capstyle="round"))
        body.append(cv.create_line(cx + r * 0.95, cy + r * 0.20 + dy,
                                   cx + r * 0.52, cy + r * 0.26 + dy,
                                   fill="#E39CB8", width=2, capstyle="round"))
    return body, bow, eye_open, eye_closed


def _draw_cinna(cv: tk.Canvas, cx: float, cy: float, r: float, c: dict[str, str]):
    """玉桂狗（Cinnamoroll）：白色、长垂耳、蓝眼睛、头顶小卷毛 + 云朵。"""
    white, edge = "#FFFFFF", "#BBD7FF"
    body: list[int] = []
    bow: list[int] = []
    # 背后的云
    for dx, dy, rw, rh in ((-1.05, 0.62, 0.42, 0.24), (1.02, 0.66, 0.46, 0.26),
                           (0.0, 0.92, 0.62, 0.28)):
        body.append(cv.create_oval(cx + dx * r - rw * r, cy + dy * r - rh * r,
                                   cx + dx * r + rw * r, cy + dy * r + rh * r,
                                   fill="#EAF4FF", outline=""))
    # 长垂耳
    for s in (-1, 1):
        pts = [cx + s * r * 0.42, cy - r * 0.72, cx + s * r * 0.72, cy - r * 1.00,
               cx + s * r * 0.96, cy - r * 0.58, cx + s * r * 1.10, cy + r * 0.20,
               cx + s * r * 1.02, cy + r * 0.66, cx + s * r * 0.84, cy + r * 0.70,
               cx + s * r * 0.78, cy + r * 0.12, cx + s * r * 0.60, cy - r * 0.32]
        body.append(cv.create_polygon(pts, smooth=True, fill=white, outline=edge, width=2))
        inner = [cx + s * r * 0.58, cy - r * 0.62, cx + s * r * 0.80, cy - r * 0.78,
                 cx + s * r * 0.94, cy - r * 0.40, cx + s * r * 0.98, cy + r * 0.24,
                 cx + s * r * 0.88, cy + r * 0.52, cx + s * r * 0.80, cy + r * 0.30,
                 cx + s * r * 0.76, cy - r * 0.20]
        body.append(cv.create_polygon(inner, smooth=True, fill="#EDF5FF", outline=""))
    # 脸
    body.append(cv.create_oval(cx - r * 0.80, cy - r * 0.62, cx + r * 0.80, cy + r * 0.78,
                               fill=white, outline=edge, width=2))
    # 头顶小卷毛
    body.append(cv.create_arc(cx - r * 0.26, cy - r * 0.86, cx + r * 0.10, cy - r * 0.50,
                              start=20, extent=300, style="arc", outline=c["main"], width=3))
    # 小蓝丝带（系在左耳根）
    bx, by = cx - r * 0.76, cy - r * 0.56
    bow.append(cv.create_polygon(bx - 24, by - 13, bx - 3, by - 1, bx - 24, by + 13,
                                 fill=c["main"], outline=c["deep"]))
    bow.append(cv.create_polygon(bx + 24, by - 13, bx + 3, by - 1, bx + 24, by + 13,
                                 fill=c["main"], outline=c["deep"]))
    bow.append(cv.create_oval(bx - 7, by - 7, bx + 7, by + 7, fill=c["deep"], outline=""))
    eye_open = [
        cv.create_oval(cx - r * 0.36, cy - r * 0.08, cx - r * 0.19, cy + r * 0.18,
                       fill=c["dark"], outline=""),
        cv.create_oval(cx + r * 0.19, cy - r * 0.08, cx + r * 0.36, cy + r * 0.18,
                       fill=c["dark"], outline=""),
        cv.create_oval(cx - r * 0.33, cy - r * 0.04, cx - r * 0.27, cy + r * 0.04,
                       fill="#FFFFFF", outline=""),
        cv.create_oval(cx + r * 0.22, cy - r * 0.04, cx + r * 0.28, cy + r * 0.04,
                       fill="#FFFFFF", outline=""),
    ]
    eye_closed = [
        cv.create_line(cx - r * 0.38, cy + r * 0.06, cx - r * 0.18, cy + r * 0.04,
                       fill=c["dark"], width=3, state="hidden", capstyle="round"),
        cv.create_line(cx + r * 0.18, cy + r * 0.04, cx + r * 0.38, cy + r * 0.06,
                       fill=c["dark"], width=3, state="hidden", capstyle="round"),
    ]
    body.extend(eye_open)
    body.extend(eye_closed)
    # 腮红
    body.append(cv.create_oval(cx - r * 0.62, cy + r * 0.20, cx - r * 0.40, cy + r * 0.36,
                               fill="#FFD3E3", outline=""))
    body.append(cv.create_oval(cx + r * 0.40, cy + r * 0.20, cx + r * 0.62, cy + r * 0.36,
                               fill="#FFD3E3", outline=""))
    # 鼻子
    body.append(cv.create_oval(cx - 5, cy + r * 0.26, cx + 5, cy + r * 0.34,
                               fill="#E39BB5", outline=""))
    return body, bow, eye_open, eye_closed


def _draw_pompom(cv: tk.Canvas, cx: float, cy: float, r: float, c: dict[str, str]):
    """大耳狗（奶油黄小狗）：黄脸 + 棕色长耳 + 贝雷帽。"""
    yellow, edge, brown = "#FFE39B", "#E9B84E", "#C98B3F"
    body: list[int] = []
    bow: list[int] = []
    # 耳朵（棕色，垂在两侧）
    for s in (-1, 1):
        body.append(cv.create_oval(cx + s * r * 0.84 - r * 0.38, cy - r * 0.30,
                                   cx + s * r * 0.84 + r * 0.38, cy + r * 0.88,
                                   fill=brown, outline="#B87A31", width=2))
        body.append(cv.create_oval(cx + s * r * 0.84 - r * 0.20, cy + r * 0.02,
                                   cx + s * r * 0.84 + r * 0.20, cy + r * 0.70,
                                   fill="#E2A65E", outline=""))
    # 脸
    body.append(cv.create_oval(cx - r * 0.88, cy - r * 0.56, cx + r * 0.88, cy + r * 0.80,
                               fill=yellow, outline=edge, width=2))
    # 贝雷帽（歪戴 + 帽顶小揪）
    body.append(cv.create_oval(cx - r * 0.76, cy - r * 0.98, cx + r * 0.50, cy - r * 0.50,
                               fill=brown, outline="#B87A31", width=2))
    body.append(cv.create_oval(cx - r * 0.60, cy - r * 0.84, cx + r * 0.36, cy - r * 0.58,
                               fill="#D2934A", outline=""))
    bow.append(cv.create_oval(cx - r * 0.12, cy - r * 1.14, cx + r * 0.02, cy - r * 0.99,
                              fill=brown, outline="#B87A31"))
    eye_open = [
        cv.create_oval(cx - r * 0.36, cy - r * 0.06, cx - r * 0.18, cy + r * 0.18,
                       fill="#4A3418", outline=""),
        cv.create_oval(cx + r * 0.18, cy - r * 0.06, cx + r * 0.36, cy + r * 0.18,
                       fill="#4A3418", outline=""),
    ]
    eye_closed = [
        cv.create_line(cx - r * 0.38, cy + r * 0.06, cx - r * 0.17, cy + r * 0.04,
                       fill="#4A3418", width=3, state="hidden", capstyle="round"),
        cv.create_line(cx + r * 0.17, cy + r * 0.04, cx + r * 0.38, cy + r * 0.06,
                       fill="#4A3418", width=3, state="hidden", capstyle="round"),
    ]
    body.extend(eye_open)
    body.extend(eye_closed)
    # 腮红 + 鼻子 + 嘴
    body.append(cv.create_oval(cx - r * 0.66, cy + r * 0.22, cx - r * 0.44, cy + r * 0.38,
                               fill="#FFC46B", outline=""))
    body.append(cv.create_oval(cx + r * 0.44, cy + r * 0.22, cx + r * 0.66, cy + r * 0.38,
                               fill="#FFC46B", outline=""))
    body.append(cv.create_oval(cx - 8, cy + r * 0.24, cx + 8, cy + r * 0.34,
                               fill="#8A5E2A", outline=""))
    body.append(cv.create_arc(cx - r * 0.16, cy + r * 0.30, cx + r * 0.16, cy + r * 0.52,
                              start=200, extent=140, style="arc", outline="#8A5E2A", width=2))
    return body, bow, eye_open, eye_closed


PAINTERS: dict[str, Callable[..., Any]] = {
    "kitty": _draw_kitty, "cinna": _draw_cinna, "pompom": _draw_pompom,
}


# --------------------------------------------------------------------------- #
# 日志 → 界面
# --------------------------------------------------------------------------- #
class QueueLogHandler(logging.Handler):
    def __init__(self, q: "queue.Queue[dict[str, Any]]") -> None:
        super().__init__()
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.q.put({"kind": "log", "text": self.format(record)})
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# 监听线程（和核心逻辑对接）
# --------------------------------------------------------------------------- #
class Monitor:
    """把 blivedm 的 asyncio 循环放到后台线程，界面通过回调队列拿结果。"""

    def __init__(self, cfg: dict[str, Any], emit) -> None:  # noqa: ANN001
        self.cfg = dict(cfg)
        self.emit = emit
        self.thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_evt: Optional[asyncio.Event] = None
        self._client = None
        self.sched: Optional[core.Scheduler] = None
        self.worker: Optional[core.ShotWorker] = None
        self.csvlog: Optional[core.CsvLogger] = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._thread_main, daemon=True, name="blivedm")
        self.thread.start()

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:  # noqa: BLE001
            text = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.emit({"kind": "error", "text": f"监听线程异常：{text}"})

    async def _run(self) -> None:
        import aiohttp

        self.loop = asyncio.get_running_loop()
        cfg = self.cfg
        out_dir = (BASE / str(cfg.get("out_dir", "shots"))).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        self.csvlog = core.CsvLogger((BASE / str(cfg.get("log_csv", "shots/gifts.csv"))).resolve())
        self.worker = core.ShotWorker(cfg)
        self.worker.start()
        self.sched = core.Scheduler(self.loop, cfg, self.worker, self.csvlog, out_dir)
        self.sched.on_row = lambda row: self.emit({"kind": "row", "row": row})
        self._stop_evt = asyncio.Event()

        session = aiohttp.ClientSession()
        sessdata = str(cfg.get("sessdata") or "").strip()
        if sessdata:
            session.cookie_jar.update_cookies({"SESSDATA": sessdata})

        self._client = core.blivedm.BLiveClient(int(cfg["room_id"]), session=session)
        self._client.set_handler(core.GiftHandler(self.sched))
        self._client.start()
        self.emit({"kind": "state", "text": "监听中"})
        try:
            await self._stop_evt.wait()
        finally:
            try:
                await self._client.stop_and_close()
            except Exception:  # noqa: BLE001
                pass
            await session.close()
            if self.worker:
                self.worker.stop()
            if self.csvlog:
                self.csvlog.close()
            self.emit({"kind": "state", "text": "已停止"})

    def stop(self) -> None:
        if self.loop and self._stop_evt:
            self.loop.call_soon_threadsafe(self._stop_evt.set)
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=6)


# --------------------------------------------------------------------------- #
# 小部件（颜色全部从 CUR 取，换主题后重建即可）
# --------------------------------------------------------------------------- #
class CuteButton(tk.Button):
    def __init__(self, master, text: str, command, kind: str = "primary", **kw):  # noqa: ANN001
        c = CUR
        if kind == "primary":
            bg, hover, fg, off = c["main"], c["deep"], "#FFFFFF", c["off"]
        elif kind == "soft":
            bg, hover, fg, off = c["soft_btn"], c["soft_hover"], c["dark"], c["off"]
        else:
            bg, hover, fg, off = c["card"], c["ghost_hover"], c["ink"], c["off"]
        if kind == "ghost":
            kw.setdefault("highlightthickness", 1)
            kw.setdefault("highlightbackground", c["soft"])
            kw.setdefault("highlightcolor", c["soft"])
        else:
            kw.setdefault("highlightthickness", 0)
        super().__init__(master, text=text, command=command, bd=0, relief="flat",
                         bg=bg, fg=fg, activebackground=hover,
                         activeforeground=fg, font=(FONT, 10, "bold"),
                         padx=16, pady=8, cursor="hand2", **kw)
        self._st = {"bg": bg, "hover": hover, "fg": fg, "off": off}

    def _hover(self, on: bool) -> None:
        if str(self["state"]) == "disabled":
            return
        self.configure(bg=self._st["hover"] if on else self._st["bg"])

    def enable(self, ok: bool) -> None:
        if ok:
            self.configure(state="normal", bg=self._st["bg"], fg=self._st["fg"], cursor="hand2")
        else:
            self.configure(state="disabled", bg=self._st["off"], fg=CUR["muted"], cursor="arrow")


class Chip(tk.Checkbutton):
    """药丸式开关，选中变成主题色底白字。"""

    def __init__(self, master, text: str, var: tk.BooleanVar, **kw):  # noqa: ANN001
        c = CUR
        super().__init__(master, text=text, variable=var, indicatoron=False, bd=0,
                         relief="flat", font=(FONT, 9), padx=10, pady=4, cursor="hand2",
                         bg=c["pale"], fg=c["ink"], activebackground=c["soft"],
                         selectcolor=c["pale"], highlightthickness=0, **kw)
        self.bind("<Button-1>", lambda _e: self.after(10, self._paint))
        self.after(50, self._paint)

    def _paint(self) -> None:
        c = CUR
        on = bool(self.getvar(str(self.cget("variable"))))
        self.configure(bg=c["main"] if on else c["pale"],
                       fg="#FFFFFF" if on else c["ink"],
                       selectcolor=c["main"] if on else c["pale"],
                       activebackground=c["deep"] if on else c["soft"],
                       activeforeground="#FFFFFF" if on else c["ink"])


class Card(tk.Frame):
    """白底 + 主题色标题条的小卡片。"""

    def __init__(self, master, title: str, **kw):  # noqa: ANN001
        c = CUR
        super().__init__(master, bg=c["card"], highlightthickness=2,
                         highlightbackground=c["soft"], **kw)
        head = tk.Frame(self, bg=c["main"])
        head.pack(fill="x")
        tk.Label(head, text=title, bg=c["main"], fg="#FFFFFF",
                 font=(FONT, 10, "bold")).pack(side="left", padx=12, pady=5)
        self.inner = tk.Frame(self, bg=c["card"])
        self.inner.pack(fill="both", expand=True, padx=12, pady=10)


class Header(tk.Canvas):
    """顶部横幅：主题渐变 + 吉祥物 + 状态胶囊 + 爱心动画。"""

    def __init__(self, master, **kw):  # noqa: ANN001
        super().__init__(master, height=118, highlightthickness=0, bg=CUR["pale"], **kw)
        self.app = master
        self.bind("<Configure>", lambda _e: self.redraw())
        self._state = "未开始"
        self._bow_dx = 0
        self.eye_open: list[int] = []
        self.eye_closed: list[int] = []
        self.after(2400, self._blink_loop)
        self.after(700, self._bow_loop)
        self.bind("<Button-1>", self._on_click)

    # -- 画 ---------------------------------------------------------------
    def redraw(self) -> None:
        try:
            self.delete("all")
            c = CUR
            w = max(self.winfo_width(), 400)
            h = int(self.cget("height"))
            for i in range(h):
                self.create_line(0, i, w, i, fill=mix(c["head1"], c["head2"], i / max(h - 1, 1)))

            # 装饰
            if c["mascot"] == "cinna":
                for dx, dy, rw, rh, col in ((0.60, 0.22, 26, 12, "#FFFFFF"),
                                            (0.72, 0.62, 20, 9, "#FFFFFF"),
                                            (0.86, 0.30, 16, 8, c["head3"]),
                                            (0.93, 0.68, 22, 10, "#FFFFFF")):
                    self.create_oval(w * dx - rw, h * dy - rh, w * dx + rw, h * dy + rh,
                                     fill=col, outline="")
                for dx, dy in ((0.66, 0.42), (0.79, 0.16), (0.88, 0.50)):
                    self._sparkle(w * dx, h * dy, 7, "#FFFFFF")
            elif c["mascot"] == "pompom":
                for dx, dy, r in ((0.62, 0.24, 4), (0.71, 0.60, 6), (0.83, 0.32, 4),
                                  (0.92, 0.66, 5), (0.55, 0.74, 3)):
                    self.create_oval(w * dx - r, h * dy - r, w * dx + r, h * dy + r,
                                     fill="#FFFFFF", outline="")
                for dx, dy in ((0.67, 0.45), (0.86, 0.55), (0.75, 0.18)):
                    self._sparkle(w * dx, h * dy, 6, c["main"])
            else:
                for dx, dy, r, col in ((0.62, 0.2, 3, "#FFFFFF"), (0.7, 0.62, 5, c["accent2"]),
                                       (0.82, 0.3, 4, "#FFFFFF"), (0.9, 0.7, 6, c["accent2"]),
                                       (0.53, 0.72, 4, "#FFFFFF")):
                    self.create_oval(w * dx - r, h * dy - r, w * dx + r, h * dy + r,
                                     fill=col, outline="")

            cx, cy = 92, h * 0.56
            painter = PAINTERS.get(c["mascot"], _draw_kitty)
            body, bow, eye_open, eye_closed = painter(self, cx, cy, 42, c)
            self._body_items = body
            self._bow_items = bow
            self.eye_open, self.eye_closed = eye_open, eye_closed

            # 云朵上的小影子
            self.create_oval(cx - 46, cy + 40, cx + 46, cy + 54, fill=mix(c["head2"], c["main"], 0.25),
                             outline="")

            self.create_text(176, 40, anchor="w", text="送礼自动截图",
                             font=(FONT, 21, "bold"), fill=c["title_fill"])
            self.create_text(177, 72, anchor="w", text=f"B站直播 · 直播姬版 · {c['tagline']}",
                             font=(FONT, 10), fill=c["sub_fill"])

            # 状态胶囊
            px1, py1, px2, py2 = w - 226, 24, w - 26, 60
            round_rect(self, px1, py1, px2, py2, 18, fill="#FFFFFF", outline=c["soft"], width=1)
            fg = {"监听中": c["green"], "已停止": c["muted"]}.get(self._state, c["muted"])
            self.create_oval(px1 + 16, py1 + 13, px1 + 26, py1 + 23, fill=fg, outline="")
            self.create_text(px1 + 36, (py1 + py2) / 2, anchor="w", text=self._state,
                             font=(FONT, 10, "bold"), fill=fg)
            self.create_text(w - 30, h - 18, anchor="e", text="♪ 比你更关心每一份礼物",
                             font=(FONT, 9), fill=c["sub_fill"])
        except tk.TclError:
            pass

    def _sparkle(self, x: float, y: float, r: float, col: str) -> None:
        self.create_line(x - r, y, x + r, y, fill=col, width=2, capstyle="round")
        self.create_line(x, y - r, x, y + r, fill=col, width=2, capstyle="round")

    # -- 动画 -------------------------------------------------------------
    def _blink_loop(self) -> None:
        try:
            if not self.eye_open:
                self.after(1200, self._blink_loop)
                return
            for item in self.eye_open:
                self.itemconfigure(item, state="hidden")
            for item in self.eye_closed:
                self.itemconfigure(item, state="normal")
            self.after(140, self._blink_end)
        except tk.TclError:
            return
        self.after(random.randint(2600, 5200), self._blink_loop)

    def _blink_end(self) -> None:
        try:
            for item in self.eye_open:
                self.itemconfigure(item, state="normal")
            for item in self.eye_closed:
                self.itemconfigure(item, state="hidden")
        except tk.TclError:
            pass

    def _bow_loop(self) -> None:
        self._bow_dx = -self._bow_dx if self._bow_dx else 2
        try:
            for item in getattr(self, "_bow_items", []):
                self.move(item, self._bow_dx, 0)
        except tk.TclError:
            return
        self.after(760, self._bow_loop)

    def bounce(self, times: int = 2) -> None:
        def step(n: int, up: bool) -> None:
            if n <= 0:
                return
            try:
                for item in getattr(self, "_body_items", []):
                    self.move(item, 0, -6 if up else 6)
            except tk.TclError:
                return
            self.after(70, lambda: step(n - 1, not up))
        step(times * 2, True)

    def hearts(self, n: int = 5) -> None:
        """吉祥物头顶飘爱心。"""
        cx, cy = 92, int(self.cget("height")) * 0.56
        for i in range(n):
            x = cx + random.randint(-26, 26)
            y = cy - 46
            size = random.randint(8, 14)
            item = self.create_text(x, y, text="♥", fill=CUR["deep"],
                                    font=(FONT, size), tags="heart")
            self.after(i * 70, lambda it=item: self._float(it))

    def _float(self, item: int, step: int = 0) -> None:
        if step > 18:
            try:
                self.delete(item)
            except tk.TclError:
                pass
            return
        try:
            self.move(item, random.choice((-1, 0, 1)), -3)
            self.itemconfigure(item, fill=mix(CUR["deep"], CUR["head1"], step / 18))
        except tk.TclError:
            return
        self.after(40, lambda: self._float(item, step + 1))

    def set_state(self, text: str) -> None:
        self._state = text
        self.redraw()

    def _on_click(self, event) -> None:  # noqa: ANN001
        if event.x > 176:
            return
        self.hearts(3)
        self.bounce(1)
        lines = {
            "kitty": ["喵～", "礼物呢？", "今天也超可爱！", "谢谢每一份心意 ♥"],
            "cinna": ["汪～", "云朵软软的", "今天也辛苦啦 ☁", "每一份礼物都记下了"],
            "pompom": ["汪！", "布丁味的好心情", "谢谢投喂 ✿", "今天也请多指教"],
        }[CUR["mascot"]]
        self.app.say(random.choice(lines))


# --------------------------------------------------------------------------- #
# 主界面
# --------------------------------------------------------------------------- #
class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.withdraw()
        self.cfg = core.load_config(BASE / "config.json")
        forced = os.environ.get("BILI_THEME", "")
        if forced in THEMES:          # 调试用：BILI_THEME=cinna 直接启动某套皮肤
            self.cfg["theme"] = forced
        self.theme_key = apply_theme(str(self.cfg.get("theme") or "kitty"))
        self.title(THEMES[self.theme_key]["title"])
        self.geometry("1120x950")
        self.minsize(1040, 800)
        self.configure(bg=CUR["bg"])
        ico = BASE / "app.ico"
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
            except tk.TclError:
                pass

        self.events: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self.monitor: Optional[Monitor] = None
        self.rows: list[dict[str, Any]] = []
        self.running = False
        self.shot_count = 0
        self._toast: Optional[tk.Label] = None
        self._log_lines: list[str] = []
        self._busy_theme = False

        self._setup_style()
        self._build()
        self._install_log_handler()
        self._load_cfg()
        self._load_history()
        self.refresh_windows()
        if self.cfg.get("auto_start"):
            self.after(1000, self.start)
        self.after(120, self._drain)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.deiconify()
        self.lift()
        # 根据内容算一个刚好够高的窗口，别让日志和状态栏被裁掉
        try:
            self.update_idletasks()
            w = max(1120, self.winfo_reqwidth())
            h = max(950, self.winfo_reqheight() + 8)
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            self.geometry(f"{min(w, sw - 40)}x{min(h, sh - 60)}+{max((sw - min(w, sw - 40)) // 2, 0)}+{max((sh - min(h, sh - 60)) // 2 - 20, 0)}")
        except tk.TclError:
            pass

    # -- 样式 -------------------------------------------------------------
    def _setup_style(self) -> None:
        c = CUR
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Pink.Treeview", background=c["card"], fieldbackground=c["card"],
                        foreground=c["ink"], rowheight=30, borderwidth=0, font=(FONT, 9))
        style.configure("Pink.Treeview.Heading", background=c["main"], foreground="#FFFFFF",
                        font=(FONT, 10, "bold"), relief="flat", borderwidth=0, padding=6)
        style.map("Pink.Treeview.Heading", background=[("active", c["deep"])])
        style.map("Pink.Treeview", background=[("selected", c["sel"])],
                  foreground=[("selected", c["sel_fg"])])
        style.configure("Pink.Vertical.TScrollbar", background=c["pale"], troughcolor=c["shade"],
                        bordercolor=c["shade"], arrowcolor=c["dark"], relief="flat")
        style.configure("Pink.TCombobox", fieldbackground=c["shade"], background=c["pale"],
                        foreground=c["ink"], arrowcolor=c["dark"], borderwidth=0, padding=4)
        style.map("Pink.TCombobox", fieldbackground=[("readonly", c["shade"])])

    # -- 布局 -------------------------------------------------------------
    def _build(self) -> None:
        c = CUR

        # ---- 主题条 ----
        strip = tk.Frame(self, bg=c["pale"], height=38)
        strip.pack(fill="x")
        tk.Label(strip, text="主题", bg=c["pale"], fg=c["dark"],
                 font=(FONT, 9, "bold")).pack(side="left", padx=(18, 10), pady=9)
        for key in THEMES:
            t = THEMES[key]
            active = key == self.theme_key
            btn = tk.Button(
                strip, text=("● " if active else "○ ") + t["label"],
                command=lambda k=key: self.set_theme(k),
                bd=0, relief="flat", cursor="hand2", font=(FONT, 9, "bold"),
                bg=c["main"] if active else c["card"],
                fg="#FFFFFF" if active else c["ink"],
                activebackground=c["deep"], activeforeground="#FFFFFF",
                padx=12, pady=4, highlightthickness=0)
            btn.pack(side="left", padx=(0, 8), pady=7)
        tk.Label(strip, text="点一下换肤 · 监听不中断", bg=c["pale"], fg=c["ink_light"],
                 font=(FONT, 9)).pack(side="right", padx=18)

        self.header = Header(self)
        self.header.pack(fill="x")

        body = tk.Frame(self, bg=c["bg"])
        body.pack(fill="both", expand=True, padx=16, pady=(10, 0))

        # ---- 设置卡 ----
        card = Card(body, "  1 · 直播设置  ")
        card.pack(fill="x")
        g = card.inner
        for col, weight in ((1, 0), (3, 0), (5, 1), (7, 0)):
            g.columnconfigure(col, weight=weight)

        self.room_var = tk.StringVar()
        self.price_var = tk.StringVar()
        self.delay_var = tk.StringVar()
        self.win_var = tk.StringVar()
        self.sc_var = tk.BooleanVar(value=True)
        self.guard_var = tk.BooleanVar(value=True)
        self.silver_var = tk.BooleanVar(value=False)
        self.auto_var = tk.BooleanVar(value=False)

        tk.Label(g, text="直播间号", bg=c["card"], fg=c["ink_light"], font=(FONT, 9)).grid(
            row=0, column=0, sticky="w", padx=(2, 6))
        field(g, self.room_var, 14).grid(row=0, column=1, sticky="w", pady=4)
        tk.Label(g, text="礼物门槛", bg=c["card"], fg=c["ink_light"], font=(FONT, 9)).grid(
            row=0, column=2, sticky="e", padx=(18, 6))
        pf = tk.Frame(g, bg=c["shade"], highlightthickness=2, highlightbackground=c["pale"])
        pf.grid(row=0, column=3, sticky="w", pady=4)
        tk.Spinbox(pf, from_=0, to=99999, increment=1, width=5, textvariable=self.price_var,
                   bd=0, relief="flat", bg=c["shade"], fg=c["ink"], font=(FONT, 11),
                   buttonbackground=c["pale"], highlightthickness=0).pack(padx=8, pady=3)
        tk.Label(g, text="元 以上（0 = 全都截）", bg=c["card"], fg=c["ink_light"],
                 font=(FONT, 9)).grid(row=0, column=4, sticky="w", padx=(6, 0))

        tk.Label(g, text="截图窗口", bg=c["card"], fg=c["ink_light"], font=(FONT, 9)).grid(
            row=1, column=0, sticky="w", padx=(2, 6), pady=(8, 0))
        self.win_combo = ttk.Combobox(g, textvariable=self.win_var, style="Pink.TCombobox",
                                      font=(FONT, 9), width=46)
        self.win_combo.grid(row=1, column=1, columnspan=5, sticky="we", pady=(8, 0))
        CuteButton(g, "刷新窗口", self.refresh_windows, kind="soft").grid(
            row=1, column=6, columnspan=2, sticky="w", padx=(8, 0), pady=(8, 0))

        opts = tk.Frame(g, bg=c["card"])
        opts.grid(row=2, column=0, columnspan=8, sticky="w", pady=(12, 2))
        Chip(opts, "醒目留言 SC", self.sc_var).pack(side="left", padx=(0, 8))
        Chip(opts, "上舰", self.guard_var).pack(side="left", padx=(0, 8))
        Chip(opts, "银瓜子礼物", self.silver_var).pack(side="left", padx=(0, 18))
        tk.Label(opts, text="延迟", bg=c["card"], fg=c["ink_light"], font=(FONT, 9)).pack(side="left")
        df = tk.Frame(opts, bg=c["shade"], highlightthickness=2, highlightbackground=c["pale"])
        df.pack(side="left", padx=(6, 4))
        tk.Spinbox(df, from_=0.2, to=10, increment=0.1, width=4, textvariable=self.delay_var,
                   bd=0, relief="flat", bg=c["shade"], fg=c["ink"], font=(FONT, 10),
                   buttonbackground=c["pale"], highlightthickness=0).pack(padx=6, pady=2)
        tk.Label(opts, text="秒", bg=c["card"], fg=c["ink_light"], font=(FONT, 9)).pack(side="left")
        Chip(opts, "启动后自动开始", self.auto_var).pack(side="left", padx=(16, 0))

        # ---- 按钮条 ----
        bar = tk.Frame(body, bg=c["bg"])
        bar.pack(fill="x", pady=(12, 0))
        self.btn_start = CuteButton(bar, "▶  开始监听", self.start, kind="primary")
        self.btn_start.pack(side="left")
        self.btn_stop = CuteButton(bar, "■  停止", self.stop, kind="soft")
        self.btn_stop.pack(side="left", padx=(8, 0))
        self.btn_stop.enable(False)
        CuteButton(bar, "测试截图", self.test_shot, kind="ghost").pack(side="left", padx=(8, 0))
        CuteButton(bar, "截图文件夹", lambda: self.open_dir(self.out_dir()), kind="ghost").pack(
            side="left", padx=(8, 0))
        CuteButton(bar, "记录表", self.open_csv, kind="ghost").pack(side="left", padx=(8, 0))
        CuteButton(bar, "所在文件夹", self.reveal_selected, kind="ghost").pack(side="left", padx=(8, 0))

        # ---- 记录卡 ----
        table_card = Card(body, "  2 · 截图记录（双击打开图片，右键更多）  ")
        table_card.pack(fill="both", expand=True, pady=(12, 0))
        tb = table_card.inner
        tb.rowconfigure(0, weight=1)
        tb.columnconfigure(0, weight=1)

        cols = ("time", "type", "uname", "gift", "amount", "file")
        heads = {"time": "时间", "type": "类型", "uname": "昵称", "gift": "礼物",
                 "amount": "金额", "file": "文件"}
        widths = {"time": 150, "type": 76, "uname": 130, "gift": 150, "amount": 80, "file": 470}
        self.tree = ttk.Treeview(tb, columns=cols, show="headings", height=7,
                                 style="Pink.Treeview")
        for col in cols:
            self.tree.heading(col, text=heads[col])
            self.tree.column(col, width=widths[col], anchor="w", stretch=(col == "file"))
        self.tree.tag_configure("odd", background=c["odd"])
        self.tree.tag_configure("guard", foreground=c["guard"])
        self.tree.tag_configure("sc", foreground=c["sc"])
        self.tree.tag_configure("failed", foreground=c["red"])
        self.tree.tag_configure("fresh", background=c["pale"])
        vsb = ttk.Scrollbar(tb, orient="vertical", command=self.tree.yview,
                            style="Pink.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-1>", lambda _e: self.open_selected())
        self.tree.bind("<Button-3>", self._popup_menu)

        self.menu = tk.Menu(self, tearoff=0, bg=c["card"], fg=c["ink"],
                            activebackground=c["pale"], activeforeground=c["ink"],
                            font=(FONT, 9), bd=0)
        self.menu.add_command(label="打开图片", command=self.open_selected)
        self.menu.add_command(label="打开所在文件夹", command=self.reveal_selected)
        self.menu.add_command(label="复制文件路径", command=self.copy_selected)

        # ---- 日志卡 ----
        log_card = Card(body, "  3 · 运行日志  ")
        log_card.pack(fill="x", pady=(12, 0))
        lb = log_card.inner
        lb.columnconfigure(0, weight=1)
        self.log_text = tk.Text(lb, height=5, wrap="none", font=("Consolas", 9),
                                bg=c["log_bg"], fg=c["log_fg"], relief="flat",
                                insertbackground=c["deep"], padx=8, pady=6)
        log_vsb = ttk.Scrollbar(lb, orient="vertical", command=self.log_text.yview,
                                style="Pink.Vertical.TScrollbar")
        self.log_text.configure(yscrollcommand=log_vsb.set, state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_vsb.grid(row=0, column=1, sticky="ns")

        # ---- 状态条 ----
        status = tk.Frame(self, bg=c["bg"])
        status.pack(fill="x", padx=18, pady=(8, 8))
        self.count_var = tk.StringVar(value="已记录 0 条")
        self.state_var = tk.StringVar(value="未开始")
        tk.Label(status, textvariable=self.count_var, bg=c["bg"], fg=c["ink_light"],
                 font=(FONT, 9)).pack(side="left")
        tk.Label(status, textvariable=self.state_var, bg=c["bg"], fg=c["dark"],
                 font=(FONT, 10, "bold")).pack(side="right")

        for line in self._log_lines[-300:]:
            self._append_log(line)

    # -- 换肤 -------------------------------------------------------------
    def set_theme(self, key: str) -> None:
        if key not in THEMES or key == self.theme_key or self._busy_theme:
            return
        self._busy_theme = True
        try:
            cfg = self._collect_cfg() if hasattr(self, "room_var") else dict(self.cfg)
            cfg["theme"] = key
            running = self.running
            rows = [dict(r) for r in self.rows]
            logs = list(self._log_lines)
            shots = self.shot_count

            self.theme_key = apply_theme(key)
            self.cfg = cfg
            self.title(THEMES[key]["title"])
            self.configure(bg=CUR["bg"])
            for child in self.winfo_children():
                child.destroy()
            self._toast = None
            self.rows = []
            self.shot_count = 0
            self._log_lines = []
            self._setup_style()
            self._build()
            self._load_cfg()
            self._log_lines = logs[-300:]
            for row in reversed(rows):
                self._add_row(row)
            self.shot_count = shots
            self.count_var.set(f"已记录 {len(self.rows)} 条 · 截图 {self.shot_count} 张")
            if running:
                self._set_running(True)
                self.state_var.set("监听中")
                self.header.set_state("监听中")
            else:
                self.state_var.set("未开始")
            self._save_cfg(cfg)
            self.update_idletasks()
            self.header.hearts(4)
            self.header.bounce(1)
            self.say(f"换成{THEMES[key]['full']}啦")
            self.log(f"主题已切换：{THEMES[key]['full']}")
        finally:
            self._busy_theme = False

    def say(self, text: str, ms: int = 2200) -> None:
        """吉祥物说话气泡。"""
        if self._toast is not None:
            try:
                self._toast.destroy()
            except tk.TclError:
                pass
        c = CUR
        self._toast = tk.Label(self, text=f" {text} ", bg="#FFFFFF", fg=c["dark"],
                               font=(FONT, 10, "bold"), bd=0, padx=12, pady=6,
                               highlightthickness=2, highlightbackground=c["soft"])
        self._toast.place(x=176, y=self.header.winfo_y() + int(self.header.cget("height")) - 34)
        self.after(ms, self._hide_toast)

    def _hide_toast(self) -> None:
        if self._toast is not None:
            try:
                self._toast.destroy()
            except tk.TclError:
                pass
            self._toast = None

    # -- 配置 -------------------------------------------------------------
    def _load_cfg(self) -> None:
        c = self.cfg
        self.room_var.set(str(c.get("room_id") or ""))
        self.price_var.set(f"{float(c.get('min_price_gift', 10)):g}")
        self.delay_var.set(f"{float(c.get('delay_seconds', 1.0)):g}")
        self.sc_var.set(bool(c.get("capture_sc", True)))
        self.guard_var.set(bool(c.get("capture_guard", True)))
        self.silver_var.set(bool(c.get("include_silver_gift", False)))
        self.auto_var.set(bool(c.get("auto_start", False)))
        title = str(c.get("window_title") or "")
        self.win_var.set(title if title else AUTO_WINDOW)

    def _collect_cfg(self) -> dict[str, Any]:
        cfg = dict(self.cfg)
        cfg["room_id"] = int(str(self.room_var.get()).strip() or 0)
        try:
            cfg["min_price_gift"] = float(str(self.price_var.get()).strip() or 0)
        except ValueError:
            cfg["min_price_gift"] = 0.0
        try:
            cfg["delay_seconds"] = max(0.0, float(str(self.delay_var.get()).strip() or 1))
        except ValueError:
            cfg["delay_seconds"] = 1.0
        win = self.win_var.get().strip()
        cfg["window_title"] = "直播姬|直播间" if win == AUTO_WINDOW else win
        cfg["capture_sc"] = self.sc_var.get()
        cfg["capture_guard"] = self.guard_var.get()
        cfg["include_silver_gift"] = self.silver_var.get()
        cfg["auto_start"] = self.auto_var.get()
        cfg["theme"] = self.theme_key
        return cfg

    def _save_cfg(self, cfg: dict[str, Any]) -> None:
        self.cfg = dict(cfg)
        try:
            (BASE / "config.json").write_text(
                json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            self.log(f"保存配置失败：{exc}")

    def out_dir(self) -> Path:
        return (BASE / str(self.cfg.get("out_dir", "shots"))).resolve()

    def _find_target(self, keyword: str) -> Optional[dict[str, Any]]:
        win = core.find_window(keyword, 0)
        if win:
            return win
        parts = [p.strip() for p in keyword.split(" - ") if p.strip()]
        for i in range(len(parts) - 1, 0, -1):
            win = core.find_window(" - ".join(parts[:i]), 0)
            if win:
                return win
        return None

    def refresh_windows(self) -> None:
        titles = sorted(core.list_windows(), key=lambda w: w["title"])
        values = [AUTO_WINDOW] + [w["title"] for w in titles if w["title"]]
        self.win_combo.configure(values=values)
        if self.win_var.get() not in values:
            self.win_var.set(AUTO_WINDOW)
        target = self._find_target(self._collect_cfg()["window_title"])
        if target:
            self.log(f"当前窗口：{target['title']}（{target['rect'][2]}x{target['rect'][3]}）")
        else:
            self.log("没有找到直播姬窗口，等开播后再点「刷新窗口」")

    # -- 日志 -------------------------------------------------------------
    def _install_log_handler(self) -> None:
        handler = QueueLogHandler(self.events)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        for h in list(root.handlers):
            root.removeHandler(h)
        root.addHandler(handler)

    def _append_log(self, line: str) -> None:
        try:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", line + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        except tk.TclError:
            pass

    def log(self, text: str) -> None:
        line = f"{datetime.now():%H:%M:%S}  {text}"
        self._log_lines.append(line)
        if len(self._log_lines) > 300:
            self._log_lines = self._log_lines[-300:]
        self._append_log(line)

    # -- 事件循环 ---------------------------------------------------------
    def _drain(self) -> None:
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev.get("kind")
                if kind == "log":
                    self.log(ev["text"])
                elif kind == "row":
                    self._add_row(ev["row"], celebrate=True)
                elif kind == "state":
                    self.state_var.set(ev["text"])
                    self.header.set_state(ev["text"])
                    if ev["text"] == "已停止":
                        self._set_running(False)
                elif kind == "error":
                    self.log(ev["text"])
                    self.say("呜… 监听出错了", 4000)
                    self._set_running(False)
                elif kind == "testshot":
                    if ev.get("ok"):
                        self.log(f"测试截图已保存：{ev.get('path')}")
                        self.say("截图成功～", 2600)
                        self.open_path(Path(ev["path"]))
                    else:
                        self.log("测试截图失败，看看窗口是不是最小化了")
                        self.say("呜… 没截到", 3000)
        except queue.Empty:
            pass
        self.after(120, self._drain)

    def _add_row(self, row: dict[str, Any], celebrate: bool = False) -> None:
        self.rows.append(row)
        tags = []
        if row.get("type") == "上舰":
            tags.append("guard")
        elif row.get("type") == "SC":
            tags.append("sc")
        if not row.get("image"):
            tags.append("failed")
        if celebrate:
            tags.append("fresh")
        elif len(self.rows) % 2 == 0:
            tags.insert(0, "odd")
        iid = self.tree.insert("", 0, values=(
            row.get("time", "")[11:],
            row.get("type", ""),
            row.get("uname", ""),
            f"{row.get('gift', '')} x{row.get('num', 1)}" if row.get("num", 1) > 1 else row.get("gift", ""),
            f"{float(row.get('amount') or 0):.2f}",
            Path(row["image"]).name if row.get("image") else "（没截到）",
        ), tags=tuple(tags))
        if row.get("image"):
            self.shot_count += 1
        self.count_var.set(f"已记录 {len(self.rows)} 条 · 截图 {self.shot_count} 张")
        if celebrate:
            self.header.bounce(2)
            self.header.hearts(4)
            self.say(f"抓到 {row.get('uname', '')} 送的 {row.get('gift', '')}")
            self.after(2600, lambda: self.tree.item(iid, tags=tuple(t for t in tags if t != "fresh")))

    def _load_history(self) -> None:
        path = (BASE / str(self.cfg.get("log_csv", "shots/gifts.csv"))).resolve()
        if not path.exists():
            return
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()[1:]
        except OSError:
            return
        loaded = 0
        for line in reversed(lines[-200:]):
            cols = next(csv.reader([line]), [])
            if len(cols) < 8:
                continue
            try:
                row = {
                    "time": cols[0], "type": cols[1], "uid": cols[2], "uname": cols[3],
                    "gift": cols[4], "num": int(cols[5] or 1), "amount": float(cols[6] or 0),
                    "image": cols[7].strip(), "detail": cols[8] if len(cols) > 8 else "",
                }
            except ValueError:
                continue
            self._add_row(row)
            loaded += 1
        if loaded:
            self.log(f"读到了 {loaded} 条历史记录")

    # -- 操作 -------------------------------------------------------------
    def _set_running(self, on: bool) -> None:
        self.running = on
        self.btn_start.enable(not on)
        self.btn_stop.enable(on)

    def start(self) -> None:
        if self.running:
            return
        cfg = self._collect_cfg()
        if not str(cfg.get("room_id") or "").isdigit() or int(cfg["room_id"]) <= 0:
            messagebox.showwarning("还差一步", "先填一下直播间号（地址栏 live.bilibili.com/ 后面那串数字）",
                                   parent=self)
            return
        if not cfg["window_title"]:
            messagebox.showwarning("还差一步", "先选一个要截图的窗口", parent=self)
            return
        target = self._find_target(cfg["window_title"])
        if not target:
            self.log(f"找不到标题含「{cfg['window_title']}」的窗口")
            messagebox.showwarning("没找到窗口",
                                   "现在没有匹配的窗口。\n先把直播姬的「直播间」页面打开，再点「刷新窗口」。",
                                   parent=self)
            return
        if target.get("minimized"):
            self.log("⚠ 目标窗口是最小化的，截出来会是黑的，建议先还原")
            self.say("窗口最小化啦，先还原一下～", 3500)
        self._save_cfg(cfg)
        self.monitor = Monitor(cfg, self.events.put)
        self.monitor.start()
        self._set_running(True)
        self.state_var.set("监听中")
        self.header.set_state("监听中")
        self.header.bounce(2)
        self.say("开始盯礼物啦", 2600)

    def stop(self) -> None:
        if self.monitor:
            self.monitor.stop()
            self.monitor = None
        self._set_running(False)
        self.state_var.set("已停止")
        self.header.set_state("已停止")
        self.log("已停止监听")

    def test_shot(self) -> None:
        cfg = self._collect_cfg()
        win = self._find_target(cfg["window_title"]) if cfg["window_title"] else None
        if not win:
            messagebox.showwarning("没找到窗口", "没有匹配的窗口，先打开直播姬并点「刷新窗口」", parent=self)
            return
        out = self.out_dir() / f"_test_{datetime.now():%H%M%S}.png"
        self.log(f"正在截「{win['title']}」…")
        job = cfg

        def work() -> None:
            worker = core.ShotWorker(job)
            worker.start()
            done = threading.Event()
            result: dict[str, Any] = {}
            worker.q.put({"hwnd": win["hwnd"], "path": out,
                          "cb": lambda ok, p: (result.update(ok=ok, path=p), done.set())})
            done.wait(10)
            worker.stop()
            self.events.put({"kind": "testshot", "ok": bool(result.get("ok")),
                             "path": str(result.get("path") or out)})

        threading.Thread(target=work, daemon=True).start()

    def _selected_image(self) -> Optional[Path]:
        sel = self.tree.selection()
        if not sel:
            return None
        vals = self.tree.item(sel[0], "values")
        if len(vals) < 6 or str(vals[5]).startswith("（"):
            return None
        name = str(vals[5])
        for row in self.rows:
            if row.get("image") and Path(row["image"]).name == name:
                return Path(row["image"])
        return self.out_dir() / name

    def open_selected(self) -> None:
        path = self._selected_image()
        if path:
            self.open_path(path)

    def reveal_selected(self) -> None:
        path = self._selected_image()
        self.open_dir(path.parent if path else self.out_dir())

    def copy_selected(self) -> None:
        path = self._selected_image()
        if path:
            self.clipboard_clear()
            self.clipboard_append(str(path))
            self.log("已复制路径")

    def _popup_menu(self, event) -> None:  # noqa: ANN001
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
            self.menu.tk_popup(event.x_root, event.y_root)

    def open_path(self, path: Path) -> None:
        try:
            os.startfile(str(path))  # noqa: S606
        except Exception as exc:  # noqa: BLE001
            self.log(f"打不开文件：{exc}")

    def open_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(path))  # noqa: S606
        except Exception as exc:  # noqa: BLE001
            self.log(f"打不开文件夹：{exc}")

    def open_csv(self) -> None:
        p = (BASE / str(self.cfg.get("log_csv", "shots/gifts.csv"))).resolve()
        if p.exists():
            self.open_path(p)
        else:
            messagebox.showinfo("还没有记录", "还没截到礼物，记录表还没生成。", parent=self)

    def _on_close(self) -> None:
        try:
            if self.monitor:
                self.monitor.stop()
        finally:
            self.destroy()


def field(master, var: tk.StringVar, width: int) -> tk.Frame:  # noqa: ANN001
    c = CUR
    wrap = tk.Frame(master, bg=c["shade"], highlightthickness=2, highlightbackground=c["pale"])
    entry = tk.Entry(wrap, textvariable=var, width=width, bd=0, relief="flat",
                     bg=c["shade"], fg=c["ink"], insertbackground=c["deep"],
                     font=(FONT, 11), highlightthickness=0)
    entry.pack(padx=8, pady=4)
    entry.bind("<FocusIn>", lambda _e: wrap.configure(highlightbackground=c["main"]))
    entry.bind("<FocusOut>", lambda _e: wrap.configure(highlightbackground=c["pale"]))
    return wrap


def self_test() -> int:
    """打包后的自检：不开界面，直接试一次窗口截图，结果写到 _selftest.json。"""
    cfg = core.load_config(BASE / "config.json")
    out_dir = (BASE / str(cfg.get("out_dir", "shots"))).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    info: dict[str, Any] = {
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": sys.version,
        "window_title": cfg.get("window_title"),
        "theme": cfg.get("theme"),
        "window": None,
        "ok": False,
        "path": "",
        "error": "",
    }
    try:
        win = core.find_window(str(cfg.get("window_title") or ""), 0)
        info["window"] = win
        if win:
            cfg["window_hwnd"] = int(win["hwnd"])
            worker = core.ShotWorker(cfg)
            worker.start()
            target = out_dir / "_selftest.png"
            done = threading.Event()

            def cb(ok: bool, path: Any) -> None:
                info["ok"] = bool(ok)
                info["path"] = str(path)
                done.set()

            worker.q.put({"hwnd": int(win["hwnd"]), "path": target, "cb": cb})
            done.wait(15)
            worker.stop()
        else:
            info["error"] = "找不到窗口"
    except Exception:  # noqa: BLE001
        info["error"] = traceback.format_exc()
    (BASE / "_selftest.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return 0 if info["ok"] else 1


def main() -> int:
    core.enable_dpi_awareness()
    core.setup_console()
    if os.environ.get("BILI_SELFTEST"):
        return self_test()
    app = App()
    try:
        app.tk.call("tk", "scaling", app.winfo_fpixels("1i") / 72.0)
    except Exception:  # noqa: BLE001
        pass
    app.mainloop()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001
        err = traceback.format_exc()
        try:
            (BASE / "gui_error.log").write_text(err, encoding="utf-8")
        except OSError:
            pass
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("启动失败", err[-1200:])
        except Exception:  # noqa: BLE001
            pass
        raise
