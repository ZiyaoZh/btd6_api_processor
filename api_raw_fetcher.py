#!/usr/bin/env python3
"""BTD6 Open Data 原始数据获取模块。"""

from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request
from urllib.parse import urljoin, urlparse

API_BASE = "https://data.ninjakiwi.com"
RACES_URL = "/btd6/races"
BOSSES_URL = "/btd6/bosses"
ODYSSEY_URL = "/btd6/odyssey"
DAILY_URL = "/btd6/challenges/filter/daily"
MAX_LIST_PAGES = 10


@dataclass
class ApiClient:
    api_key: str | None = None
    timeout: int = 45
    retries: int = 2

    def _format_error(self, exc: Exception) -> str:
        if isinstance(exc, error.HTTPError):
            return f"HTTP {exc.code} {exc.reason}"
        if isinstance(exc, (socket.timeout, TimeoutError)):
            return f"读取超时（{self.timeout}s）"
        if isinstance(exc, error.URLError):
            reason = exc.reason
            if isinstance(reason, socket.timeout):
                return f"读取超时（{self.timeout}s）"
            return f"网络错误: {reason}"
        if isinstance(exc, json.JSONDecodeError):
            return "响应不是合法 JSON"
        return str(exc)

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
            except (error.URLError, error.HTTPError, socket.timeout, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    # 指数退避，缓解短时网络抖动和限流。
                    time.sleep(min(8.0, 1.5 ** attempt))
                else:
                    break

        formatted_error = self._format_error(last_error) if last_error is not None else "unknown error"
        raise RuntimeError(f"请求失败: {url}; 错误: {formatted_error}")


def fetch_paginated(
    client: ApiClient,
    path_or_url: str,
    *,
    max_pages: int = MAX_LIST_PAGES,
) -> list[dict[str, Any]]:
    page_url = _pagination_url(path_or_url)
    seen_pages: set[str] = set()
    seen_event_ids: set[str] = set()
    events: list[dict[str, Any]] = []

    for _page_number in range(max(1, int(max_pages))):
        normalized_url = urljoin(f"{API_BASE}/", page_url)
        if normalized_url in seen_pages:
            raise RuntimeError(f"分页链接形成循环: {normalized_url}")
        seen_pages.add(normalized_url)

        payload = client.get(page_url)
        body = payload.get("body")
        if not isinstance(body, list):
            raise RuntimeError(f"活动列表端点未返回数组: {page_url}")
        for item in body:
            if not isinstance(item, dict):
                continue
            event_id = str(item.get("id", "") or "").strip()
            if event_id and event_id in seen_event_ids:
                continue
            if event_id:
                seen_event_ids.add(event_id)
            events.append(item)

        next_url = payload.get("next")
        if not next_url:
            return events
        page_url = _pagination_url(str(next_url))

    raise RuntimeError(f"活动列表分页超过安全上限 {max(1, int(max_pages))} 页")


def _pagination_url(path_or_url: str) -> str:
    raw = str(path_or_url or "").strip()
    if not raw:
        raise RuntimeError("分页链接为空")
    absolute = urljoin(f"{API_BASE}/", raw)
    parsed = urlparse(absolute)
    api_host = urlparse(API_BASE).hostname
    if parsed.scheme != "https" or parsed.hostname != api_host:
        raise RuntimeError(f"拒绝非 Ninja Kiwi 域名的分页链接: {raw}")
    return raw if raw.startswith("/") else absolute


def fetch_races(client: ApiClient) -> list[dict[str, Any]]:
    return fetch_paginated(client, RACES_URL)


def fetch_bosses(client: ApiClient) -> list[dict[str, Any]]:
    return fetch_paginated(client, BOSSES_URL)


def fetch_odyssey(client: ApiClient) -> list[dict[str, Any]]:
    return fetch_paginated(client, ODYSSEY_URL)


def fetch_daily_challenges(client: ApiClient) -> list[dict[str, Any]]:
    return fetch_paginated(client, DAILY_URL)


def fetch_raw_data(client: ApiClient) -> dict[str, Any]:
    """获取项目所需的所有原始数据，不做业务加工。"""
    races = fetch_races(client)
    bosses = fetch_bosses(client)
    odyssey = fetch_odyssey(client)
    daily = fetch_daily_challenges(client)

    return {
        "races": races,
        "bosses": bosses,
        "odyssey": odyssey,
        "daily": daily,
    }
