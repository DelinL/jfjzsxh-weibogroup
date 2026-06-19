# 微博群聊消息查看器前端 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `weibo_im.db` 做一个本地只读 web 查看器：按日期跳转浏览群聊消息（最新在底、向上翻更早），支持发送者筛选与关键词 `LIKE` 模糊搜索（搜索结果可跳转到上下文翻看）。

**Architecture:** 新增 `server.py`（标准库 `http.server` + `sqlite3`，只读打开）提供 JSON API 和静态文件；新增 `web/`（原生 HTML/JS/CSS，无框架）。右栏聊天视图用 `(created_at, id)` 复合游标双向分页，每页 500 条。不引入任何新依赖。

**Tech Stack:** Python 标准库（http.server / sqlite3 / argparse / json / urllib）、原生 HTML+CSS+JS、Python unittest。

**设计依据:** `docs/superpowers/specs/2026-06-19-weibo-im-message-viewer-design.md`

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `server.py` | HTTP 服务 + JSON API。单一文件，含路由分发、查询函数、主入口。只读打开 SQLite。 |
| `web/index.html` | 单页结构骨架：顶栏、左栏日期列表、右栏聊天视图、搜索浮层。 |
| `web/app.js` | 全部前端交互逻辑：状态管理、API 调用、渲染、双向滚动加载、搜索跳转。 |
| `web/style.css` | 样式：三栏布局、气泡、系统消息、浮层、高亮动画。 |
| `tests/test_server.py` | 后端 API 单测：用临时 SQLite 验证游标分页、LIKE 转义、日期聚合、发送者筛选。 |
| `tests/conftest.py` | 测试夹具：构造临时小数据库与已知消息。 |

不改动 `weibo_im/` 包内任何文件。

---

## 实现顺序总览

1. **Task 1** — 搭建 server.py 骨架（静态文件 + 启动入口）与测试夹具
2. **Task 2** — 元数据 API：`/api/groups`、`/api/dates`、`/api/senders`
3. **Task 3** — 游标分页核心 API：`/api/messages`（双向游标）
4. **Task 4** — 锚点 API：`/api/messages/by_date`、`/api/messages/around`
5. **Task 5** — 搜索 API：`/api/search`（LIKE + 范围）
6. **Task 6** — 前端骨架：HTML + CSS 三栏布局
7. **Task 7** — 前端核心：状态机 + 群/日期加载 + 选日期渲染
8. **Task 8** — 双向滚动加载 + 发送者筛选
9. **Task 9** — 搜索浮层 + 跳转上下文 + 高亮
10. **Task 10** — 端到端走查与收尾

---

## Task 1: server.py 骨架与测试夹具

**Files:**
- Create: `server.py`
- Create: `tests/conftest.py`
- Create: `tests/__init__.py`

本任务搭建能启动的空壳：解析命令行参数、只读打开数据库、提供静态文件（`/` → `web/index.html`，`/web/<file>` → `web/` 下文件）、对未知路径返回 404、对 `/api/*` 路径返回占位 501。同时建立测试夹具：构造一个内存/临时文件的 SQLite，建出与生产一致的 `messages` 和 `groups` 表结构，插入若干已知消息供后续任务测查询。

- [ ] **Step 1: 写测试夹具 `tests/conftest.py`**

```python
"""测试夹具：构造临时小数据库，结构与生产 messages/groups 表一致。"""
import os
import sqlite3
import tempfile

# 与生产 messages 表完全一致的建表语句（复制自 weibo_im.db 实际 schema）
MESSAGES_DDL = """
CREATE TABLE messages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    mid              TEXT NOT NULL UNIQUE,
    gid              INTEGER NOT NULL,
    msg_type         INTEGER NOT NULL DEFAULT 321,
    msg_type_name    TEXT NOT NULL DEFAULT '',
    media_type       INTEGER DEFAULT 0,
    sender_id        INTEGER NOT NULL DEFAULT 0,
    sender_name      TEXT DEFAULT '',
    text             TEXT DEFAULT '',
    fid              TEXT DEFAULT '',
    media_orig_url   TEXT DEFAULT '',
    media_local_path TEXT DEFAULT '',
    url_objects      TEXT DEFAULT '',
    pic_infos        TEXT DEFAULT '',
    template         TEXT DEFAULT '',
    template_data    TEXT DEFAULT '{}',
    recall_mids      TEXT DEFAULT '[]',
    recall_by        TEXT DEFAULT '',
    attitude_data    TEXT DEFAULT '{}',
    faith_status     INTEGER DEFAULT 0,
    faith_icon       TEXT DEFAULT '',
    group_name       TEXT DEFAULT '',
    annotations      TEXT DEFAULT '{}',
    created_at       INTEGER NOT NULL,
    saved_at         INTEGER NOT NULL,
    raw_json         TEXT DEFAULT ''
)
"""

GROUPS_DDL = """
CREATE TABLE groups (
    gid            INTEGER PRIMARY KEY,
    name           TEXT NOT NULL DEFAULT '',
    avatar         TEXT DEFAULT '',
    round_avatar   TEXT DEFAULT '',
    member_count   INTEGER DEFAULT 0,
    max_member     INTEGER DEFAULT 0,
    owner_id       INTEGER DEFAULT 0,
    admins         TEXT DEFAULT '[]',
    summary        TEXT DEFAULT '',
    group_type     INTEGER DEFAULT 0,
    super_group_type INTEGER DEFAULT 0,
    status         INTEGER DEFAULT 0,
    validate_type  INTEGER DEFAULT 0,
    raw_json       TEXT DEFAULT '',
    created_at     INTEGER DEFAULT 0,
    updated_at     INTEGER DEFAULT 0,
    min_mid        TEXT DEFAULT '',
    max_mid        TEXT DEFAULT ''
)
"""

INDEXES_DDL = [
    "CREATE INDEX idx_msg_gid   ON messages(gid)",
    "CREATE INDEX idx_msg_mtype ON messages(msg_type)",
    "CREATE INDEX idx_msg_ctime ON messages(created_at)",
    "CREATE INDEX idx_msg_mid   ON messages(mid)",
    "CREATE INDEX idx_msg_fid   ON messages(fid)",
]


def make_test_db():
    """创建一个临时文件 SQLite，建表建索引，返回 db 路径。

    调用方负责在测试结束后删除该文件（unittest 的 addCleanup 或 tmp 目录）。
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.executescript(MESSAGES_DDL)
    conn.executescript(GROUPS_DDL)
    for ddl in INDEXES_DDL:
        conn.execute(ddl)
    conn.commit()
    conn.close()
    return path


def insert_messages(conn, rows):
    """批量插入消息。rows 是 list[dict]，缺失字段用默认值。"""
    cols = [
        "mid", "gid", "msg_type", "msg_type_name", "media_type",
        "sender_id", "sender_name", "text", "fid", "media_orig_url",
        "url_objects", "pic_infos", "template", "template_data",
        "recall_by", "group_name", "created_at", "saved_at",
    ]
    defaults = {c: "" for c in cols}
    defaults.update({"msg_type": 321, "media_type": 0, "sender_id": 0,
                     "template_data": "{}", "created_at": 0, "saved_at": 0})
    placeholders = ",".join("?" for _ in cols)
    sql = f"INSERT INTO messages ({','.join(cols)}) VALUES ({placeholders})"
    conn.executemany(sql, [[r.get(c, defaults[c]) for c in cols] for r in rows])
    conn.commit()
```

- [ ] **Step 2: 写 `tests/__init__.py`**（空文件，使 tests 成为包）

```python
```

- [ ] **Step 3: 写第一个测试 —— server 能启动且静态文件可访问**

`tests/test_server.py`：

```python
import http.client
import os
import socket
import threading
import unittest

from tests.conftest import make_test_db
import server


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class ServerSkeletonTest(unittest.TestCase):
    def setUp(self):
        self.db_path = make_test_db()
        self.port = _free_port()
        self.httpd = server.make_server("127.0.0.1", self.port, self.db_path)
        self.t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.t.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        os.remove(self.db_path)

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        return resp.status, body

    def test_index_html_served(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("<html", body)

    def test_unknown_api_returns_501(self):
        status, _ = self._get("/api/unknown")
        self.assertEqual(status, 501)

    def test_404_for_missing(self):
        status, _ = self._get("/nope")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: 运行测试确认失败（server.py 尚不存在）**

Run: `python -m unittest tests.test_server -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server'`

- [ ] **Step 5: 写 `server.py` 骨架**

