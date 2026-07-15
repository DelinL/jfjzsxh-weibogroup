"""成员发言导出 — 用于 AI 分析的数据导出模块

纯读操作：不修改任何表数据，不依赖 Cookie，不涉及网络请求。
供 crawl.py CLI 或程序化调用。
"""
from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from .db import set_db_path, init_db, get_conn, get_group_list

CST = timezone(timedelta(hours=8))
log = logging.getLogger("weibo_im.export")


# ── 工具函数 ────────────────────────────────────────────────


def ms_to_cst(ms: int | None) -> str | None:
    """毫秒时间戳转 CST 格式化字符串；空则返回 None。"""
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=CST).strftime("%Y-%m-%d %H:%M:%S")


# ── 数据库查询（只读）───────────────────────────────────────


def get_members(gid: int) -> list[dict]:
    """返回群内发过言的成员列表（sender_id + sender_name），按最近发言倒序。

    沿用 server.py query_members_list 的口径：仅统计 msg_type IN (100, 321) 的
    真实用户发言，GROUP BY sender_id，给出 msg_count 与最近发言时间，便于定位
    准确昵称/ID。
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT sender_id, sender_name, MAX(created_at) AS last_msg_at, "
        "COUNT(*) AS msg_count FROM messages "
        "WHERE gid=? AND msg_type IN (100, 321) "
        "GROUP BY sender_id ORDER BY last_msg_at DESC",
        (gid,),
    ).fetchall()
    return [{"sender_id": r["sender_id"],
             "sender_name": r["sender_name"],
             "msg_count": r["msg_count"],
             "last_msg_at": r["last_msg_at"]} for r in rows]


def get_member_messages(
    gid: int,
    sender_id: int | None = None,
    sender_name: str | None = None,
    since_ms: int | None = None,
    until_ms: int | None = None,
    msg_types: tuple[int, ...] = (100, 321),
) -> list[dict]:
    """返回指定群内某成员本人发言（默认普通消息 321 + 微博分享 100），按时间升序。

    - sender_id 与 sender_name 可任传其一或同时传入，按传入情况拼接 WHERE；
      优先用 sender_id（稳定），sender_name 便于按可感知昵称导出。
    - since_ms/until_ms 为 created_at 毫秒范围：since 闭区间 (>=)、until 开区间 (<)，
      与项目内 CST 日期区间 [start, end) 约定一致。
    - msg_types 默认 (100, 321)；传空元组则不加该过滤（一般不必要）。

    返回每行 dict（含 mid/gid/msg_type/msg_type_name/media_type/sender_id/
    sender_name/text/fid/media_orig_url/url_objects/created_at/group_name），
    按 created_at ASC 排列，契合按时间线的 AI 序列分析。
    """
    conn = get_conn()
    conds = ["gid=?"]
    params: list[Any] = [gid]
    if msg_types:
        placeholders = ",".join("?" for _ in msg_types)
        conds.append(f"msg_type IN ({placeholders})")
        params.extend(msg_types)
    if sender_id is not None:
        conds.append("sender_id=?")
        params.append(sender_id)
    if sender_name:
        conds.append("sender_name=?")
        params.append(sender_name)
    if since_ms is not None:
        conds.append("created_at>=?")
        params.append(since_ms)
    if until_ms is not None:
        conds.append("created_at<?")
        params.append(until_ms)
    sql = (
        "SELECT mid, gid, msg_type, msg_type_name, media_type, "
        "sender_id, sender_name, text, fid, media_orig_url, "
        "url_objects, created_at, group_name "
        "FROM messages WHERE " + " AND ".join(conds) +
        " ORDER BY created_at ASC"
    )
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


# ── JSON 组装 ───────────────────────────────────────────────


def build_export_json(rows: list[dict]) -> list[dict]:
    """将查询结果组装为适合 AI 分析的导出数据。

    返回消息列表，每条仅含 sender_name（发言者昵称）与 text（正文）两项，
    按 created_at ASC 排列，契合按时间线的 AI 序列分析。
    """
    return [
        {
            "sender_name": r.get("sender_name") or "",
            "text": r.get("text") or "",
        }
        for r in rows
    ]


# ── 高级编排（含 DB 初始化 + 文件写入）─────────────────────


def export_member_messages(
    db_path: str,
    gid: int,
    sender_name: str | None = None,
    sender_id: int | None = None,
    since_ms: int | None = None,
    until_ms: int | None = None,
    output_path: str | None = None,
    compact: bool = False,
    fmt: str = "json",
) -> dict:
    """导出指定群内某成员本人发言为文件（JSON 或 CSV）。

    完整流程：初始化 DB 连接 → 查询消息 → 查询群名 → 组装数据 → 写入文件。

    fmt="json"（默认）：输出纯 JSON 数组，每条含 sender_name / text 两项。
        compact=True 时进一步输出紧凑（minified）JSON（去缩进、去空格），
        显著减小体积，适合直接喂大模型或网络传输；否则保留 2 空格缩进便于阅读。
    fmt="csv"：输出 CSV 文件，表头为 sender_name,text（UTF-8-SIG 编码，
        Excel 可直接打开且中文不乱码）；compact 参数对 CSV 无影响。

    返回结果字典:
        {"path": str,          # 输出文件路径
         "count": int,         # 导出条数
         "start_cst": str,     # 最早消息时间
         "end_cst": str,       # 最晚消息时间
         "group_name": str}    # 群名称
    """
    set_db_path(db_path)
    init_db()

    sid = sender_id if sender_id else None
    sname = sender_name or None

    rows = get_member_messages(
        gid=gid,
        sender_id=sid,
        sender_name=sname,
        since_ms=since_ms,
        until_ms=until_ms,
    )

    # 查群名称
    group_name = ""
    for g in get_group_list():
        if g["gid"] == gid:
            group_name = g.get("name", "")
            break

    msgs = build_export_json(rows)

    # 确定输出路径（CSV 用 .csv 扩展名）
    if not output_path:
        sender_slug = sname or (str(sid) if sid else "member")
        safe = "".join(c for c in sender_slug if c.isalnum() or c in "._-") or "member"
        ext = "csv" if fmt == "csv" else "json"
        output_path = str(Path(__file__).resolve().parent.parent / f"export_{gid}_{safe}.{ext}")

    if fmt == "csv":
        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["sender_name", "text"])
            writer.writeheader()
            for m in msgs:
                writer.writerow(m)
    else:
        with open(output_path, "w", encoding="utf-8") as f:
            if compact:
                json.dump(msgs, f, ensure_ascii=False, separators=(",", ":"))
            else:
                json.dump(msgs, f, ensure_ascii=False, indent=2)

    start_cst = ms_to_cst(rows[0].get("created_at")) if rows else ""
    end_cst = ms_to_cst(rows[-1].get("created_at")) if rows else ""

    log.info("已导出 %d 条发言 → %s", len(msgs), output_path)

    return {
        "path": output_path,
        "count": len(msgs),
        "start_cst": start_cst,
        "end_cst": end_cst,
        "group_name": group_name,
    }


def list_members(db_path: str, gid: int) -> list[dict]:
    """列出指定群内发过言的成员信息。

    初始化 DB → 查询成员列表 → 返回 dict 列表。
    每条含 sender_id / sender_name / msg_count / last_msg_at。
    """
    set_db_path(db_path)
    init_db()
    members = get_members(gid)
    if not members:
        log.info("该群还没有任何用户发言记录")
    else:
        log.info("群 %d 的发言成员（%d 人）:", gid, len(members))
        for m in members:
            ts = m.get("last_msg_at") or 0
            last = ms_to_cst(ts) or "(无)"
            log.info("  sender_id=%-12d 发言=%-5d 最近=%s  %s",
                     m["sender_id"], m["msg_count"], last, m["sender_name"] or "(未知)")
    return members
