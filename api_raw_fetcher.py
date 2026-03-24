#!/usr/bin/env python3
"""BTD6 Open Data 原始数据获取模块。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request

API_BASE = "https://data.ninjakiwi.com"


@dataclass
class ApiClient:
    api_key: str | None = None
    timeout: int = 30
    retries: int = 5

    def get(self, path_or_url: str) -> dict[str, Any]:
        url = path_or_url if path_or_url.startswith("http") else f"{API_BASE}{path_or_url}"
        last_error: Exception | None = None

        for attempt in range(1, self.retries + 1):
            req = request.Request(url)
            req.add_header("Accept", "application/json")
            req.add_header("User-Agent", "btd6-api-processor/1.0")
            if self.api_key:
                req.add_header("Authorization", self.api_key)

            try:
                with request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                    if not payload.get("success", False):
                        err_text = payload.get("error") or "unknown api error"
                        raise RuntimeError(f"API 返回失败: {err_text}")
                    return payload
            except (error.URLError, error.HTTPError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    # 指数退避，缓解短时网络抖动和限流。
                    time.sleep(min(8.0, 1.5 ** attempt))
                else:
                    break

        raise RuntimeError(f"请求失败: {url}; 错误: {last_error}")


def fetch_raw_data(client: ApiClient) -> dict[str, Any]:
    """获取项目所需的所有原始数据，不做业务加工。"""
    races = client.get("/btd6/races").get("body", [])
    bosses = client.get("/btd6/bosses").get("body", [])
    odyssey = client.get("/btd6/odyssey").get("body", [])
    daily = client.get("/btd6/challenges/filter/daily").get("body", [])

    return {
        "races": races,
        "bosses": bosses,
        "odyssey": odyssey,
        "daily": daily,
    }