```python
"""微博群聊消息查看器 —— 本地只读 web 服务。

标准库实现，零外部依赖。只读打开 weibo_im.db，提供 JSON API 与静态前端。
启动：python server.py   访问：http://127.0.0.1:8765
"""
import argparse
import json
import mimetypes
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

# ---------- 数据库 ----------

def open_db(db_path):
    """以只读模式打开 SQLite，返回连接。设置 row_factory 便于按列名取值。"""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ---------- HTTP Handler ----------

class Handler(BaseHTTPRequestHandler):
    # 子类在 make_server 中注入 db_path 与 conn
    db_path = None

    def log_message(self, *args):
        pass  # 静默，避免刷屏

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, body, status=200, content_type="text/plain; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/":
            self._serve_static("index.html")
            return
        if path.startswith("/web/"):
            self._serve_static(path[len("/web/"):])
            return
        if path.startswith("/api/"):
            self._send_json({"error": "not implemented"}, status=501)
            return
        self._send_text("Not Found", status=404)

    def _serve_static(self, rel):
        # 防目录穿越
        rel = rel.replace("\\", "/").lstrip("/")
        full = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not full.startswith(os.path.normpath(WEB_DIR)):
            self._send_text("Forbidden", status=403)
            return
        if not os.path.isfile(full):
            self._send_text("Not Found", status=404)
            return
        ctype, _ = mimetypes.guess_type(full)
        with open(full, "rb") as f:
            self._send_text(f.read(), content_type=ctype or "application/octet-stream")


# ---------- 工厂 ----------

def make_server(host, port, db_path):
    """构造 ThreadingHTTPServer，把 db_path 绑到 Handler 类上。"""
    Handler.db_path = db_path
    Handler.conn = open_db(db_path)
    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description="微博群聊消息查看器")
    default_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weibo_im.db")
    parser.add_argument("--db", default=default_db, help="SQLite 数据库路径")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    httpd = make_server(args.host, args.port, args.db)
    print(f"查看器已启动：http://{args.host}:{args.port}  (db={args.db})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
        httpd.shutdown()


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 创建占位的 `web/index.html` 使 `/` 能返回 200**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>微博群聊消息查看器</title></head>
<body>占位</body>
</html>
```

- [ ] **Step 7: 运行测试确认通过**

Run: `python -m unittest tests.test_server -v`
Expected: 4 个测试 PASS（index/501/404 + setUp/tearDown 正常）

- [ ] **Step 8: 手动启动确认**

Run: `python server.py`，浏览器打开 `http://127.0.0.1:8765/` 看到"占位"。Ctrl+C 停止。

- [ ] **Step 9: 提交**

```bash
git add server.py web/index.html tests/__init__.py tests/conftest.py tests/test_server.py
git commit -m "feat: 搭建 server.py 骨架与测试夹具"
```

---

## Task 2: 元数据 API — groups / dates / senders

**Files:**
- Modify: `server.py`（在 Handler 内增加 API 路由与查询函数）
- Modify: `tests/test_server.py`（增加元数据测试）

实现三个只读元数据端点：
- `GET /api/groups` → `[{gid, name, msg_count}]`，按 msg_count 倒序
- `GET /api/dates?gid=` → `[{date, count}]`，date 为 CST `YYYY-MM-DD`，按 date 倒序
- `GET /api/senders?gid=` → `[{sender_id, sender_name, count}]`，按 count 倒序

CST 转换：`date(datetime(created_at/1000,'unixepoch','+8 hours'))`。

- [ ] **Step 1: 写失败测试 —— groups/dates/senders**

在 `tests/test_server.py` 末尾（`if __name__` 之前）追加：

```python
class MetadataApiTest(unittest.TestCase):
    def setUp(self):
        self.db_path = make_test_db()
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO groups(gid,name) VALUES(100,'群A'),(200,'群B')")
        # 群100：2026-06-17 两条，2026-06-16 一条；群200 一条
        insert_messages(conn, [
            {"mid": "m1", "gid": 100, "sender_id": 1, "sender_name": "甲",
             "text": "hi", "created_at": 1750200000000},  # 2026-06-18 CST
            {"mid": "m2", "gid": 100, "sender_id": 2, "sender_name": "乙",
             "text": "yo", "created_at": 1750113600000},  # 2026-06-17 CST
            {"mid": "m3", "gid": 100, "sender_id": 1, "sender_name": "甲",
             "text": "x", "created_at": 1750113600000},   # 同毫秒 tiebreaker 后续测
            {"mid": "m4", "gid": 200, "sender_id": 9, "sender_name": "丙",
             "text": "z", "created_at": 1750113600000},
        ])
        conn.close()
        self.port = _free_port()
        self.httpd = server.make_server("127.0.0.1", self.port, self.db_path)
        self.t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.t.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        os.remove(self.db_path)

    def _get_json(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        return resp.status, json.loads(body)

    def test_groups(self):
        status, data = self._get_json("/api/groups")
        self.assertEqual(status, 200)
        self.assertEqual(data, [
            {"gid": 100, "name": "群A", "msg_count": 3},
            {"gid": 200, "name": "群B", "msg_count": 1},
        ])

    def test_dates(self):
        status, data = self._get_json("/api/dates?gid=100")
        self.assertEqual(status, 200)
        self.assertEqual(data, [
            {"date": "2026-06-18", "count": 1},
            {"date": "2026-06-17", "count": 2},
        ])

    def test_senders(self):
        status, data = self._get_json("/api/senders?gid=100")
        self.assertEqual(status, 200)
        self.assertEqual(data, [
            {"sender_id": 1, "sender_name": "甲", "count": 2},
            {"sender_id": 2, "sender_name": "乙", "count": 1},
        ])
```

注：测试文件顶部需 `import sqlite3` 与 `import json`（若已有则跳过）。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_server.MetadataApiTest -v`
Expected: FAIL — `/api/groups` 返回 501（骨架只返回 not implemented）

- [ ] **Step 3: 在 server.py 实现元数据查询函数与路由**

在 `server.py` 的 `# ---------- HTTP Handler ----------` 之前，增加查询函数：

```python
# ---------- 查询函数 ----------

def query_groups(conn):
    rows = conn.execute(
        "SELECT g.gid, g.name, COUNT(m.id) AS msg_count "
        "FROM groups g LEFT JOIN messages m ON m.gid = g.gid "
        "GROUP BY g.gid ORDER BY msg_count DESC, g.gid"
    ).fetchall()
    return [{"gid": r["gid"], "name": r["name"], "msg_count": r["msg_count"]}
            for r in rows]


def query_dates(conn, gid):
    rows = conn.execute(
        "SELECT date(datetime(created_at/1000,'unixepoch','+8 hours')) AS d, "
        "COUNT(*) AS c FROM messages WHERE gid=? "
        "GROUP BY d ORDER BY d DESC",
        (gid,),
    ).fetchall()
    return [{"date": r["d"], "count": r["c"]} for r in rows]


def query_senders(conn, gid):
    rows = conn.execute(
        "SELECT sender_id, sender_name, COUNT(*) AS c "
        "FROM messages WHERE gid=? AND sender_id<>0 "
        "GROUP BY sender_id ORDER BY c DESC, sender_id",
        (gid,),
    ).fetchall()
    return [{"sender_id": r["sender_id"],
             "sender_name": r["sender_name"] or str(r["sender_id"]),
             "count": r["c"]} for r in rows]
```

修改 `Handler.do_GET` 中 `/api/` 分支，替换占位 501：

```python
        if path.startswith("/api/"):
            self._route_api(path, qs)
            return
```

并在 `Handler` 类内增加 `_route_api`：

```python
    def _route_api(self, path, qs):
        conn = self.conn
        try:
            if path == "/api/groups":
                self._send_json(query_groups(conn))
            elif path == "/api/dates":
                gid = int(qs.get("gid", ["0"])[0])
                self._send_json(query_dates(conn, gid))
            elif path == "/api/senders":
                gid = int(qs.get("gid", ["0"])[0])
                self._send_json(query_senders(conn, gid))
            else:
                self._send_json({"error": "not found"}, status=404)
        except Exception as e:
            self._send_json({"error": str(e)}, status=500)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest tests.test_server.MetadataApiTest -v`
Expected: 3 个测试 PASS

- [ ] **Step 5: 提交**

```bash
git add server.py tests/test_server.py
git commit -m "feat: 元数据 API（groups/dates/senders）"
```

---

## Task 3: 游标分页核心 API — `/api/messages`

**Files:**
- Modify: `server.py`（增加 `query_messages` + 路由）
- Modify: `tests/test_server.py`（增加游标测试）

实现双向游标分页。排序固定 `created_at ASC, id ASC`（DOM 升序，最新在底）。游标用 `(created_at, id)` 复合。

参数：
- `gid`（必填）
- `sender_id`（可选，0 或缺省 = 全部）
- `before_ts` + `before_id`：向上加载更早（取 `< ` 本页最旧）
- `after_ts` + `after_id`：向下加载更新（取 `> ` 本页最新）
- `limit`（默认 500）

返回：
```json
{
  "messages": [ ... ],
  "oldest": {"ts": int, "id": int},
  "newest": {"ts": int, "id": int},
  "has_more_older": bool,
  "has_more_newer": bool
}
```
当 `messages` 为空时，`oldest`/`newest` 为 `null`，`has_more_*` 为 `false`。

- [ ] **Step 1: 写失败测试 —— 双向游标、同毫秒 tiebreaker、不漏不重**

在 `tests/test_server.py` 末尾追加：

