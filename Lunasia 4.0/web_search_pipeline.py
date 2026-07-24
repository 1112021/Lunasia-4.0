# -*- coding: utf-8 -*-
"""
联网检索流水线：意图识别 → 多 query 并行 SERP → LLM 筛选 → 选择性深读 → 上下文包。
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse, urlunparse

# 明显垃圾/跳转壳域名（仅规则过滤，不做语义）
_JUNK_HOST_SUBSTRINGS = (
    "bing.com/aclick",
    "google.com/aclk",
    "doubleclick.net",
    "googleadservices.com",
)


@dataclass
class SearchBundle:
    """检索结果包，供主 Agent / Framework 使用。"""

    user_input: str
    status: str = "ok"  # ok | partial | empty | skipped
    intent: Dict[str, Any] = field(default_factory=dict)
    queries: List[str] = field(default_factory=list)
    selected_items: List[Dict[str, Any]] = field(default_factory=list)
    browse_results: List[Dict[str, Any]] = field(default_factory=list)
    context_text: str = ""
    short_summary: str = ""

    def to_context_text(self) -> str:
        return self.context_text or ""

    def short_summary_for_framework(self) -> str:
        return self.short_summary or "联网检索未返回可用结果。"


def _today_label() -> str:
    return date.today().isoformat()


def _llm_text_call(
    base_agent,
    config_key: str,
    messages: List[dict],
    *,
    max_tokens: int = 512,
    temperature: float = 0.1,
    task_label: str = "",
) -> str:
    from llm_router import chat_completion

    text = chat_completion(
        base_agent.config,
        config_key=config_key,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        task_label=task_label or config_key,
    )
    return (text or "").strip()


def _parse_json_object(text: str) -> Dict[str, Any]:
    if not text or not text.strip():
        raise ValueError("empty response")
    raw = text.strip()
    if "```json" in raw:
        raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in raw:
        raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
    raw = re.sub(r"^```\w*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(raw)):
            ch = raw[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    data = json.loads(raw[start : i + 1])
                    if isinstance(data, dict):
                        return data
    raise json.JSONDecodeError("no JSON object found", raw, 0)


def _extract_search_subject(user_input: str) -> str:
    text = (user_input or "").strip()
    if not text:
        return ""
    patterns = (
        r"^(?:请)?(?:结合|使用|通过|借助)?(?:联网)?(?:搜索|检索)(?:一下)?[，,：:\s]+",
        r"^(?:请)?(?:帮我|帮忙)?(?:搜索|查一下|查询|检索)[一下]?[，,：:\s]*",
        r"^(?:请)?(?:介绍一下|介绍)[一下]?[，,：:\s]*",
    )
    for pat in patterns:
        text = re.sub(pat, "", text, count=1, flags=re.IGNORECASE)
    return text.strip() or (user_input or "").strip()


def _looks_like_instruction(query: str) -> bool:
    q = (query or "").strip()
    if not q:
        return True
    if len(q) > 100:
        return True
    markers = (
        "结合联网",
        "联网搜索",
        "帮我",
        "介绍一下",
        "请搜索",
        "搜索一下",
    )
    return any(m in q for m in markers)


def _fallback_queries(
    user_input: str, supplement_query: str, *, max_q: int
) -> List[str]:
    out: List[str] = []
    supplement = (supplement_query or "").strip()
    if supplement:
        out.append(supplement)
    subject = _extract_search_subject(user_input)
    if subject and subject not in out:
        out.append(subject)
    if not out:
        out.append((user_input or "").strip())
    deduped: List[str] = []
    seen = set()
    for q in out:
        if q and q not in seen:
            seen.add(q)
            deduped.append(q)
    return deduped[:max_q]


def recognize_web_search_intent(
    base_agent,
    user_input: str,
    conversation_context: str = "",
) -> Dict[str, Any]:
    """Step 0：仅 LLM 判断是否需要联网检索（不用关键词规则）。"""
    default = {
        "need_search": False,
        "search_profile": "fact",
        "must_include_entities": [],
        "reason": "意图识别失败，默认不检索",
        "ok": False,
    }
    prompt = f"""你是联网检索门控助手。仅根据用户是否需要**外部时效/事实/资料**判断，不要用关键词表。

当前日期（仅供判断时效，勿写入搜索词）：{_today_label()}

用户输入：{user_input}

近期对话：
{conversation_context or '无'}

请只输出 JSON：
{{
  "need_search": true,
  "search_profile": "fact",
  "must_include_entities": ["实体1"],
  "reason": "一句话理由"
}}

