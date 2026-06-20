# 前端 UX 三处修复 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复消息查看器前端三处 UX 问题：点日期后稳定触发下拉加载、统一媒体消息 `[链接]` 字号、搜索框清除按钮一致。

**Architecture:** 纯前端改动，涉及 `web/app.js`、`web/index.html`、`web/style.css` 三个文件。问题 1 在 `loadByDate` 末尾显式调用 `loadNewer()` 取代依赖观察者异步触发；问题 2 把 `[链接]` 统一用 `.tag` 包裹并补 `.tag a` 防护样式；问题 3 把 `search-sender` 改为 `type="search"` 并补 `appearance:none`。三处改动相互独立，无共享状态。

**Tech Stack:** 原生 JS（无框架）、HTML、CSS。无前端自动化测试框架，验证以手动浏览器验证为主，辅以后端 `pytest` 回归。

**Spec:** `docs/superpowers/specs/2026-06-20-frontend-ux-fixes-design.md`

**前置条件：** 已在 `feat/ux-fixes` 分支上（基于最新 master）。工作区干净。

---

### Task 1: 点日期后显式触发下拉加载

**Files:**
- Modify: `web/app.js:263-278`（`loadByDate` 函数）

**说明：** 当前 `loadByDate` 滚到底后依赖底部 `IntersectionObserver` 异步触发 `loadNewer()`，但 `renderMessages` 会移除再重新挂载底部哨兵，观察者回调时机不稳定，导致点日期后时灵时不灵地触发下拉加载。改为滚到底后显式调用 `loadNewer()`，仅当 `hasMoreNewer` 为真时。`loadNewer` 内部的 `loadingNewer`/`hasMoreNewer` 同步守卫保证不会与观察者触发的调用重复请求（详见 spec 防重复说明）。

- [ ] **Step 1: 修改 `loadByDate` 末尾，显式调用 `loadNewer`**

在 `web/app.js` 中，把 `loadByDate` 函数末尾的：

```js
  renderMessages(null);
  // 滚到底（最新在底）
  elMsgList.scrollTop = elMsgList.scrollHeight;
  elStatus.textContent = "";
}
```

替换为：

```js
  renderMessages(null);
  // 滚到底（最新在底）
  elMsgList.scrollTop = elMsgList.scrollHeight;
  elStatus.textContent = "";
  // 滚到底后，若有更新内容则立即显式加载下一页，便于用户直接下滑查看。
  // 不依赖底部 IntersectionObserver 异步触发——renderMessages 会移除并重新
  // 挂载底部哨兵，观察者回调时机不稳定。loadNewer 内部有 loadingNewer/
  // hasMoreNewer 同步守卫，与观察者触发的调用互斥，不会重复请求。
  if (state.hasMoreNewer) loadNewer();
}
```

- [ ] **Step 2: 手动验证——有后续消息的日期**

启动服务器（若未运行）：`python server.py`，浏览器打开 `http://127.0.0.1:8765`。
选择一个群，在左栏选一个**非最新**的日期（即该日期之后还有其它日期有消息）。
打开浏览器开发者工具 Network 面板，确认：
1. 点击日期后先出现 `/api/messages/by_date?...` 请求。
2. 紧接着（by_date 返回后）自动出现一次 `/api/messages?...&after_ts=...` 请求。
3. 消息列表滚动位置停在底部附近，不跳动；底部追加了新内容。
4. 上述 after_ts 请求**只出现一次**（不重复）。

- [ ] **Step 3: 手动验证——最新日期无后续消息**

选择该群**最新**的日期（左栏最顶部的日期，当天之后无消息）。
确认：点击日期后只有 `/api/messages/by_date?...` 请求，**不**出现 after_ts 请求（`hasMoreNewer` 为 false，不调用 `loadNewer`）。

- [ ] **Step 4: 手动验证——级联预加载不重复**

回到非最新日期，确认 after_ts 请求完成后，若底部哨兵仍在观察者触发区（新追加内容不足一屏），会再出现**一次** after_ts 请求但 `after_ts` 值不同（游标已前进，取下一页，非同一批）。这是预期行为（spec 级联说明），非 bug。

- [ ] **Step 5: 提交**

```bash
git add web/app.js
git commit -m "fix: 点日期后显式触发下拉加载，避免观察者时序不稳"
```

---

### Task 2: 统一媒体消息 `[链接]` 字号为 12px

**Files:**
- Modify: `web/app.js:92`（`renderMessageBody` 的 `link` 变量）
- Modify: `web/style.css:64`（`.tag` 规则后新增 `.tag a` 防护规则）

**说明：** `renderMessageBody` 中 `link` 变量为裸 `<a>[链接]</a>`，继承 `.msg-body` 16px；而 mt 14/15/默认分支用 `<span class="tag">[链接]</span>` 为 12px。同一标签两种字号。把 `link` 改为 `.tag` 包裹，并补 `.tag a { font-size: inherit; color: inherit; }` 防止链接默认样式覆盖字号。

- [ ] **Step 1: 修改 `link` 变量，用 `.tag` 包裹**

在 `web/app.js` 的 `renderMessageBody` 函数中，把第 92 行：

```js
  const link = url ? ` <a href="${escapeHtml(url)}" target="_blank" rel="noopener">[链接]</a>` : "";
```