```python
class MessagesCursorTest(unittest.TestCase):
    def setUp(self):
        self.db_path = make_test_db()
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO groups(gid,name) VALUES(100,'群A')")
        # 5 条消息：ts 递增；其中 m2/m3 同毫秒、m4/m5 同毫秒，测 tiebreaker
        # id 顺序与 ts 顺序一致，便于预期
        insert_messages(conn, [
            {"mid": "m1", "gid": 100, "sender_id": 1, "text": "a", "created_at": 1000},
            {"mid": "m2", "gid": 100, "sender_id": 1, "text": "b", "created_at": 2000},
            {"mid": "m3", "gid": 100, "sender_id": 2, "text": "c", "created_at": 2000},
            {"mid": "m4", "gid": 100, "sender_id": 1, "text": "d", "created_at": 3000},
            {"mid": "m5", "gid": 100, "sender_id": 2, "text": "e", "created_at": 3000},
        ])
        conn.close()
        self.port = _free_port()
        self.httpd = server.make_server("127.0.0.1", self.port, self.db_path)
        self.t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.t.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        os.remove(self.db_path)

    def _get_json(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        return resp.status, json.loads(body)

    def test_after_cursor_loads_newer(self):
        # 用 after 游标 = m2(ts=2000,id=2)，取更新的：m3,m4,m5（同毫秒 id>2 + ts>2000）
        path = "/api/messages?gid=100&after_ts=2000&after_id=2&limit=500"
        status, data = self._get_json(path)
        self.assertEqual(status, 200)
        mids = [m["mid"] for m in data["messages"]]
        self.assertEqual(mids, ["m3", "m4", "m5"])
        self.assertFalse(data["has_more_newer"])
        self.assertEqual(data["newest"], {"ts": 3000, "id": 5})

    def test_before_cursor_loads_older(self):
        # 用 before 游标 = m4(ts=3000,id=4)，取更早的：m1,m2,m3
        path = "/api/messages?gid=100&before_ts=3000&before_id=4&limit=500"
        status, data = self._get_json(path)
        self.assertEqual(status, 200)
        mids = [m["mid"] for m in data["messages"]]
        self.assertEqual(mids, ["m1", "m2", "m3"])  # 升序
        self.assertFalse(data["has_more_older"])
        self.assertEqual(data["oldest"], {"ts": 1000, "id": 1})

    def test_limit_caps_results_and_has_more(self):
        # after=m1，limit=2，应返回 m2,m3，且 has_more_newer=True
        path = "/api/messages?gid=100&after_ts=1000&after_id=1&limit=2"
        status, data = self._get_json(path)
        self.assertEqual(status, 200)
        mids = [m["mid"] for m in data["messages"]]
        self.assertEqual(mids, ["m2", "m3"])
        self.assertTrue(data["has_more_newer"])

    def test_sender_filter(self):
        # after=m1，只看 sender_id=2：m3,m5（跳过 m2,m4）
        path = "/api/messages?gid=100&after_ts=1000&after_id=1&sender_id=2&limit=500"
        status, data = self._get_json(path)
        self.assertEqual(status, 200)
        mids = [m["mid"] for m in data["messages"]]
        self.assertEqual(mids, ["m3", "m5"])

    def test_no_cursor_returns_from_oldest(self):
        # 不带游标：从最旧开始升序取 limit
        path = "/api/messages?gid=100&limit=500"
        status, data = self._get_json(path)
        self.assertEqual(status, 200)
        mids = [m["mid"] for m in data["messages"]]
        self.assertEqual(mids, ["m1", "m2", "m3", "m4", "m5"])
        self.assertTrue(data["has_more_newer"])  # 无上界，视为可能还有

    def test_empty_when_no_match(self):
        path = "/api/messages?gid=999&limit=500"
        status, data = self._get_json(path)
        self.assertEqual(status, 200)
        self.assertEqual(data["messages"], [])
        self.assertIsNone(data["oldest"])
        self.assertIsNone(data["newest"])
        self.assertFalse(data["has_more_older"])
        self.assertFalse(data["has_more_newer"])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_server.MessagesCursorTest -v`
Expected: FAIL — `/api/messages` 仍返回 404（未路由）

- [ ] **Step 3: 实现 `query_messages` 与 `row_to_msg`**

在 `server.py` 查询函数区增加：

```python
# messages 查询选取的列（供 row_to_msg 使用，保持一致）
MSG_COLUMNS = (
    "id, mid, gid, msg_type, msg_type_name, media_type, "
    "sender_id, sender_name, text, fid, media_orig_url, "
    "url_objects, pic_infos, template, template_data, recall_by, "
    "group_name, created_at"
)


def row_to_msg(r):
    return {
        "id": r["id"],
        "mid": r["mid"],
        "gid": r["gid"],
        "msg_type": r["msg_type"],
        "msg_type_name": r["msg_type_name"],
        "media_type": r["media_type"],
        "sender_id": r["sender_id"],
        "sender_name": r["sender_name"],
        "text": r["text"],
        "fid": r["fid"],
        "media_orig_url": r["media_orig_url"],
        "url_objects": r["url_objects"],
        "pic_infos": r["pic_infos"],
        "template": r["template"],
        "template_data": r["template_data"],
        "recall_by": r["recall_by"],
        "group_name": r["group_name"],
        "created_at": r["created_at"],
    }


def _has_more(conn, gid, sender_cond, sender_params, where_clause, params):
    """检查指定方向是否还有更多消息。"""
    sql = (f"SELECT 1 FROM messages WHERE gid=? {sender_cond} {where_clause} "
           f"LIMIT 1")
    return conn.execute(sql, (gid,) + sender_params + params).fetchone() is not None


def query_messages(conn, gid, sender_id, before_ts, before_id,
                   after_ts, after_id, limit):
    """双向游标分页。before/after 二选一，无则从最旧开始升序取 limit。"""
    sender_cond = ""
    sender_params = ()
    if sender_id:
        sender_cond = "AND sender_id=?"
        sender_params = (sender_id,)

    where = ""
    params = ()
    if before_ts is not None:
        where = ("AND (created_at < ? OR (created_at = ? AND id < ?))")
        params = (before_ts, before_ts, before_id)
    elif after_ts is not None:
        where = ("AND (created_at > ? OR (created_at = ? AND id > ?))")
        params = (after_ts, after_ts, after_id)

    sql = (f"SELECT {MSG_COLUMNS} FROM messages "
           f"WHERE gid=? {sender_cond} {where} "
           f"ORDER BY created_at ASC, id ASC LIMIT ?")
    rows = conn.execute(sql, (gid,) + sender_params + params + (limit,)).fetchall()
    msgs = [row_to_msg(r) for r in rows]

    if not msgs:
        return {"messages": [], "oldest": None, "newest": None,
                "has_more_older": False, "has_more_newer": False}

    oldest = {"ts": msgs[0]["created_at"], "id": msgs[0]["id"]}
    newest = {"ts": msgs[-1]["created_at"], "id": msgs[-1]["id"]}

    # has_more_older：比本页最旧更早的（同毫秒 id 更小也算）
    has_more_older = _has_more(
        conn, gid, sender_cond, sender_params,
        "AND (created_at < ? OR (created_at = ? AND id < ?))",
        (oldest["ts"], oldest["ts"], oldest["id"]))
    # has_more_newer：比本页最新更新的
    has_more_newer = _has_more(
        conn, gid, sender_cond, sender_params,
        "AND (created_at > ? OR (created_at = ? AND id > ?))",
        (newest["ts"], newest["ts"], newest["id"]))

    return {"messages": msgs, "oldest": oldest, "newest": newest,
            "has_more_older": has_more_older, "has_more_newer": has_more_newer}
```

- [ ] **Step 4: 在 `_route_api` 增加路由**

```python
            elif path == "/api/messages":
                gid = int(qs.get("gid", ["0"])[0])
                sender_id = int(qs.get("sender_id", ["0"])[0]) or 0
                limit = int(qs.get("limit", ["500"])[0])
                before_ts = _opt_int(qs, "before_ts")
                before_id = _opt_int(qs, "before_id")
                after_ts = _opt_int(qs, "after_ts")
                after_id = _opt_int(qs, "after_id")
                self._send_json(query_messages(
                    conn, gid, sender_id, before_ts, before_id,
                    after_ts, after_id, limit))
```

在 `server.py` 顶部工具区（查询函数之前）加 `_opt_int`：

```python
def _opt_int(qs, key):
    v = qs.get(key, [None])[0]
    return int(v) if v not in (None, "") else None
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m unittest tests.test_server.MessagesCursorTest -v`
Expected: 6 个测试 PASS

- [ ] **Step 6: 提交**

```bash
git add server.py tests/test_server.py
git commit -m "feat: 游标分页核心 API /api/messages"
```

---

## Task 4: 锚点 API — by_date / around

**Files:**
- Modify: `server.py`
- Modify: `tests/test_server.py`