说明：
- need_search 只能是 true 或 false（JSON 布尔值，不要写中文）
- search_profile 只能是 news、fact、howto、compare 之一
- reason 尽量短，不要换行，不要引号
- 纯聊天、代码、已有文件/屏幕内容、打开网站、待办 → need_search false
- 需要查新闻、价格、人物近况、政策、未掌握的事实 → need_search true
"""
    try:
        raw = _llm_text_call(
            base_agent,
            "search_intent_model",
            [
                {"role": "system", "content": "只输出合法 JSON，无 markdown。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=384,
            temperature=0.0,
            task_label="web_search_intent",
        )
        if not raw:
            raise ValueError("empty response")
        data = _parse_json_object(raw)
        return {
            "need_search": bool(data.get("need_search", False)),
            "search_profile": str(data.get("search_profile", "fact")),
            "must_include_entities": list(data.get("must_include_entities") or []),
            "reason": str(data.get("reason", "")),
            "ok": True,
        }
    except Exception as e:
        print(f"⚠️ 联网意图识别失败: {e}")
        return default


def format_intent_hint_for_planner(intent: Dict[str, Any]) -> str:
    if not intent.get("ok"):
        return "\n【联网意图】意图识别未完成；若需外部资料可安排 search_web + pass_to_main_agent，否则勿重复 search_web。\n"
    ns = intent.get("need_search", False)
    ents = intent.get("must_include_entities") or []
    profile = intent.get("search_profile", "fact")
    reason = intent.get("reason", "")
    lines = [
        "\n【联网意图识别】",
        f"- need_search: {ns}",
        f"- search_profile: {profile}",
        f"- reason: {reason}",
    ]
    if ents:
        lines.append(f"- 关键实体: {', '.join(ents)}")
    if ns:
        lines.append(
            "- 建议：安排 search_web（一次即可）+ pass_to_main_agent；勿安排多个 search_web。"
        )
    else:
        lines.append(
            "- 建议：无需 search_web；简单对话或本地工具即可，最后 pass_to_main_agent。"
        )
    return "\n".join(lines) + "\n"


def _generate_search_queries(
    base_agent,
    user_input: str,
    supplement_query: str,
    conversation_context: str,
    intent: Dict[str, Any],
    config: Dict[str, Any],
) -> List[str]:
    max_q = int(config.get("max_search_questions", 3))
    max_q = max(1, min(6, max_q))
    supplement = (supplement_query or "").strip()
    if supplement and not config.get("use_ai_query_extraction", True):
        return _fallback_queries(user_input, supplement_query, max_q=max_q)

    entities = intent.get("must_include_entities") or []
    prompt = f"""你是搜索 query 生成助手。根据用户问题生成 {max_q} 条**相互补充**的独立搜索 query（可直接用于搜索引擎）。

当前日期（仅供判断时效；**禁止**把完整日期或过时年份写进 query；需要时用「最新」「今年」「近期」）: {_today_label()}

用户原问题：{user_input}
框架指定核心 query（若不为「无」则第一条必须原样使用）：{supplement or '无'}
近期对话：
{conversation_context or '无'}
关键实体（须在 query 中体现）：{', '.join(entities) if entities else '无'}

规则：
1. 每条 query 应是短关键词短语，可直接用于 Bing/Google，不要整句对话
2. 禁止把「结合联网搜索」「帮我介绍」等指令词写进 query
3. 禁止「XX 知乎」「XX 百科」等站名后缀，除非用户明确要求
4. 不要引入对话中未出现的实体
5. 每行一条，不要编号

