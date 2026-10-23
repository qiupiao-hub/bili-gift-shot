# -*- coding: utf-8 -*-
"""
按礼物 CSV 的时间点，从直播姬的录制文件里抽帧（事后补高清图）。

思路：直播姬的录制文件从开播开始录，礼物 CSV 里记的是送礼时刻的墙上时间。
用「录制文件第 0 秒对应的墙上时间」把两者对齐，再用 ffmpeg 抽帧。

用法：
    # 录制文件创建时间就是开播时间（最常见）
    python extract_frames.py --csv shots/gifts.csv --video "D:\\Videos\\直播录制.mp4"

    # 时间对不上：手动指定录制起点，或加偏移
    python extract_frames.py --csv shots/gifts.csv --video xxx.mp4 --rec-start "2026-10-23 23:00:00"
    python extract_frames.py --csv shots/gifts.csv --video xxx.mp4 --rec-start "2026-10-23 23:00:00" --offset 2.5

    # 先看看每一行会落在视频的第几秒
    python extract_frames.py --csv shots/gifts.csv --video xxx.mp4 --dry-run
"""
from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def find_tool(name: str) -> str:
    p = shutil.which(name)
    if p:
        return p
    raise SystemExit(f"找不到 {name}，请安装 ffmpeg 并加入 PATH，或用 --ffmpeg 指定")


def video_duration(ffprobe: str, video: Path) -> float:
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def read_rows(csv_path: Path) -> list[dict[str, str]]:
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def parse_dt(s: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    raise SystemExit(f"看不懂时间：{s!r}，请用 2026-10-23 23:00:00 这种格式")


def main() -> int:
    ap = argparse.ArgumentParser(description="按礼物时间点从录制文件抽帧")
    ap.add_argument("--csv", required=True, help="gift_shot.py 生成的 gifts.csv")
    ap.add_argument("--video", required=True, help="直播姬的录制文件")
    ap.add_argument("--rec-start", default="", help="录制文件第0秒对应的墙上时间，默认用文件创建时间")
    ap.add_argument("--offset", type=float, default=0.0, help="整体时间偏移秒数，正数=往后挪")
    ap.add_argument("--pad", type=float, default=2.0, help="在礼物时间点前后各抽几秒（默认2秒）")
    ap.add_argument("--step", type=float, default=1.0, help="抽帧间隔秒数（默认1秒）")
    ap.add_argument("--out", default="", help="输出目录，默认 shots/frames_<视频名>")
    ap.add_argument("--type", default="", help="只处理某类事件，例如 礼物 / 上舰 / 醒目留言")
    ap.add_argument("--min-amount", type=float, default=0.0, help="只处理金额不低于该值的行")
    ap.add_argument("--ffmpeg", default="", help="ffmpeg 路径")
    ap.add_argument("--dry-run", action="store_true", help="只打印时间，不抽帧")
    args = ap.parse_args()

    csv_path = Path(args.csv).expanduser().resolve()
    video = Path(args.video).expanduser().resolve()
    if not csv_path.exists():
        raise SystemExit(f"CSV 不存在：{csv_path}")
    if not video.exists():
        raise SystemExit(f"视频不存在：{video}")

    ffmpeg = args.ffmpeg or find_tool("ffmpeg")
    ffprobe = str(Path(ffmpeg).with_name("ffprobe.exe")) if Path(ffmpeg).with_name("ffprobe.exe").exists() else find_tool("ffprobe")

    if args.rec_start:
        base = parse_dt(args.rec_start)
        base_src = "手动指定"
    else:
        base = datetime.fromtimestamp(video.stat().st_ctime)
        base_src = "文件创建时间"
    print(f"录制起点：{base:%Y-%m-%d %H:%M:%S}（{base_src}），视频：{video.name}")

    duration = video_duration(ffprobe, video)
    if duration:
        print(f"视频时长：{duration:.1f} 秒")

    rows = read_rows(csv_path)
    out_dir = Path(args.out).resolve() if args.out else csv_path.parent / f"frames_{video.stem}"
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[dict[str, str], float]] = []
    for row in rows:
        if args.type and args.type not in (row.get("类型") or ""):
            continue
        try:
            amount = float(row.get("金额元") or 0)
        except ValueError:
            amount = 0.0
        if amount < args.min_amount:
            continue
        ts_raw = (row.get("时间") or "").strip()
        if not ts_raw:
            continue
        t = (parse_dt(ts_raw) - base).total_seconds() + args.offset
        if duration and (t < 0 or t > duration):
            print(f"  跳过 {ts_raw}（t={t:.1f}s 超出视频范围，检查 --rec-start/--offset）")
            continue
        if t < 0:
            print(f"  跳过 {ts_raw}（t={t:.1f}s < 0，检查 --rec-start/--offset）")
            continue
        jobs.append((row, t))

    if not jobs:
        print("没有可抽帧的礼物记录")
        return 1

    print(f"共 {len(jobs)} 条记录，输出到 {out_dir}")
    index_rows = [["时间", "类型", "昵称", "礼物", "金额元", "视频秒数", "图片"]]
    ok = 0
    for i, (row, t) in enumerate(jobs, 1):
        label = f"{i:03d}_{t:08.2f}s_{row.get('昵称','')}_{row.get('礼物','')}"
        label = "".join(ch for ch in label if ch not in '\\/:*?"<>|').strip()
        frames = []
        pad, step = max(0.0, args.pad), max(0.2, args.step)
        offsets = []
        x = -pad
        while x <= pad + 1e-6:
            offsets.append(round(x, 3))
            x += step
        for off in offsets:
            tt = max(0.0, t + off)
            out = out_dir / f"{label}_{off:+.1f}s.png"
            if args.dry_run:
                print(f"  {row.get('时间')}  t={tt:8.2f}s  {out.name}")
                continue
            cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                   "-ss", f"{tt:.3f}", "-i", str(video),
                   "-frames:v", "1", str(out)]
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode == 0 and out.exists():
                frames.append(out)
                ok += 1
            else:
                err = (r.stderr or "").strip().splitlines()
                print(f"  抽帧失败 t={tt:.2f}s: {err[-1] if err else r.returncode}")
        if frames and not args.dry_run:
            index_rows.append([row.get("时间", ""), row.get("类型", ""), row.get("昵称", ""),
                               row.get("礼物", ""), row.get("金额元", ""), f"{t:.2f}",
                               frames[len(frames) // 2].name])

    if not args.dry_run and len(index_rows) > 1:
        with open(out_dir / "_map.csv", "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(index_rows)
        print(f"完成：{ok} 张，索引 {out_dir / '_map.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