两个锚点端点：
- `GET /api/messages/by_date?gid=&date=&sender_id=&limit=500`：取该 CST 日期最新 limit 条，服务端反转为升序返回。响应结构与 `/api/messages` 一致。
- `GET /api/messages/around?gid=&mid=&limit=500`：以 mid 对应消息为锚，取它及之前（更早方向）limit 条，反转为升序。响应结构一致，额外带 `anchor_mid`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_server.py` 末尾追加：

```python
class AnchorApiTest(unittest.TestCase):
    def setUp(self):
        self.db_path = make_test_db()
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO groups(gid,name) VALUES(100,'群A')")
        # 2026-06-17 CST 对应 ts 范围。用 1750113600000 (2026-06-17 00:00 CST) 起
        base = 1750113600000
        insert_messages(conn, [
            {"mid": "d1", "gid": 100, "sender_id": 1, "text": "1", "created_at": base + 1000},
            {"mid": "d2", "gid": 100, "sender_id": 1, "text": "2", "created_at": base + 2000},
            {"mid": "d3", "gid": 100, "sender_id": 2, "text": "3", "created_at": base + 3000},
            {"mid": "d4", "gid": 100, "sender_id": 1, "text": "4", "created_at": base + 86400000},  # 次日
        ])
        conn.close()
        self.port = _free_port()
        self.httpd = server.make_server("127.0.0.1", self.port, self.db_path)
        self.t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.t.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        os.remove(self.db_path)

    def _get_json(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        return resp.status, json.loads(body)

    def test_by_date_returns_latest_of_day_ascending(self):
        # 2026-06-17 有 d1,d2,d3；取最新 limit 条（即全部），升序返回
        path = "/api/messages/by_date?gid=100&date=2026-06-17&limit=500"
        status, data = self._get_json(path)
        self.assertEqual(status, 200)
        mids = [m["mid"] for m in data["messages"]]
        self.assertEqual(mids, ["d1", "d2", "d3"])
        self.assertEqual(data["newest"], {"ts": self.base + 3000, "id": 3})

    def test_by_date_limit_caps_to_latest(self):
        # limit=2：取最新 2 条（d2,d3），升序返回
        path = "/api/messages/by_date?gid=100&date=2026-06-17&limit=2"
        status, data = self._get_json(path)
        self.assertEqual(status, 200)
        mids = [m["mid"] for m in data["messages"]]
        self.assertEqual(mids, ["d2", "d3"])

    def test_by_date_sender_filter(self):
        path = "/api/messages/by_date?gid=100&date=2026-06-17&sender_id=2&limit=500"
        status, data = self._get_json(path)
        self.assertEqual(status, 200)
        mids = [m["mid"] for m in data["messages"]]
        self.assertEqual(mids, ["d3"])

    def test_around_anchors_at_mid(self):
        # 以 d3 为锚，取它及之前 limit 条，升序：d1,d2,d3
        path = "/api/messages/around?gid=100&mid=d3&limit=500"
        status, data = self._get_json(path)
        self.assertEqual(status, 200)
        mids = [m["mid"] for m in data["messages"]]
        self.assertEqual(mids, ["d1", "d2", "d3"])
        self.assertEqual(data["anchor_mid"], "d3")
        self.assertFalse(data["has_more_older"])

    def test_around_has_more_newer(self):
        # 以 d2 为锚：d1,d2 返回，d3/d4 在后面 → has_more_newer True
        path = "/api/messages/around?gid=100&mid=d2&limit=500"
        status, data = self._get_json(path)
        self.assertEqual(status, 200)
        self.assertTrue(data["has_more_newer"])
```

注：`base_for(self)` 取 setUp 里的 base 值。为避免闭包问题，在测试类内把 `base` 存为属性：修改 setUp 增加 `self.base = base`，并把测试里的 `base_for(self)` 改为 `self.base`，断言改为 `{"ts": self.base + 3000, "id": 3}`。

（实现时按上述修正：setUp 内 `self.base = 1750113600000`，测试引用 `self.base`。）

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_server.AnchorApiTest -v`
Expected: FAIL — 路由未实现

- [ ] **Step 3: 实现 `query_by_date` 与 `query_around`**

在 `server.py` 查询函数区增加：

```python
def _build_response(conn, msgs, gid, sender_cond, sender_params, anchor_mid=None):
    """复用：从升序 msgs 构造与 /api/messages 一致的响应结构。"""
    if not msgs:
        return {"messages": [], "oldest": None, "newest": None,
                "has_more_older": False, "has_more_newer": False,
                **({"anchor_mid": anchor_mid} if anchor_mid else {})}
    oldest = {"ts": msgs[0]["created_at"], "id": msgs[0]["id"]}
    newest = {"ts": msgs[-1]["created_at"], "id": msgs[-1]["id"]}
    has_more_older = _has_more(
        conn, gid, sender_cond, sender_params,
        "AND (created_at < ? OR (created_at = ? AND id < ?))",
        (oldest["ts"], oldest["ts"], oldest["id"]))
    has_more_newer = _has_more(
        conn, gid, sender_cond, sender_params,
        "AND (created_at > ? OR (created_at = ? AND id > ?))",
        (newest["ts"], newest["ts"], newest["id"]))
    resp = {"messages": msgs, "oldest": oldest, "newest": newest,
            "has_more_older": has_more_older, "has_more_newer": has_more_newer}
    if anchor_mid is not None:
        resp["anchor_mid"] = anchor_mid
    return resp


def query_by_date(conn, gid, date, sender_id, limit):
    """取某 CST 日期最新 limit 条，反转为升序返回。"""
    sender_cond = "AND sender_id=?" if sender_id else ""
    sender_params = (sender_id,) if sender_id else ()
    sql = (f"SELECT {MSG_COLUMNS} FROM messages "
           f"WHERE gid=? AND date(datetime(created_at/1000,'unixepoch','+8 hours'))=? "
           f"{sender_cond} ORDER BY created_at DESC, id DESC LIMIT ?")
    rows = conn.execute(sql, (gid, date) + sender_params + (limit,)).fetchall()
    msgs = [row_to_msg(r) for r in rows]
    msgs.reverse()  # 反转为升序
    return _build_response(conn, msgs, gid, sender_cond, sender_params)


def query_around(conn, gid, mid, limit):
    """以 mid 对应消息为锚，取它及之前 limit 条，反转为升序返回。"""
    anchor = conn.execute(
        f"SELECT {MSG_COLUMNS} FROM messages WHERE mid=?", (mid,)).fetchone()
    if anchor is None:
        return {"messages": [], "oldest": None, "newest": None,
                "has_more_older": False, "has_more_newer": False,
                "anchor_mid": mid}
    a = row_to_msg(anchor)
    # 取严格早于锚点 + 锚点本身，倒序取 limit
    sql = (f"SELECT {MSG_COLUMNS} FROM messages WHERE gid=? "
           f"AND (created_at < ? OR (created_at = ? AND id <= ?)) "
           f"ORDER BY created_at DESC, id DESC LIMIT ?")
    rows = conn.execute(sql, (gid, a["created_at"], a["created_at"], a["id"], limit)).fetchall()
    msgs = [row_to_msg(r) for r in rows]
    msgs.reverse()
    return _build_response(conn, msgs, gid, "", (), anchor_mid=mid)
```

- [ ] **Step 4: 在 `_route_api` 增加路由**

```python
            elif path == "/api/messages/by_date":
                gid = int(qs.get("gid", ["0"])[0])
                date = qs.get("date", [""])[0]
                sender_id = int(qs.get("sender_id", ["0"])[0]) or 0
                limit = int(qs.get("limit", ["500"])[0])
                self._send_json(query_by_date(conn, gid, date, sender_id, limit))
            elif path == "/api/messages/around":
                gid = int(qs.get("gid", ["0"])[0])
                mid = qs.get("mid", [""])[0]
                limit = int(qs.get("limit", ["500"])[0])
                self._send_json(query_around(conn, gid, mid, limit))
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m unittest tests.test_server.AnchorApiTest -v`
Expected: 5 个测试 PASS

- [ ] **Step 6: 全量回归**

Run: `python -m unittest tests.test_server -v`
Expected: 全部 PASS（骨架 + 元数据 + 游标 + 锚点）

- [ ] **Step 7: 提交**

```bash
git add server.py tests/test_server.py
git commit -m "feat: 锚点 API by_date / around"
```

---

## Task 5: 搜索 API — `/api/search`

**Files:**
- Modify: `server.py`
- Modify: `tests/test_server.py`

`GET /api/search?gid=&q=&days=&limit=200`：
- `q` 关键词，`LIKE '%q%'`，转义 `% _ \`，配 `ESCAPE '\'`
- `days` 范围天数（7/30/90），默认 90；下界 = 该群最新消息 `created_at - days*86400000`
- 按 `created_at DESC, id DESC` 取 limit 条
- 返回 `[{mid, sender_id, sender_name, created_at, text, snippet}]`，snippet 为关键词前后各 ~30 字，关键词用 `\x00`/`\x01` 包裹供前端替换为 `<mark>`

- [ ] **Step 1: 写失败测试**

在 `tests/test_server.py` 末尾追加：

```python
class SearchApiTest(unittest.TestCase):
    def setUp(self):
        self.db_path = make_test_db()
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO groups(gid,name) VALUES(100,'群A')")
        base = 1750113600000  # 2026-06-17
        insert_messages(conn, [
            {"mid": "s1", "gid": 100, "sender_id": 1, "sender_name": "甲",
             "text": "今天天气不错", "created_at": base},
            {"mid": "s2", "gid": 100, "sender_id": 2, "sender_name": "乙",
             "text": "天气真好啊天气", "created_at": base + 1000},
            {"mid": "s3", "gid": 100, "sender_id": 1, "sender_name": "甲",
             "text": "含通配符 50% 折扣", "created_at": base + 2000},
        ])
        conn.close()
        self.base = base
        self.port = _free_port()
        self.httpd = server.make_server("127.0.0.1", self.port, self.db_path)
        self.t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.t.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        os.remove(self.db_path)

    def _get_json(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        return resp.status, json.loads(body)

    def test_search_basic(self):
        from urllib.parse import quote
        path = f"/api/search?gid=100&q={quote('天气')}&days=90&limit=200"
        status, data = self._get_json(path)
        self.assertEqual(status, 200)
        mids = [r["mid"] for r in data["results"]]
        self.assertEqual(mids, ["s2", "s1"])  # 倒序
        # snippet 含关键词标记
        self.assertIn("天气", data["results"][0]["snippet"])

    def test_search_escapes_like_wildcards(self):
        # 搜 "50%"，% 应被转义为字面量，只匹配 s3
        from urllib.parse import quote
        path = f"/api/search?gid=100&q={quote('50%')}&days=90&limit=200"
        status, data = self._get_json(path)
        self.assertEqual(status, 200)
        mids = [r["mid"] for r in data["results"]]
        self.assertEqual(mids, ["s3"])

    def test_search_no_match(self):
        from urllib.parse import quote
        path = f"/api/search?gid=100&q={quote('不存在')}&days=90&limit=200"
        status, data = self._get_json(path)
        self.assertEqual(status, 200)
        self.assertEqual(data["results"], [])

    def test_search_days_filter(self):
        # days=0 → 下界=最新，只匹配最新那条
        from urllib.parse import quote
        path = f"/api/search?gid=100&q={quote('天气')}&days=0&limit=200"
        status, data = self._get_json(path)
        self.assertEqual(status, 200)
        mids = [r["mid"] for r in data["results"]]
        self.assertEqual(mids, ["s2"])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_server.SearchApiTest -v`
Expected: FAIL — 路由未实现

- [ ] **Step 3: 实现 `query_search`**

在 `server.py` 查询函数区增加：

```python
def _escape_like(s):
    """转义 LIKE 通配符 % _ \，配合 ESCAPE '\\' 使用。"""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _snippet(text, q, span=30):
    """截取关键词前后各 span 字，关键词用 \\x00/\\x01 包裹供前端转 <mark>。"""
    if not text:
        return ""
    idx = text.find(q)
    if idx < 0:
        return text[:span * 2]
    start = max(0, idx - span)
    end = min(len(text), idx + len(q) + span)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return (prefix + text[start:idx] + "\x00" + q + "\x01"
            + text[idx + len(q):end] + suffix)


def query_search(conn, gid, q, days, limit):
    if not q:
        return {"results": []}
    # 该群最新消息时间作为范围上界基准
    max_row = conn.execute(
        "SELECT MAX(created_at) AS mx FROM messages WHERE gid=?", (gid,)).fetchone()
    max_ts = max_row["mx"] if max_row and max_row["mx"] else 0
    min_ts = max_ts - days * 86400000
    like = "%" + _escape_like(q) + "%"
    rows = conn.execute(
        f"SELECT {MSG_COLUMNS} FROM messages WHERE gid=? "
        f"AND created_at >= ? AND text LIKE ? ESCAPE '\\' "
        f"ORDER BY created_at DESC, id DESC LIMIT ?",
        (gid, min_ts, like, limit)).fetchall()
    results = []
    for r in rows:
        m = row_to_msg(r)
        results.append({
            "mid": m["mid"],
            "sender_id": m["sender_id"],
            "sender_name": m["sender_name"] or str(m["sender_id"]),
            "created_at": m["created_at"],
            "text": m["text"],
            "snippet": _snippet(m["text"], q),
        })
    return {"results": results}
```

- [ ] **Step 4: 在 `_route_api` 增加路由**

```python
            elif path == "/api/search":
                gid = int(qs.get("gid", ["0"])[0])
                q = qs.get("q", [""])[0]
                days = int(qs.get("days", ["90"])[0])
                limit = int(qs.get("limit", ["200"])[0])
                self._send_json(query_search(conn, gid, q, days, limit))
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m unittest tests.test_server.SearchApiTest -v`
Expected: 4 个测试 PASS

- [ ] **Step 6: 全量回归**

Run: `python -m unittest tests.test_server -v`
Expected: 全部 PASS

- [ ] **Step 7: 提交**

```bash
git add server.py tests/test_server.py
git commit -m "feat: 搜索 API /api/search (LIKE)"
```

---

## Task 6: 前端骨架 — HTML 三栏布局 + CSS

**Files:**
- Create: `web/index.html`（覆盖占位）
- Create: `web/style.css`
- Create: `web/app.js`（占位空壳，Task 7+ 填充）

实现静态结构：顶栏（群下拉 / 搜索框 / 发送者下拉 / 状态）、左栏（日期跳转输入 + 日期列表容器）、右栏（可见范围指示 + 消息列表 + 顶/底哨兵）、搜索浮层（默认隐藏）。无 JS 逻辑，纯结构 + 样式。

- [ ] **Step 1: 写 `web/index.html`**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>微博群聊消息查看器</title>
  <link rel="stylesheet" href="/web/style.css">
</head>
<body>
  <div id="topbar">
    <select id="group-select" title="选择群"></select>
    <input id="search-input" type="search" placeholder="搜索关键词（最近3个月）…" autocomplete="off">
    <select id="sender-select" title="按发送者筛选"></select>
    <span id="status">加载中…</span>
  </div>

  <div id="main">
    <aside id="sidebar">
      <div id="date-jump">
        <input id="date-picker" type="date" title="跳转到日期">
      </div>
      <div id="date-list"></div>
    </aside>

    <section id="viewer">
      <div id="range-indicator"></div>
      <div id="sentinel-top"></div>
      <div id="message-list"></div>
      <div id="sentinel-bottom"></div>
      <div id="empty-hint" hidden></div>
    </section>
  </div>

  <!-- 搜索浮层 -->
  <div id="search-overlay" hidden>
    <div id="search-panel">
      <div id="search-panel-head">
        <span>搜索结果</span>
        <select id="search-range" title="搜索时间范围">
          <option value="7">最近1周</option>
          <option value="30">最近1个月</option>
          <option value="90" selected>最近3个月</option>
        </select>
        <button id="search-close" type="button">×</button>
      </div>
      <div id="search-status"></div>
      <div id="search-results"></div>
    </div>
  </div>

  <script src="/web/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: 写 `web/style.css`**

```css
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }
body { display: flex; flex-direction: column; height: 100vh; overflow: hidden; }

#topbar {
  display: flex; gap: 8px; align-items: center; padding: 8px 12px;
  background: #f5f5f5; border-bottom: 1px solid #ddd; flex-shrink: 0;
}
#topbar select, #topbar input { padding: 4px 8px; }
#search-input { flex: 0 1 320px; }
#status { margin-left: auto; color: #888; font-size: 13px; }

#main { flex: 1; display: flex; min-height: 0; }

#sidebar {
  width: 240px; flex-shrink: 0; border-right: 1px solid #ddd;
  display: flex; flex-direction: column; min-height: 0; background: #fafafa;
}
#date-jump { padding: 8px; border-bottom: 1px solid #eee; }
#date-list { overflow-y: auto; flex: 1; }

.month-group { margin: 0; }
.month-header {
  padding: 6px 12px; cursor: pointer; font-weight: 600; font-size: 13px;
  background: #eee; user-select: none; position: sticky; top: 0;
}
.month-header::before { content: "▸ "; }
.month-group.open .month-header::before { content: "▾ "; }
.month-days { display: none; }
.month-group.open .month-days { display: block; }

.date-item {
  padding: 5px 20px; cursor: pointer; font-size: 13px;
  display: flex; justify-content: space-between;
}
.date-item:hover { background: #e8f0fe; }
.date-item.active { background: #1a73e8; color: #fff; }
.date-item .count { color: #999; font-size: 11px; }
.date-item.active .count { color: #cfe3ff; }

#viewer { flex: 1; display: flex; flex-direction: column; min-width: 0; min-height: 0; }
#range-indicator {
  padding: 4px 16px; font-size: 12px; color: #888; background: #fafafa;
  border-bottom: 1px solid #eee; flex-shrink: 0;
}
#message-list { flex: 1; overflow-y: auto; padding: 8px 16px; }
#sentinel-top, #sentinel-bottom { height: 1px; }

.msg { margin: 4px 0; }
.msg-meta { font-size: 12px; color: #888; margin-bottom: 2px; }
.msg-meta .sender { font-weight: 600; color: #333; margin-right: 8px; }
.msg-body { padding: 6px 10px; background: #f0f0f0; border-radius: 6px;
  display: inline-block; max-width: 80%; word-break: break-word; white-space: pre-wrap; }
.msg-body a { color: #1a73e8; }

.msg-system {
  text-align: center; color: #999; font-size: 12px; margin: 8px 0;
}
.date-sep {
  text-align: center; color: #aaa; font-size: 11px; margin: 12px 0 4px;
}
.date-sep span { background: #fff; padding: 0 8px; }

.msg-highlight { animation: blink 0.5s ease-in-out 4; }
@keyframes blink {
  0%, 100% { background: #f0f0f0; }
  50% { background: #fff3a0; }
}

#empty-hint { text-align: center; color: #999; padding: 40px; }
.loading-more { text-align: center; color: #aaa; font-size: 12px; padding: 8px; }
.no-more { text-align: center; color: #ccc; font-size: 11px; padding: 8px; }

/* 搜索浮层 */
#search-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.3);
  display: flex; align-items: flex-start; justify-content: center; padding-top: 60px;
  z-index: 100;
}
#search-panel {
  background: #fff; border-radius: 8px; width: 600px; max-width: 90vw;
  max-height: 70vh; display: flex; flex-direction: column; box-shadow: 0 8px 30px rgba(0,0,0,0.2);
}
#search-panel-head {
  display: flex; align-items: center; gap: 8px; padding: 10px 14px;
  border-bottom: 1px solid #eee; font-weight: 600;
}
#search-panel-head span { flex: 1; }
#search-close { background: none; border: none; font-size: 20px; cursor: pointer; color: #888; }
#search-status { padding: 6px 14px; font-size: 13px; color: #888; border-bottom: 1px solid #f0f0f0; }
#search-results { overflow-y: auto; flex: 1; }
.search-result {
  padding: 10px 14px; border-bottom: 1px solid #f0f0f0; cursor: pointer;
}
.search-result:hover { background: #f5f9ff; }
.search-result .sr-meta { font-size: 12px; color: #888; margin-bottom: 4px; }
.search-result .sr-meta .sender { font-weight: 600; color: #333; margin-right: 8px; }
.search-result .sr-snippet { font-size: 13px; }
.search-result mark { background: #fff3a0; padding: 0 1px; }
```

- [ ] **Step 3: 写 `web/app.js` 占位**

```javascript
"use strict";
// 将在 Task 7+ 填充。先放一个全局 state 占位，避免 HTML 引用报错。
console.log("app.js loaded");
```

- [ ] **Step 4: 手动走查**

Run: `python server.py`，浏览器打开 `http://127.0.0.1:8765/`：
- 看到顶栏（空下拉 + 搜索框 + 空下拉 + 状态"加载中…"）
- 看到左栏（日期输入框 + 空列表）
- 看到右栏（空消息区）
- 控制台打印 `app.js loaded`，无报错

- [ ] **Step 5: 提交**

```bash
git add web/index.html web/style.css web/app.js
git commit -m "feat: 前端三栏布局骨架"
```

---

## Task 7: 前端核心 — 状态机 + 群/日期/发送者加载 + 选日期渲染

**Files:**
- Modify: `web/app.js`（全量替换占位）

实现：全局 `state`、API 封装、启动时加载群列表 → 默认选第一个群 → 加载该群日期列表 + 发送者列表 → 默认选最新日期 → 加载该日最新 500 条并渲染。消息按 media_type/msg_type 渲染（含系统消息居中、跨天分隔条、文本转义 + URL 链接化）。

- [ ] **Step 1: 写 `web/app.js` 核心**

全量替换 `web/app.js`：

```javascript
"use strict";

// ---------- 全局状态 ----------
const state = {
  gid: null,
  groups: [],
  dates: [],            // [{month:'YYYY-MM', days:[{date,count}], open:bool}]
  selectedDate: null,
  selectedSender: null, // sender_id 或 null
  senders: [],
  messages: [],         // 升序，最新在底
  before: null,         // {ts,id}
  after: null,          // {ts,id}
  hasMoreOlder: true,
  hasMoreNewer: true,
  loadingOlder: false,
  loadingNewer: false,
  reqId: 0,
};

const LIMIT = 500;

// ---------- DOM ----------
const $ = (id) => document.getElementById(id);
const elGroup = $("group-select");
const elSender = $("sender-select");
const elSearch = $("search-input");
const elStatus = $("status");
const elDateList = $("date-list");
const elDatePicker = $("date-picker");
const elMsgList = $("message-list");
const elRange = $("range-indicator");
const elEmpty = $("empty-hint");
const elSentinelTop = $("sentinel-top");
const elSentinelBottom = $("sentinel-bottom");

// ---------- API ----------
async function api(path) {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

// ---------- 工具 ----------
function escapeHtml(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, (c) => (
    {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function linkify(escaped) {
  // 在已转义的文本里把 URL 转链接（&amp; 已是实体，不误伤）
  return escaped.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
}

function fmtTime(ms) {
  // 与后端 CST(+8) 一致：按 UTC+8 取时分，避免依赖运行机器时区
  const d = new Date(ms + 8 * 3600 * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

function fmtDate(ms) {
  // 同样锚定 +8，取 YYYY-MM-DD
  const d = new Date(ms + 8 * 3600 * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())}`;
}

