"""成员发言导出 — 用于 AI 分析的数据导出模块

纯读操作：不修改任何表数据，不依赖 Cookie，不涉及网络请求。
供 crawl.py CLI 或程序化调用。
"""
from __future__ import annotations

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


def build_export_json(
    rows: list[dict],
    gid: int,
    sender_id: int | None,
    sender_name: str | None,
    group_name: str,
    since_ms: int | None,
    until_ms: int | None,
) -> dict:
    """将查询结果组装为适合 AI 分析的导出 JSON 结构。

    返回 {"meta": {...}, "messages": [...]}，其中 meta 含群/成员/条数/时间范围/
    过滤条件，messages 数组中每条含 created_at（毫秒）与 created_at_cst（CST 字符串）。
    """
    msgs = []
    for r in rows:
        ts = r.get("created_at") or 0
        cst_str = ms_to_cst(ts) or ""
        msgs.append({
            "mid": r.get("mid"),
            "created_at": ts,
            "created_at_cst": cst_str,
            "sender_id": r.get("sender_id"),
            "sender_name": r.get("sender_name") or "",
            "msg_type": r.get("msg_type"),
            "msg_type_name": r.get("msg_type_name") or "",
            "media_type": r.get("media_type"),
            "text": r.get("text") or "",
            "fid": r.get("fid") or "",
            "media_orig_url": r.get("media_orig_url") or "",
            "url_objects": r.get("url_objects") or "",
        })

    start_cst = msgs[0]["created_at_cst"] if msgs else ""
    end_cst = msgs[-1]["created_at_cst"] if msgs else ""
    return {
        "meta": {
            "exported_at": datetime.now(tz=CST).strftime("%Y-%m-%dT%H:%M:%S%z"),
            "group": {"gid": gid, "name": group_name},
            "member": {
                "sender_id": sender_id or None,
                "sender_name": sender_name or None,
            },
            "filters": {
                "msg_types": [100, 321],
                "since_ms": since_ms,
                "until_ms": until_ms,
                "since_cst": ms_to_cst(since_ms),
                "until_cst": ms_to_cst(until_ms),
            },
            "message_count": len(msgs),
            "time_range": {"start_cst": start_cst, "end_cst": end_cst},
        },
        "messages": msgs,
    }


# ── 高级编排（含 DB 初始化 + 文件写入）─────────────────────


def export_member_messages(
    db_path: str,
    gid: int,
    sender_name: str | None = None,
    sender_id: int | None = None,
    since_ms: int | None = None,
    until_ms: int | None = None,
    output_path: str | None = None,
) -> dict:
    """导出指定群内某成员本人发言为 JSON 文件。

    完整流程：初始化 DB 连接 → 查询消息 → 查询群名 → 组装 JSON → 写入文件。

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

    payload = build_export_json(
        rows=rows, gid=gid, sender_id=sid, sender_name=sname,
        group_name=group_name, since_ms=since_ms, until_ms=until_ms,
    )

    # 确定输出路径
    if not output_path:
        sender_slug = sname or (str(sid) if sid else "member")
        safe = "".join(c for c in sender_slug if c.isalnum() or c in "._-") or "member"
        output_path = str(Path(__file__).resolve().parent.parent / f"export_{gid}_{safe}.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    msgs = payload["messages"]
    start_cst = msgs[0]["created_at_cst"] if msgs else ""
    end_cst = msgs[-1]["created_at_cst"] if msgs else ""

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