只输出 query 列表："""
    try:
        text = _llm_text_call(
            base_agent,
            "ai_query_extraction_model",
            [
                {"role": "system", "content": "只输出搜索 query，每行一条。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=400,
            temperature=0.2,
            task_label="web_search_queries",
        )
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        lines = [re.sub(r"^\d+[\.\)、]\s*", "", ln) for ln in lines]
        lines = [ln for ln in lines if not _looks_like_instruction(ln)]
        if supplement:
            lines = [supplement] + [ln for ln in lines if ln != supplement]
        lines = lines[:max_q]
        if lines:
            return lines
    except Exception as e:
        print(f"⚠️ 生成搜索 query 失败: {e}")
    return _fallback_queries(user_input, supplement_query, max_q=max_q)


def _normalize_url(url: str) -> str:
    try:
        p = urlparse(url.strip())
        if p.scheme not in ("http", "https"):
            return ""
        host = (p.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = p.path.rstrip("/") or ""
        return urlunparse((p.scheme, host, path, "", "", ""))
    except Exception:
        return ""


def _is_junk_url(url: str, title: str) -> bool:
    if not url or not url.startswith("http"):
        return True
    if not (title or "").strip():
        return True
    low = url.lower()
    for sub in _JUNK_HOST_SUBSTRINGS:
        if sub in low:
            return True
    return False


def _dedupe_serp_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for it in items:
        url = _normalize_url(it.get("url", ""))
        if not url or url in seen:
            continue
        if _is_junk_url(url, it.get("title", "")):
            continue
        seen.add(url)
        out.append({**it, "url": url})
    return out


def _fetch_serp_parallel(
    queries: List[str],
    config: Dict[str, Any],
    status_cb: Optional[Callable[[str], None]] = None,
) -> tuple:
    per_query = int(config.get("serp_results_per_query", 5))
    method = config.get("search_method", "Playwright")
    engine = config.get("search_engine", "Bing")
    engine_key = engine.lower()
    if engine_key == "duckduckgo":
        engine_key = "bing"
    timeout_q = 20.0
    all_items = []
    partial = False

    if status_cb:
        status_cb(f"正在并行检索 ({len(queries)} 个查询)…")

    if method == "Playwright":
        from playwright_tool import playwright_parallel_serp

        batch = playwright_parallel_serp(
            queries, search_engine=engine_key, per_query=per_query, timeout_per_query=timeout_q
        )
        for pack in batch:
            if not pack.get("success"):
                partial = True
                continue
            q = pack.get("query", "")
            for rank, row in enumerate(pack.get("results") or [], 1):
                all_items.append({
                    "title": row.get("title", ""),
                    "url": row.get("url", ""),
                    "snippet": row.get("snippet", ""),
                    "source_query": q,
                    "rank": rank,
                })
    else:
        from search_tool import search_serp_items

        def _one(q):
            try:
                rows = search_serp_items(q, max_results=per_query)
                return q, rows, None
            except Exception as e:
                return q, [], str(e)

        with ThreadPoolExecutor(max_workers=min(4, len(queries))) as ex:
            futs = {ex.submit(_one, q): q for q in queries}
            for fut in as_completed(futs):
                q, rows, err = fut.result()
                if err:
                    partial = True
                for rank, row in enumerate(rows, 1):
                    all_items.append({
                        **row,
                        "source_query": q,
                        "rank": rank,
                    })

    merged = _dedupe_serp_items(all_items)
    for i, it in enumerate(merged):
        it["index"] = i
    return merged, partial


def _rerank_indices(
    base_agent,
    user_input: str,
    items: List[Dict[str, Any]],
    config: Dict[str, Any],
    status_cb: Optional[Callable[[str], None]] = None,
) -> List[int]:
    max_browse = int(config.get("max_pages_to_browse", 2))
    max_browse = max(1, min(6, max_browse))
    if not items:
        return []

    if status_cb:
        status_cb("正在筛选相关来源…")

    lines = []
    for it in items:
        lines.append(
            f"[{it['index']}] 标题:{it.get('title','')[:120]} | "
            f"摘要:{it.get('snippet','')[:200]} | URL:{it.get('url','')[:120]}"
        )
    listing = "\n".join(lines)
    prompt = f"""用户问题：{user_input}

以下是搜索引擎结果（方括号内为 index）。请选出最值得深度阅读的 {max_browse} 个 index。

只输出 JSON：
{{"selected": [{{"index": 0, "reason": "简短理由"}}]}}