function cstDate(ms) {
  // 与后端一致：UTC ms + 8h 取 YYYY-MM-DD
  return fmtDate(ms);
}

// ---------- 消息渲染 ----------
function renderMessageBody(m) {
  const mt = m.media_type;
  const text = escapeHtml(m.text || "");
  const url = m.media_orig_url || "";
  const link = url ? ` <a href="${escapeHtml(url)}" target="_blank" rel="noopener">[链接]</a>` : "";
  if (m.msg_type !== 321 && m.msg_type !== 100) {
    // 系统消息（居中由外层处理），body 即文本
    return linkify(text);
  }
  if (mt === 0) return linkify(text);
  if (mt === 1) return `🖼 [图片]${link}`;
  if (mt === 5) return `📎 [文件]${link}`;
  if (mt === 10) return `🎬 [视频]${link}`;
  if (mt === 13) {
    if ((m.text || "").includes("红包")) return `🧧 [红包]${link}`;
    return `🎬 [视频]${link}`;
  }
  if (mt === 14) return `${linkify(text)} <span class="tag">[链接]</span>`;
  if (mt === 15) return `${linkify(text)} <span class="tag">[小程序]</span>`;
  return `${linkify(text)} <span class="tag">[未知媒体:${mt}]</span>`;
}

function isSystem(m) {
  return m.msg_type !== 321 && m.msg_type !== 100;
}