替换为：

```js
  const link = url
    ? ` <span class="tag"><a href="${escapeHtml(url)}" target="_blank" rel="noopener">[链接]</a></span>`
    : "";
```

- [ ] **Step 2: 在 `style.css` 新增 `.tag a` 防护规则**

在 `web/style.css` 中，找到：

```css
.tag { color: #1a73e8; font-size: 12px; margin-left: 4px; }
```

在其后新增一行：

```css
.tag a { font-size: inherit; color: inherit; }
```

- [ ] **Step 3: 手动验证——各 media_type 的 `[链接]` 字号一致**

浏览器刷新页面。选择含不同类型媒体消息的群（图片、文件、视频、链接、小程序等）。
对每条带 `[链接]` 的媒体消息，用开发者工具 Elements 面板选中 `[链接]` 元素，确认 Computed 的 `font-size` 均为 `12px`：
1. 图片 fallback（mt 1 无 fid）`🖼 [图片] [链接]` 中的 `[链接]` → 12px。
2. 文件（mt 5）`📎 [文件] [链接]` 中的 `[链接]` → 12px。
3. 视频 fallback（mt 10 无 fid）`🎬 [视频] [链接]` 中的 `[链接]` → 12px。
4. 链接（mt 14）`... [链接]` 中的 `[链接]` → 12px。
5. 小程序（mt 15）`[小程序]` 标签 → 12px（本就如此，确认未受影响）。

确认 `[链接]` 仍可点击跳转（`<a>` 保留 href）。

- [ ] **Step 4: 提交**

```bash
git add web/app.js web/style.css
git commit -m "fix: 统一媒体消息 [链接] 字号为 12px .tag"
```

---

### Task 3: 搜索框统一 `type="search"` 清除按钮

**Files:**
- Modify: `web/index.html:42`（`search-sender` 的 `type` 属性）
- Modify: `web/style.css:107`（`.search-fields input` 规则补 `appearance`）

**说明：** `search-keyword` 是 `type="search"` 有原生 ✕，`search-sender` 是 `type="text"` 无 ✕。把 `search-sender` 改为 `type="search"`，并给 `.search-fields input` 补 `-webkit-appearance: none; appearance: none;` 消除 `type=search` 的原生框体装饰差异（不影响原生 ✕ 按钮，✕ 由 `::-webkit-search-cancel-button` 控制）。

- [ ] **Step 1: 把 `search-sender` 改为 `type="search"`**

在 `web/index.html` 中，把：

```html
        <input id="search-sender" type="text" placeholder="发送者名称（精确匹配，可选）" autocomplete="off">
```

替换为：

```html
        <input id="search-sender" type="search" placeholder="发送者名称（精确匹配，可选）" autocomplete="off">
```

- [ ] **Step 2: 给 `.search-fields input` 补 `appearance` 属性**

在 `web/style.css` 中，找到：

```css
.search-fields input { padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; }
```

替换为：

```css
.search-fields input { padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; -webkit-appearance: none; appearance: none; }
```

- [ ] **Step 3: 手动验证——两框均有 ✕ 且外观一致**

浏览器刷新页面，点击"🔍 高级搜索"打开浮层。
1. 在"发送者名称"框输入文字 → 确认出现原生 ✕ 清除按钮，点击 ✕ 清空内容。
2. 在"关键词"框输入文字 → 确认出现原生 ✕，点击 ✕ 清空。
3. 两框外观（圆角、内边距、边框）一致，无原生装饰差异。
4. 两框回车仍可触发搜索（Enter 绑定未受影响）。

- [ ] **Step 4: 提交**

```bash
git add web/index.html web/style.css
git commit -m "fix: 搜索发送者框改 type=search 统一清除按钮"
```

---

### Task 4: 后端回归测试

**Files:**
- 无修改，仅运行现有测试套件确认未受影响。

**说明：** 本次为纯前端改动，后端 `server.py` 与 `tests/` 未动。运行后端测试确认全绿，排除意外回归。

- [ ] **Step 1: 运行后端测试**

Run: `python -m pytest tests/ -v`
Expected: 全部测试通过（32 项）。若有失败，确认是否与本分支改动相关（应无关，因后端未改）。

- [ ] **Step 2: 确认工作区干净**

Run: `git status`
Expected: `nothing to commit, working tree clean`（所有改动已在前述任务提交）。

---

## Self-Review

**1. Spec coverage:**
- 问题 1（点日期显式触发下拉加载）→ Task 1 ✓
- 问题 2（统一 `[链接]` 12px .tag）→ Task 2 ✓
- 问题 3（搜索框 type=search）→ Task 3 ✓
- spec"测试策略"中的后端回归 → Task 4 ✓
- spec"防重复与级联加载说明"→ Task 1 Step 2/4 验证项覆盖 ✓

**2. Placeholder scan:** 无 TBD/TODO，每个步骤均有具体代码或具体验证动作。

**3. Type/名称一致性:**
- `loadNewer` / `state.hasMoreNewer` / `state.loadingNewer` 在 spec 与 Task 1 中一致 ✓
- `link` 变量、`.tag` / `.tag a` 类名在 spec 与 Task 2 中一致 ✓
- `search-sender` / `.search-fields input` / `appearance` 在 spec 与 Task 3 中一致 ✓

无问题。