结果列表：
{listing}
"""
    try:
        raw = _llm_text_call(
            base_agent,
            "search_rerank_model",
            [
                {"role": "system", "content": "只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=384,
            temperature=0.0,
            task_label="web_search_rerank",
        )
        if not raw:
            raise ValueError("empty response")
        data = _parse_json_object(raw)
        picked = []
        for row in data.get("selected", []):
            idx = row.get("index")
            if isinstance(idx, int) and 0 <= idx < len(items):
                picked.append(idx)
        if picked:
            return picked[:max_browse]
    except Exception as e:
        print(f"⚠️ 相关性筛选失败，使用顺序回退: {e}")

    # 回退：原始顺序
    return [it["index"] for it in items[:max_browse]]


def _browse_urls(
    urls: List[str],
    config: Dict[str, Any],
    status_cb: Optional[Callable[[str], None]] = None,
) -> List[Dict[str, Any]]:
    if not urls:
        return []
    if status_cb:
        status_cb(f"正在深度阅读 {len(urls)} 个页面…")
    from playwright_tool import playwright_browse_multiple

    max_len = min(3000, int(config.get("max_search_context_chars", 8000)) // max(1, len(urls)))
    data = playwright_browse_multiple(urls, max_content_length=max_len)
    return data.get("results") or []


def _build_context_text(
    user_input: str,
    queries: List[str],
    items: List[Dict[str, Any]],
    selected_indices: List[int],
    browse_results: List[Dict[str, Any]],
    status: str,
    engine: str,
    max_chars: int = 8000,
) -> str:
    parts = []
    if status == "partial":
        parts.append("[检索状态: partial，部分来源不可用]\n")
    parts.append(f"用户问题: {user_input}\n")
    parts.append(f"检索查询: {', '.join(queries)}\n")
    parts.append(f"搜索引擎/方式: {engine}\n")

    idx_to_item = {it["index"]: it for it in items}
    for i, bi in enumerate(browse_results):
        if i >= len(selected_indices):
            break
        it = idx_to_item.get(selected_indices[i], {})
        parts.append(f"\n=== 来源 {i + 1} ===\n")
        parts.append(f"标题: {it.get('title', bi.get('title', ''))}\n")
        parts.append(f"URL: {it.get('url', bi.get('url', ''))}\n")
        parts.append(f"摘要: {it.get('snippet', '')}\n")
        if bi.get("success"):
            content = bi.get("content", "")
            parts.append(f"正文摘录:\n{content}\n")
        else:
            parts.append(f"正文读取失败: {bi.get('content', '')}\n")

    text = "\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…(检索上下文已截断)"
    return text


def run_web_search(
    base_agent,
    user_input: str,
    *,
    supplement_query: str = "",
    conversation_context: str = "",
    framework_snapshot: str = "",
    force: bool = False,
    status_callback: Optional[Callable[[str], None]] = None,
) -> SearchBundle:
    """
    执行完整联网检索流水线。
    force=True 时跳过 need_search 门控（Framework 已规划 search_web 时使用）。
    """
    config = base_agent.config
    bundle = SearchBundle(user_input=user_input)

    ctx = conversation_context or base_agent._get_recent_context()
    if framework_snapshot:
        ctx = f"{ctx}\n\n【框架已收集信息】\n{framework_snapshot}"

    intent = recognize_web_search_intent(base_agent, user_input, ctx)
    bundle.intent = intent

    if not force and not intent.get("need_search", False):
        bundle.status = "skipped"
        bundle.short_summary = "未触发联网检索（意图识别判断无需外部资料）。"
        return bundle

    queries = _generate_search_queries(
        base_agent, user_input, supplement_query, ctx, intent, config
    )
    bundle.queries = queries
    from workflow_status import emit_workflow, shorten, url_host

    query_label = shorten(queries[0] if queries else user_input, 20)
    query_suffix = f"等 {len(queries)} 词" if len(queries) > 1 else ""
    emit_workflow(
        base_agent,
        "web_search:queries",
        f"搜索「{query_label}」{query_suffix}中",
        "active",
    )

    items, partial = _fetch_serp_parallel(queries, config, status_callback)
    if not items:
        emit_workflow(
            base_agent,
            "web_search:queries",
            f"搜索「{query_label}」失败",
            "failed",
        )
        bundle.status = "empty"
        bundle.short_summary = "联网检索未获得搜索结果。"
        return bundle
    emit_workflow(
        base_agent,
        "web_search:queries",
        f"已搜索「{query_label}」{query_suffix}",
        "done",
    )

    selected_indices = _rerank_indices(
        base_agent, user_input, items, config, status_callback
    )
    selected = [items[i] for i in selected_indices if i < len(items)]
    bundle.selected_items = selected

    urls = [it["url"] for it in selected if it.get("url")]
    if urls:
        first_host = url_host(urls[0])
        page_suffix = f"等 {len(urls)} 个页面" if len(urls) > 1 else ""
        emit_workflow(
            base_agent,
            "web_search:browse",
            f"浏览 {first_host}{page_suffix}中",
            "active",
        )
    browse = _browse_urls(urls, config, status_callback)
    bundle.browse_results = browse
    if urls:
        failed_browse = not browse
        emit_workflow(
            base_agent,
            "web_search:browse",
            (
                f"浏览 {first_host} 失败"
                if failed_browse
                else f"已浏览 {first_host}{page_suffix}"
            ),
            "failed" if failed_browse else "done",
        )

    engine = f"{config.get('search_method', 'Playwright')} / {config.get('search_engine', 'Bing')}"
    bundle.status = "partial" if partial else "ok"
    max_ctx = int(config.get("max_search_context_chars", 8000))
    bundle.context_text = _build_context_text(
        user_input,
        queries,
        items,
        selected_indices,
        browse,
        bundle.status,
        engine,
        max_ctx,
    )
    titles = [it.get("title", "")[:40] for it in selected]
    bundle.short_summary = (
        f"已完成联网检索（{bundle.status}），深度阅读 {len(urls)} 个页面："
        + "；".join(titles)
    )
    return bundle