function messageEl(m, anchorMid) {
  if (isSystem(m)) {
    const div = document.createElement("div");
    div.className = "msg-system";
    div.dataset.mid = m.mid;
    div.dataset.date = cstDate(m.created_at);
    div.innerHTML = linkify(escapeHtml(m.text || ""));
    return div;
  }
  const div = document.createElement("div");
  div.className = "msg";
  div.dataset.mid = m.mid;
  div.dataset.date = cstDate(m.created_at);
  const meta = document.createElement("div");
  meta.className = "msg-meta";
  meta.innerHTML = `<span class="sender">${escapeHtml(m.sender_name || String(m.sender_id))}</span><span class="time">${fmtTime(m.created_at)}</span>`;
  const body = document.createElement("div");
  body.className = "msg-body";
  body.innerHTML = renderMessageBody(m);
  div.append(meta, body);
  if (anchorMid && m.mid === anchorMid) div.classList.add("msg-highlight");
  return div;
}

function dateSepEl(date) {
  const div = document.createElement("div");
  div.className = "date-sep";
  div.innerHTML = `<span>──── ${date} ────</span>`;
  return div;
}

function renderMessages(anchorMid) {
  // 清空旧消息但保留哨兵（哨兵在 Task 8 被移入 #message-list 内）
  // 先移除哨兵，清空，再把哨兵放回
  if (elSentinelTop.parentElement === elMsgList) elMsgList.removeChild(elSentinelTop);
  if (elSentinelBottom.parentElement === elMsgList) elMsgList.removeChild(elSentinelBottom);
  elMsgList.innerHTML = "";
  elMsgList.appendChild(elSentinelTop);
  let lastDate = null;
  for (const m of state.messages) {
    const d = cstDate(m.created_at);
    if (d !== lastDate) {
      elMsgList.appendChild(dateSepEl(d));
      lastDate = d;
    }
    elMsgList.appendChild(messageEl(m, anchorMid));
  }
  elMsgList.appendChild(elSentinelBottom);
  updateRangeIndicator();
  updateEmptyHint();
}

function updateRangeIndicator() {
  if (!state.messages.length) { elRange.textContent = ""; return; }
  const first = state.messages[0];
  const last = state.messages[state.messages.length - 1];
  elRange.textContent = `${fmtDate(first.created_at)} ${fmtTime(first.created_at)} → ${fmtDate(last.created_at)} ${fmtTime(last.created_at)}`;
}

function updateEmptyHint() {
  elEmpty.hidden = state.messages.length > 0;
  if (state.messages.length === 0) {
    elEmpty.textContent = state.gid ? "该范围内没有消息" : "请选择一个群";
  }
}

// ---------- 左栏日期列表 ----------
function renderDateList() {
  elDateList.innerHTML = "";
  for (const mg of state.dates) {
    const group = document.createElement("div");
    group.className = "month-group" + (mg.open ? " open" : "");
    const head = document.createElement("div");
    head.className = "month-header";
    const total = mg.days.reduce((s, d) => s + d.count, 0);
    head.textContent = `${mg.month} (${total})`;
    head.onclick = () => { mg.open = !mg.open; group.classList.toggle("open"); };
    const days = document.createElement("div");
    days.className = "month-days";
    for (const d of mg.days) {
      const item = document.createElement("div");
      item.className = "date-item" + (d.date === state.selectedDate ? " active" : "");
      item.dataset.date = d.date;
      const mmdd = d.date.slice(5);
      item.innerHTML = `<span>${mmdd}</span><span class="count">${d.count}</span>`;
      item.onclick = () => selectDate(d.date);
      days.appendChild(item);
    }
    group.append(head, days);
    elDateList.appendChild(group);
  }
}

function highlightDate(date) {
  // 展开对应月份并高亮
  for (const mg of state.dates) {
    if (mg.month === date.slice(0, 7)) mg.open = true;
  }
  state.selectedDate = date;
  renderDateList();
  const item = elDateList.querySelector(`.date-item[data-date="${date}"]`);
  if (item) item.scrollIntoView({ block: "nearest" });
}

// ---------- 数据加载 ----------
async function loadGroups() {
  state.groups = await api("/api/groups");
  elGroup.innerHTML = state.groups.map(g =>
    `<option value="${g.gid}">${escapeHtml(g.name)} (${g.msg_count})</option>`).join("");
}

async function loadSenders(gid) {
  state.senders = await api(`/api/senders?gid=${gid}`);
  elSender.innerHTML = `<option value="">全部发送者</option>` +
    state.senders.map(s => `<option value="${s.sender_id}">${escapeHtml(s.sender_name)} (${s.count})</option>`).join("");
}

async function loadDates(gid) {
  const data = await api(`/api/dates?gid=${gid}`);
  // 按月分组，倒序
  const byMonth = {};
  for (const d of data) {
    const m = d.date.slice(0, 7);
    if (!byMonth[m]) byMonth[m] = [];
    byMonth[m].push(d);
  }
  state.dates = Object.keys(byMonth).sort((a, b) => b.localeCompare(a)).map(m => ({
    month: m, days: byMonth[m], open: false,
  }));
  if (state.dates.length) state.dates[0].open = true; // 默认展开最近月
  renderDateList();
}

