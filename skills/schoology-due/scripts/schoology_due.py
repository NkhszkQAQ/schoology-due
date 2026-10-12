#!/usr/bin/env python3
"""Read a private Schoology iCal feed and print due assignments safely."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.request
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_CONFIG = Path.home() / ".config" / "schoology-due"
ASSIGNMENT_RE = re.compile(r"/assignment/(\d+)")


def unfold_ical(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def unescape_ical(value: str) -> str:
    return (
        value.replace("\\N", "\n")
        .replace("\\n", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def parse_ical(text: str) -> list[dict[str, str]]:
    if not text.strip().startswith("BEGIN:VCALENDAR") or "END:VCALENDAR" not in text:
        raise RuntimeError("订阅响应不是有效的 iCal 日历；请检查网络和订阅设置")
    events: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in unfold_ical(text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        left, value = line.split(":", 1)
        key = left.split(";", 1)[0].upper()
        current[key] = unescape_ical(value)
        current[f"_{key}_PARAMS"] = left
    return events


def parse_start(event: dict[str, str], local_tz: ZoneInfo) -> datetime:
    raw = event.get("DTSTART", "")
    params = event.get("_DTSTART_PARAMS", "")
    if "VALUE=DATE" in params and "DATE-TIME" not in params:
        return datetime.combine(datetime.strptime(raw, "%Y%m%d").date(), time.min, tzinfo=local_tz)
    if raw.endswith("Z"):
        parsed = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return parsed.astimezone(local_tz)
    parsed = datetime.strptime(raw, "%Y%m%dT%H%M%S")
    tz_match = re.search(r'(?:^|;)TZID=("[^"]+"|[^;]+)', params)
    source_tz = ZoneInfo(tz_match.group(1).strip('"')) if tz_match else local_tz
    return parsed.replace(tzinfo=source_tz).astimezone(local_tz)


def read_private_text(path: Path) -> str:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise RuntimeError(f"私密配置权限过宽（{mode:o}）；请改为 600")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError("私密订阅配置为空")
    return value


def fetch_feed(config_dir: Path) -> str:
    url = read_private_text(config_dir / "ical_url")
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://") :]
    if not url.startswith("https://"):
        raise RuntimeError("订阅地址不是受支持的 HTTPS/webcal 地址")
    request = urllib.request.Request(url, headers={"User-Agent": "schoology-due/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return response.read().decode("utf-8-sig")
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"读取 Schoology 日历失败：{type(exc).__name__}") from None


def load_course_map(config_dir: Path) -> dict[str, dict[str, str]]:
    path = config_dir / "course_map.json"
    if not path.exists():
        return {"assignments": {}, "summaries": {}}
    data = json.loads(read_private_text(path))
    if not isinstance(data, dict):
        raise RuntimeError("课程映射必须是 JSON 对象")
    mapping = {key: data.get(key, {}) for key in ("assignments", "summaries")}
    for values in mapping.values():
        if not isinstance(values, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in values.items()
        ):
            raise RuntimeError("课程映射必须包含字符串键值对")
    return mapping


def course_for(event: dict[str, str], mapping: dict[str, dict[str, str]]) -> str:
    url = event.get("URL", "") or event.get("DESCRIPTION", "")
    match = ASSIGNMENT_RE.search(url)
    if match and match.group(1) in mapping["assignments"]:
        return mapping["assignments"][match.group(1)]
    return mapping["summaries"].get(event.get("SUMMARY", ""), "课程未标注")


def select_window(args: argparse.Namespace, now: datetime) -> tuple[datetime, datetime, str]:
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) if args.today else now
    if args.today:
        return start, start + timedelta(days=1), "今天"
    if args.week:
        end = (now + timedelta(days=8 - now.isoweekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return start, end, "本周剩余时间"
    return start, start + timedelta(days=args.days), f"未来 {args.days} 天"


def main() -> int:
    parser = argparse.ArgumentParser(description="读取 Schoology iCal 截止事项")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--today", action="store_true", help="今天")
    group.add_argument("--week", action="store_true", help="从现在到本周日")
    group.add_argument("--days", type=int, metavar="N", help="从现在起 N 天")
    parser.add_argument("--timezone", default="Asia/Shanghai", help="输出时区")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()
    if args.days is not None and args.days < 1:
        parser.error("--days 必须大于 0")

    config_dir = Path(os.environ.get("SCHOOLOGY_DUE_CONFIG", DEFAULT_CONFIG))
    try:
        local_tz = ZoneInfo(args.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        parser.error("--timezone 必须是可用的 IANA 时区，例如 Asia/Shanghai")
    now = datetime.now(local_tz)
    start, end, label = select_window(args, now)

    try:
        events = parse_ical(fetch_feed(config_dir))
        mapping = load_course_map(config_dir)
        due = []
        for event in events:
            url = event.get("URL", "") or event.get("DESCRIPTION", "")
            if not ASSIGNMENT_RE.search(url) or "DTSTART" not in event:
                continue
            deadline = parse_start(event, local_tz)
            if start <= deadline < end:
                due.append(
                    {
                        "course": course_for(event, mapping),
                        "assignment": event.get("SUMMARY", "未命名作业"),
                        "deadline": deadline,
                    }
                )
        due.sort(key=lambda item: item["deadline"])
    except json.JSONDecodeError:
        print("错误：课程映射不是有效的 JSON", file=sys.stderr)
        return 1
    except (ValueError, ZoneInfoNotFoundError):
        print("错误：日历日期或时区不受支持", file=sys.stderr)
        return 1
    except (OSError, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "period": label,
                    "timezone": args.timezone,
                    "items": [
                        {**item, "deadline": item["deadline"].isoformat()} for item in due
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(f"{label}（{args.timezone}）")
    if not due:
        print("没有 Schoology due 项目。")
        return 0
    for item in due:
        deadline = item["deadline"].strftime("%m月%d日 %H:%M %z")
        print(f"- {item['course']}｜{item['assignment']}｜{deadline}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
