#!/usr/bin/env python3
"""BTD6 数据处理 CLI 入口。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from api_raw_fetcher import ApiClient
from btd6_core.common import parse_translation_tables
from btd6_core.detail_service import resolve_detail
from btd6_core.leaderboard_service import resolve_leaderboard
from btd6_core.summary_service import build_report
from btd6_core.update_service import update_all_data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="获取 BTD6 Open Data 并生成详情/排行榜")
    parser.add_argument("--api-key", default=os.getenv("NK_API_KEY"), help="Ninja Kiwi API Key，可选。也可用环境变量 NK_API_KEY")
    parser.add_argument("--translate", default="translate.md", help="翻译表 Markdown 路径")
    parser.add_argument("--output", default="btd6_digest.md", help="输出文件路径")
    parser.add_argument(
        "--mode",
        choices=["summary", "detail", "leaderboard", "update"],
        default="summary",
        help="输出模式：summary=简报，detail=最新一期详细信息，leaderboard=排行榜，update=更新所有数据",
    )
    parser.add_argument(
        "--detail-types",
        default="race,boss,odyssey,daily",
        help="detail 模式下要输出的类型，逗号分隔：race,boss,odyssey,daily",
    )
    parser.add_argument(
        "--leaderboard-type",
        choices=["race", "boss-standard", "boss-elite"],
        default="race",
        help="leaderboard 模式类型",
    )
    parser.add_argument(
        "--leaderboard-format",
        choices=["markdown", "image"],
        default="markdown",
        help="leaderboard 输出格式：markdown 或 image（仅玩家和得分）",
    )
    parser.add_argument("--refresh", action="store_true", help="忽略本地缓存，强制重新拉取并覆盖")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = ApiClient(api_key=args.api_key)
    trans = parse_translation_tables(Path(args.translate))

    try:
        if args.mode == "summary":
            report = build_report(client, trans)

        elif args.mode == "detail":
            requested = [x.strip() for x in args.detail_types.split(",") if x.strip()]
            valid = {"race", "boss", "odyssey", "daily"}
            unknown = [x for x in requested if x not in valid]
            if unknown:
                raise ValueError(f"detail-types 含不支持的类型: {', '.join(unknown)}")

            paths: list[Path] = []
            blocks: list[str] = []
            for detail_type in requested:
                path, content, cached = resolve_detail(client, trans, detail_type, refresh=args.refresh)
                source = "缓存" if cached else "远程"
                blocks.append(f"# 来源: {source}\n# 文件: {path}\n\n{content}")
                paths.append(path)

            if len(blocks) == 1:
                report = blocks[0]
            else:
                summary = ["# 详细信息输出", ""]
                for p in paths:
                    summary.append(f"- {p}")
                summary.append("")
                summary.append("以下为合并内容：")
                summary.append("")
                summary.append("\n\n".join(blocks))
                report = "\n".join(summary)

        elif args.mode == "leaderboard":
            path, content, cached = resolve_leaderboard(
                client,
                args.leaderboard_type,
                1,
                output_format=args.leaderboard_format,
                refresh=args.refresh,
            )
            source = "缓存" if cached else "远程"
            if args.leaderboard_format == "image":
                report = f"# 来源: {source}\n# 文件: {path}\n\n已生成 排行榜表格图片（仅玩家与得分）。"
            else:
                report = f"# 来源: {source}\n# 文件: {path}\n\n{content}"

        else:
            report = update_all_data(client, trans)

    except Exception as exc:  # noqa: BLE001
        print(f"生成失败: {exc}", file=sys.stderr)
        return 1

    Path(args.output).write_text(report, encoding="utf-8")
    print(f"已生成: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