async function loadByDate(gid, date, senderId) {
  const myReq = ++state.reqId;
  elStatus.textContent = "加载中…";
  let params = `gid=${gid}&date=${encodeURIComponent(date)}&limit=${LIMIT}`;
  if (senderId) params += `&sender_id=${senderId}`;
  const data = await api(`/api/messages/by_date?${params}`);
  if (myReq !== state.reqId) return; // 已被新请求覆盖
  state.messages = data.messages;
  state.before = data.oldest;
  state.after = data.newest;
  state.hasMoreOlder = data.has_more_older;
  state.hasMoreNewer = data.has_more_newer;
  renderMessages(null);
  elStatus.textContent = `共 ${state.messages.length} 条`;
  // 滚到底（最新在底）
  elMsgList.scrollTop = elMsgList.scrollHeight;
}

// ---------- 选择操作 ----------
async function selectGroup(gid) {
  state.gid = gid;
  state.selectedSender = null;
  elSender.value = "";
  elStatus.textContent = "加载中…";
  await Promise.all([loadDates(gid), loadSenders(gid)]);
  // 默认选最新日期
  if (state.dates.length && state.dates[0].days.length) {
    await selectDate(state.dates[0].days[0].date);
  }
}

async function selectDate(date) {
  highlightDate(date);
  elDatePicker.value = date;
  await loadByDate(state.gid, date, state.selectedSender);
}

// ---------- 初始化 ----------
async function init() {
  await loadGroups();
  if (state.groups.length) {
    await selectGroup(state.groups[0].gid);
  } else {
    elStatus.textContent = "数据库中没有群";
  }
}

// 事件绑定
elGroup.onchange = () => selectGroup(parseInt(elGroup.value, 10));
elSender.onchange = () => {
  const v = elSender.value;
  state.selectedSender = v ? parseInt(v, 10) : null;
  if (state.selectedDate) loadByDate(state.gid, state.selectedDate, state.selectedSender);
};
elDatePicker.onchange = () => {
  if (elDatePicker.value) selectDate(elDatePicker.value);
};

init();
```

- [ ] **Step 2: 手动走查**

Run: `python server.py`，浏览器打开：
- 顶栏群下拉显示"茧房建筑师协会 (847715)"
- 左栏日期列表按月折叠，最近月展开，最新日期高亮
- 发送者下拉列出 1148 个发送者（按发言数倒序）
- 右栏显示最新日期的消息，最新在底，自动滚到底
- 文本消息显示气泡，系统消息居中灰字
- 跨天有日期分隔条
- 点左栏其他日期 → 右栏切换到那天最新 500 条
- 日期输入框选其他天 → 同上
- 切群 → 重置（仅 1 个群，验证不报错即可）

- [ ] **Step 3: 提交**

```bash
git add web/app.js
git commit -m "feat: 前端核心 群/日期/发送者加载与渲染"
```

---

## Task 8: 双向滚动加载 + 发送者筛选（滚动部分）

**Files:**
- Modify: `web/app.js`

发送者筛选已在 Task 7 绑定（重新查询）。本任务加双向滚动加载：用 IntersectionObserver 监听顶/底哨兵，触顶加载更早（before 游标，拼到头部、保持滚动位置），触底加载更新（after 游标，追加尾部）。

- [ ] **Step 1: 在 `web/app.js` 增加滚动加载逻辑**

在 `// ---------- 初始化 ----------` 之前插入：

```javascript
// ---------- 双向滚动加载 ----------
async function loadOlder() {
  if (!state.before || state.loadingOlder || !state.hasMoreOlder) return;
  state.loadingOlder = true;
  showLoadingMarker("top");
  const myReq = state.reqId;
  let params = `gid=${state.gid}&before_ts=${state.before.ts}&before_id=${state.before.id}&limit=${LIMIT}`;
  if (state.selectedSender) params += `&sender_id=${state.selectedSender}`;
  try {
    const data = await api(`/api/messages?${params}`);
    if (myReq !== state.reqId) return;
    // 保持滚动位置：记录旧 scrollHeight，插入后补偿
    const prevHeight = elMsgList.scrollHeight;
    state.messages = data.messages.concat(state.messages);
    state.before = data.oldest;
    state.hasMoreOlder = data.has_more_older;
    // 重新渲染（简单可靠，500 条开销可接受）
    renderMessages(null);
    elMsgList.scrollTop = elMsgList.scrollHeight - prevHeight;
  } catch (e) {
    elStatus.textContent = "加载更早失败：" + e.message;
  } finally {
    state.loadingOlder = false;
    showLoadingMarker(null);
  }
}

async function loadNewer() {
  if (!state.after || state.loadingNewer || !state.hasMoreNewer) return;
  state.loadingNewer = true;
  showLoadingMarker("bottom");
  const myReq = state.reqId;
  let params = `gid=${state.gid}&after_ts=${state.after.ts}&after_id=${state.after.id}&limit=${LIMIT}`;
  if (state.selectedSender) params += `&sender_id=${state.selectedSender}`;
  try {
    const data = await api(`/api/messages?${params}`);
    if (myReq !== state.reqId) return;
    const wasAtBottom = (elMsgList.scrollHeight - elMsgList.scrollTop - elMsgList.clientHeight) < 50;
    state.messages = state.messages.concat(data.messages);
    state.after = data.newest;
    state.hasMoreNewer = data.has_more_newer;
    renderMessages(null);
    if (wasAtBottom) elMsgList.scrollTop = elMsgList.scrollHeight;
  } catch (e) {
    elStatus.textContent = "加载更新失败：" + e.message;
  } finally {
    state.loadingNewer = false;
    showLoadingMarker(null);
  }
}

let loadingMarkerTop = null, loadingMarkerBottom = null;
function showLoadingMarker(pos) {
  if (pos === "top") {
    if (!loadingMarkerTop) {
      loadingMarkerTop = document.createElement("div");
      loadingMarkerTop.className = "loading-more";
      loadingMarkerTop.textContent = "加载更早…";
    }
    if (loadingMarkerTop.parentElement !== elMsgList) elMsgList.insertBefore(loadingMarkerTop, elMsgList.firstChild);
  } else if (pos === "bottom") {
    if (!loadingMarkerBottom) {
      loadingMarkerBottom = document.createElement("div");
      loadingMarkerBottom.className = "loading-more";
      loadingMarkerBottom.textContent = "加载更新…";
    }
    if (loadingMarkerBottom.parentElement !== elMsgList) elMsgList.appendChild(loadingMarkerBottom);
  } else {
    if (loadingMarkerTop && loadingMarkerTop.parentElement) loadingMarkerTop.remove();
    if (loadingMarkerBottom && loadingMarkerBottom.parentElement) loadingMarkerBottom.remove();
  }
}

function setupSentinels() {
  const obsTop = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting) loadOlder();
  }, { root: elMsgList, rootMargin: "50px" });
  obsTop.observe(elSentinelTop);
  const obsBottom = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting) loadNewer();
  }, { root: elMsgList, rootMargin: "50px" });
  obsBottom.observe(elSentinelBottom);
}
```

注意：哨兵 `#sentinel-top`/`#sentinel-bottom` 在 HTML 中位于 `#message-list` **之外**（Task 6 的结构）。为让 IntersectionObserver 的 `root` 生效，需把它们移入消息列表内。修改 `setupSentinels` 末尾：把哨兵 DOM 移入 `elMsgList`：

在 `setupSentinels` 函数内 observe 之前加：

```javascript
  // 把哨兵移入消息列表，使 root:elMsgList 生效
  if (elSentinelTop.parentElement !== elMsgList) elMsgList.insertBefore(elSentinelTop, elMsgList.firstChild);
  if (elSentinelBottom.parentElement !== elMsgList) elMsgList.appendChild(elSentinelBottom);
```

- [ ] **Step 2: 在 `init()` 末尾调用 `setupSentinels()`**

修改 `init()`，在 `selectGroup` 之后加：

```javascript
async function init() {
  setupSentinels();
  await loadGroups();
  if (state.groups.length) {
    await selectGroup(state.groups[0].gid);
  } else {
    elStatus.textContent = "数据库中没有群";
  }
}
```

- [ ] **Step 3: 手动走查**

Run: `python server.py`，浏览器：
- 右栏初始是最新日期最新 500 条，滚到底部
- 向上滚到顶 → 自动加载更早 500 条，滚动位置不跳（仍在原消息附近）
- 持续向上 → 跨天分隔条出现，继续加载
- 选一个较早的日期（消息多的天），向下滚到底 → 加载更新 500 条
- 选发送者筛选 → 右栏重新加载该发送者消息，上下滚只翻该发送者的消息
- 清空发送者筛选 → 恢复全部

- [ ] **Step 4: 提交**

```bash
git add web/app.js
git commit -m "feat: 双向滚动加载（游标分页）"
```

---

## Task 9: 搜索浮层 + 跳转上下文 + 高亮

**Files:**
- Modify: `web/app.js`

实现：搜索框回车 → 打开浮层 → 调 `/api/search` → 渲染结果列表（snippet 里 `\x00/\x01` 转 `<mark>`）→ 点结果 → 调 `/api/messages/around` → 右栏替换视图、高亮命中、滚到命中、左栏日期同步。

- [ ] **Step 1: 在 `web/app.js` 增加搜索逻辑**

在 `// ---------- 双向滚动加载 ----------` 之前插入：

