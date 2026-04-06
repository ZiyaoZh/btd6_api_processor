from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from api_raw_fetcher import ApiClient
from btd6_core.collection_event_service import refresh_collection_event_cache
from btd6_core.update_service import update_all_data


def run_refresh_service(
    client: ApiClient,
    trans: dict[str, dict[str, str]],
    interval_seconds: int = 600,
    log_path: Path | None = None,
) -> None:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds 必须大于 0")

    start_text = f"# 刷新服务已启动\n刷新间隔: {interval_seconds} 秒\n"
    print(start_text, flush=True)
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(start_text + "\n")

    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"[{now}] 开始刷新"]
        try:
            result = update_all_data(client, trans)
            lines.append(result)
            lines.append(f"[{now}] 刷新完成")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"[{now}] 刷新失败: {exc}")

        try:
            json_path, _json_text, image_path = refresh_collection_event_cache(client, only_upcoming=False)
            lines.append(f"[{now}] 收集活动缓存已刷新: {json_path} | {image_path}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"[{now}] 收集活动缓存刷新失败: {exc}")

        try:
            json_upcoming_path, _json_upcoming_text, image_upcoming_path = refresh_collection_event_cache(
                client,
                only_upcoming=True,
            )
            lines.append(f"[{now}] 收集活动 upcoming 缓存已刷新: {json_upcoming_path} | {image_upcoming_path}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"[{now}] 收集活动 upcoming 缓存刷新失败: {exc}")

        lines.append("")
        cycle_text = "\n".join(lines)
        print(cycle_text, flush=True)
        if log_path is not None:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(cycle_text + "\n")
        time.sleep(interval_seconds)