```javascript
// ---------- 搜索 ----------
const elOverlay = $("search-overlay");
const elSearchRange = $("search-range");
const elSearchStatus = $("search-status");
const elSearchResults = $("search-results");
const elSearchClose = $("search-close");

function openSearch() {
  elOverlay.hidden = false;
  elSearchInput_focus();
}

function closeSearch() {
  elOverlay.hidden = true;
}

function elSearchInput_focus() { elSearch.focus(); }

function snippetToHtml(snippet) {
  // \x00..\x01 包裹关键词 → <mark>
  const esc = escapeHtml(snippet);
  return esc.replace(/\x00/g, "<mark>").replace(/\x01/g, "</mark>");
}

async function doSearch() {
  const q = elSearch.value.trim();
  if (!q) return;
  const days = parseInt(elSearchRange.value, 10);
  elSearchStatus.textContent = "搜索中…";
  elSearchResults.innerHTML = "";
  try {
    const data = await api(`/api/search?gid=${state.gid}&q=${encodeURIComponent(q)}&days=${days}&limit=200`);
    const results = data.results || [];
    if (!results.length) {
      elSearchStatus.textContent = "未找到匹配消息";
      return;
    }
    elSearchStatus.textContent = `共 ${results.length} 条结果` + (results.length >= 200 ? "（已达上限，请缩小范围）" : "");
    elSearchResults.innerHTML = "";
    for (const r of results) {
      const div = document.createElement("div");
      div.className = "search-result";
      div.innerHTML = `<div class="sr-meta"><span class="sender">${escapeHtml(r.sender_name)}</span><span>${fmtDate(r.created_at)} ${fmtTime(r.created_at)}</span></div><div class="sr-snippet">${snippetToHtml(r.snippet)}</div>`;
      div.onclick = () => jumpToMessage(r.mid);
      elSearchResults.appendChild(div);
    }
  } catch (e) {
    elSearchStatus.textContent = "搜索失败：" + e.message;
  }
}

async function jumpToMessage(mid) {
  closeSearch();
  const myReq = ++state.reqId;
  elStatus.textContent = "定位中…";
  const data = await api(`/api/messages/around?gid=${state.gid}&mid=${encodeURIComponent(mid)}&limit=${LIMIT}`);
  if (myReq !== state.reqId) return;
  state.messages = data.messages;
  state.before = data.oldest;
  state.after = data.newest;
  state.hasMoreOlder = data.has_more_older;
  state.hasMoreNewer = data.has_more_newer;
  renderMessages(mid);
  // 滚到命中消息
  const target = elMsgList.querySelector(`[data-mid="${CSS.escape(mid)}"]`);
  if (target) target.scrollIntoView({ block: "center" });
  // 左栏同步到命中消息所在日
  if (state.messages.length) {
    // 找命中消息的日期
    const hit = state.messages.find(m => m.mid === mid) || state.messages[state.messages.length - 1];
    highlightDate(cstDate(hit.created_at));
  }
  elStatus.textContent = `已定位，共 ${state.messages.length} 条`;
}

// 事件绑定
elSearch.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); openSearch(); doSearch(); }
});
elSearchRange.onchange = doSearch;
elSearchClose.onclick = closeSearch;
elOverlay.addEventListener("click", (e) => { if (e.target === elOverlay) closeSearch(); });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !elOverlay.hidden) closeSearch();
});
```

- [ ] **Step 2: 手动走查**

Run: `python server.py`，浏览器：
- 搜索框输入一个常见词（如"天气""哈哈"）回车 → 浮层弹出，列出结果
- 结果项有发送者、时间、snippet（关键词黄底高亮）
- 顶部范围下拉切"最近1周" → 重新搜索
- 点某条结果 → 浮层关闭，右栏跳到该消息，居中显示并黄闪 4 次
- 左栏日期高亮更新为命中消息那天（对应月份自动展开）
- 命中消息上下可继续滚动加载前后文
- 搜不存在的词 → "未找到匹配消息"
- Esc / 点遮罩 → 关闭浮层
- 搜含 `%` 的词 → 不报错（LIKE 转义生效）

- [ ] **Step 3: 提交**

```bash
git add web/app.js
git commit -m "feat: 搜索浮层与跳转上下文高亮"
```

---

## Task 10: 端到端走查与收尾

**Files:**
- Modify: `README.md`（补充查看器使用说明）
- Modify: `run.bat`（可选，补充启动查看器）

无新代码，做全链路验证、补文档、确认所有测试通过。

- [ ] **Step 1: 全量单测**

Run: `python -m unittest tests.test_server -v`
Expected: 全部 PASS（骨架 4 + 元数据 3 + 游标 6 + 锚点 5 + 搜索 4 = 22 个）

- [ ] **Step 2: 端到端走查清单**

Run: `python server.py`，逐项验证：

- [ ] 打开 `http://127.0.0.1:8765/`，群下拉显示"茧房建筑师协会 (847715)"
- [ ] 左栏按月折叠，最近月展开，最新日期高亮，每天显示消息数
- [ ] 右栏显示最新日期最新 500 条，最新在底，自动滚到底
- [ ] 文本气泡正常，系统消息居中灰字，跨天有分隔条
- [ ] 图片消息显示 `🖼 [图片] [链接]`，链接可点（会因 cookie 失败，符合预期）
- [ ] 向上滚到顶 → 自动加载更早 500 条，滚动位置不跳
- [ ] 向下滚到底 → 加载更新 500 条
- [ ] 点左栏其他日期 → 右栏切换到那天最新 500 条，左栏高亮更新
- [ ] 日期输入框选某天 → 同上
- [ ] 发送者下拉选某人 → 右栏只显示该人消息，上下翻只翻该人
- [ ] 清空发送者 → 恢复全部
- [ ] 搜索框输词回车 → 浮层列出结果，snippet 关键词高亮
- [ ] 切搜索范围 → 重新搜
- [ ] 点搜索结果 → 跳转，命中消息居中黄闪，左栏日期同步
- [ ] 命中后上下滚可翻前后文
- [ ] Esc / 点遮罩关浮层
- [ ] 搜含 `%` 的词不报错

- [ ] **Step 3: 补充 README**

在 `README.md` 末尾追加一节：

```markdown
## 消息查看器

本地只读 web 查看器，浏览已抓取的群聊消息。

### 启动

\`\`\`bash
python server.py
\`\`\`

默认访问 http://127.0.0.1:8765 。可选参数：`--db`（数据库路径）、`--host`、`--port`。

### 功能

- 左栏按月折叠的日期列表，点某天查看当天消息（最新在底）
- 右栏聊天视图，向上/向下滚动加载更早/更新消息（每页 500 条）
- 顶栏发送者筛选（重新查询，仅看某人消息）
- 关键词模糊搜索（LIKE，最近 3 个月范围），点结果跳转到上下文并翻看
- 媒体仅显示占位与原始链接（需带 cookie 才能访问）

### 测试

\`\`\`bash
python -m unittest discover tests
\`\`\`
```

- [ ] **Step 4: 提交**

```bash
git add README.md
git commit -m "docs: 补充消息查看器使用说明"
```

- [ ] **Step 5: 最终确认**

Run: `python -m unittest discover tests -v`
Expected: 全部 PASS。项目可 `python server.py` 正常启动使用。

---

## 自审记录

**1. Spec 覆盖：**
- §2 架构与文件布局 → Task 1（server 骨架）+ Task 6（前端骨架）
- §2.2 七个 API → Task 2（groups/dates/senders）+ Task 3（messages）+ Task 4（by_date/around）+ Task 5（search）✓
- §3 游标分页 → Task 3（双向游标 + tiebreaker 测试）✓
- §3.4 初始锚点 → Task 4（by_date）✓
- §3.5 跳转查询 → Task 4（around）✓
- §4 搜索浮层 → Task 5（后端）+ Task 9（前端）✓
- §5 消息渲染 → Task 7（renderMessageBody / isSystem / 分隔条 / 转义链接化）✓
- §6 布局与交互 → Task 6（布局）+ Task 7（选日期）+ Task 8（滚动）✓
- §6.3 左栏高亮规则 → Task 7（highlightDate 仅选日期/跳转时更新）+ Task 9（跳转同步）✓
- §7 状态机/竞态/错误 → Task 7（reqId）+ Task 8（loading 标志 + try/catch）✓
- §7.6 测试 → Task 1-5 后端 unittest，Task 10 走查清单 ✓

**2. 占位符扫描：** 无 TBD/TODO，所有步骤含完整代码或完整命令。

**3. 类型一致性：**
- `row_to_msg` 字段在 Task 3 定义，Task 4/5 复用一致 ✓
- `_build_response` 响应结构（messages/oldest/newest/has_more_older/has_more_newer）在 Task 3/4 一致，Task 4 around 额外加 `anchor_mid` ✓
- 前端 `state.before/after` 结构 `{ts,id}` 与后端 `oldest/newest` 一致 ✓
- API 路径前后端一致：`/api/messages/by_date`、`/api/messages/around`、`/api/search` ✓
- `cstDate` 前端与后端 `date(datetime(...,'+8 hours'))` 口径一致 ✓

**4. 已知简化（计划内，非缺陷）：**
- 前端加载更早时全量 `renderMessages` 重渲染（非增量 DOM）。500 条重渲染开销可接受，换来实现简单与滚动位置可控。若实测卡顿可在后续优化为增量插入。
- `loadOlder`/`loadNewer` 用 `state.reqId` 防竞态，但未阻止"同一方向连续触发"。IntersectionObserver 的 `rootMargin` + `loading` 标志已足够防抖。
