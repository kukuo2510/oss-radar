"""深讀功能 M2：翻譯 agent —— 把 reader_fetch.py 產出的區塊文件翻成繁體中文（台灣用語）。

全程用本機 Ollama 模型，不花錢。流程：

1. 建術語表：先讓模型讀標題、各章標題與開頭幾段，挑出需要統一譯法的技術詞彙
   （哪些翻、哪些保留英文）。之後每一段只帶「這段有出現的」術語進提示詞。
2. 逐段翻譯：每段附上前一段原文當上下文；公式、程式碼、提示詞區塊本來就標成不翻譯。
3. 自我檢查（用程式檢查，不靠模型自評）：
   - 公式 $…$、行內程式碼 `…`、網址、數字都要原封不動出現在譯文裡
   - 不能整段沒翻（還是英文）、不能夾雜韓文／日文假名
   - 譯文長度要在合理比例內（防漏翻或亂加）
   - 不能有「以下是翻譯：」這類前言
   - 清單的項目數要對得上
4. 不合格就把具體錯誤原因告訴模型重翻，最多 2 次；還是不行就保留原文並標記。
5. 輸出一律再過 OpenCC s2twp（簡體 → 台灣用語），並統計有幾段被它修正過。

譯文存在原文旁邊：data/reader/<文件>.zh.json。中途中斷可以直接重跑，已翻好的段落會跳過。

用法（在 src/ 底下）：
    python reader_translate.py ../data/reader/x_2104216919033192746.json [--limit 20] [--model qwen2.5:14b]
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import opencc
import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("READER_MODEL", "qwen2.5:14b")
MAX_ATTEMPTS = 3  # 第一次 + 重試 2 次
_TO_TAIWAN = opencc.OpenCC("s2twp")

SYSTEM_PROMPT = """你是專業的技術文件譯者，負責把英文翻成繁體中文（台灣用語）。規則：
1. 只輸出譯文本身，不要加任何說明、前言、引號，也不要寫「譯文：」。
2. 用 $ 包住的 LaTeX 公式、用反引號 ` 包住的程式碼、函式名稱（例如 seek(t)）、檔案路徑、網址，一律原樣保留，不可翻譯或改寫；原文沒有的反引號或 $ 不要自己加。
3. 術語表裡的詞照表翻譯；標示「保留英文」的維持英文原文。
4. 產品、模型、公司、工具、人名等專有名詞保留英文。
5. 數字一律照原文寫阿拉伯數字（例如 22、2026、9,500、60 fps），不要改寫成中文數字；金額保留 $ 符號（例如 $4），不要改成「元」。
6. 使用台灣用語，例如：程式、軟體、資料、影片、品質、預設、執行、透過、介面、網路、記憶體、伺服器、使用者、漸層、置中。
7. 譯文要自然通順，不要逐字硬翻，但不能增加或刪減原文的內容；除了專有名詞以外，不要留下沒翻的英文單字。
8. 俚語、網路用語、慣用語要翻出實際意思，不要照字面直翻；不確定意思時，寧可意譯成通順的中文。"""

# OpenCC 的 s2twp 只處理常見的簡繁與兩岸詞彙，實測還會漏掉一些中國用語，或把「扩展」轉成
# 生硬的「擴充套件」。這張表在 OpenCC 之後再修一次（左邊出現就換成右邊）。
TAIWAN_FIXES = {
    "漸變": "漸層",
    "居中": "置中",
    "擴充套件": "擴充",
    "運行": "執行",
    "菜單": "選單",
    "信息": "資訊",
    "默認": "預設",
    "優化": "最佳化",
    "通過": "透過",
    "反饋": "回饋",
    "流水線": "管線",
    # 不要加「質量→品質」：物理的 mass 在台灣也叫質量，實測會把「動作有質量」改壞成「有品質」。
}

# 譯文裡出現這些英文功能詞，代表有句子片段沒翻（專有名詞不會是這些字）。
LEFTOVER_EN_RE = re.compile(r"(?<![A-Za-z`$])(with|the|and|of|for|from|that|this|into|your|you|is|are)(?![A-Za-z])", re.I)

GLOSSARY_PROMPT = """以下是一篇英文技術文章的節錄。請挑出文中反覆出現、翻譯時需要統一譯法的技術詞彙，最多 25 個。
- 一般技術概念給出繁體中文（台灣用語）譯名。
- 產品、模型、框架、工具、公司名稱，或業界習慣直接用英文的詞（例如 prompt、token、agent 若通用），標示保留英文。
只輸出 JSON，格式：{"terms": [{"en": "英文詞", "zh": "中文譯名", "keep_english": false}]}

文章節錄：
"""

# $…$ 只有 arXiv 論文代表 LaTeX 公式；X 文章裡的 $ 是美元（實測「$4 per million … $20」整段被誤認成公式）。
# translate_doc() 依文件來源切換，非 arXiv 文件改用永遠比對不到的規則。
LATEX_RE = re.compile(r"\$[^$]+\$")
NO_MATCH_RE = re.compile(r"(?!)")
MATH_RE = LATEX_RE
CODE_RE = re.compile(r"`[^`]+`")
# 沒加反引號的函式呼叫（seek(t)、track()、lib/motion.js 這類）也是程式碼，實測會被翻成「尋找(t)」。
CALL_RE = re.compile(r"(?<![\w/])[A-Za-z_][\w.]*\([\w, ]*\)|\b[\w-]+(?:/[\w.-]+)+\.\w+\b")
URL_RE = re.compile(r"https?://[^\s)\]>，。]+")
NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*%?")
CJK_RE = re.compile(r"[一-鿿]")
FOREIGN_SCRIPT_RE = re.compile(r"[가-힯぀-ヿ]")  # 韓文、日文假名
PREAMBLE_RE = re.compile(r"^\s*(以下是|譯文|翻譯|Translation|Here is)[^\n]{0,12}[:：]")
LIST_ITEM_RE = re.compile(r"^\s*\[(\d+)\]\s*(.*)$")
LIST_MARKER_RE = re.compile(r"^\s*\[\d+\]\s*", re.M)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(block: dict) -> str:
    raw = json.dumps([block.get("text"), block.get("items")], ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def chat(model: str, messages: list[dict], json_mode: bool = False, num_predict: int = 2048) -> str:
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": 8192, "num_predict": num_predict},
    }
    if json_mode:
        body["format"] = "json"
    resp = requests.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=600)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


# ---------------------------------------------------------------- 術語表

def build_glossary(doc: dict, model: str) -> list[dict]:
    parts = [doc.get("title", "")]
    parts += [b["text"] for b in doc["blocks"] if b["type"] == "heading"]
    budget = 6000
    for b in doc["blocks"]:
        if b["type"] == "paragraph" and budget > 0:
            parts.append(b["text"][:budget])
            budget -= len(b["text"])
    # 本機模型偶爾不照格式（例如 terms 變成字串清單），格式不對就再問一次，兩次都不行就不用術語表。
    terms = []
    for _ in range(2):
        raw = chat(model, [{"role": "user", "content": GLOSSARY_PROMPT + "\n".join(parts)}], json_mode=True)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        terms = [t for t in (parsed.get("terms", []) if isinstance(parsed, dict) else []) if isinstance(t, dict)]
        if terms:
            break
    glossary, seen = [], set()
    for t in terms:
        en = str(t.get("en", "")).strip()
        if not en or en.lower() in seen:
            continue
        seen.add(en.lower())
        keep = bool(t.get("keep_english"))
        zh = en if keep else to_taiwan(str(t.get("zh", "")).strip()) or en
        glossary.append({"en": en, "zh": zh, "keep_english": keep or zh == en})
    return glossary[:30]


def _terms_in(text: str, glossary: list[dict]) -> list[dict]:
    low = text.lower()
    # 允許複數形（frame → frames），不然術語表對不到。
    return [t for t in glossary if re.search(r"(?<!\w)" + re.escape(t["en"].lower()) + r"(?:s|es)?(?!\w)", low)]


def to_taiwan(text: str) -> str:
    # OpenCC s2twp 會把「文件／文档」都轉成台灣的「檔案」（簡體的文件＝file），但模型在這些文章裡
    # 幾乎都是指 documentation。先換成佔位符避開轉換，轉完再還原成「文件」。
    for word in ("文档", "文檔", "文件"):
        text = text.replace(word, "")
    text = _TO_TAIWAN.convert(text).replace("", "文件")
    for wrong, right in TAIWAN_FIXES.items():
        text = text.replace(wrong, right)
    return text


# ---------------------------------------------------------------- 檢查

def _protected(text: str) -> list[str]:
    """譯文裡必須原樣出現的片段：公式、行內程式碼、網址、數字（數字比對時去掉千分位逗號）。"""
    tokens = MATH_RE.findall(text) + CODE_RE.findall(text) + URL_RE.findall(text)
    rest = URL_RE.sub(" ", CODE_RE.sub(" ", MATH_RE.sub(" ", text)))
    tokens += CALL_RE.findall(rest)
    rest = CALL_RE.sub(" ", rest)
    tokens += [n.replace(",", "") for n in NUMBER_RE.findall(rest)]
    return tokens


def unwrap_spurious(source: str, output: str) -> str:
    """模型會「好心」把數字或一般詞包成 `30`、$9$。原文沒有的反引號／錢字號包裝就拆掉。"""
    src_spans = set(MATH_RE.findall(source) + CODE_RE.findall(source))

    def fix(m: re.Match) -> str:
        span = m.group(0)
        return span if span in src_spans else span[1:-1]

    return MATH_RE.sub(fix, CODE_RE.sub(fix, output))


CN_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
CN_NUM_RE = re.compile(r"[〇零一二兩三四五六七八九十百千]+")


def _cn_to_int(s: str) -> int | None:
    """「二十二」→22、「十二」→12、「二零二六」→2026。「第二部分」這種自然中文數字寫法不該被當成遺漏數字。"""
    if all(ch in CN_DIGITS for ch in s):  # 逐字念的年份：二零二六
        return int("".join(str(CN_DIGITS[ch]) for ch in s))
    total, cur = 0, 0
    for ch in s:
        if ch in CN_DIGITS:
            cur = CN_DIGITS[ch]
        elif ch in "十百千":
            total += (cur or 1) * {"十": 10, "百": 100, "千": 1000}[ch]
            cur = 0
        else:
            return None
    return total + cur


def check(source: str, output: str) -> list[str]:
    issues = []
    if not output.strip():
        return ["譯文是空的"]
    if PREAMBLE_RE.search(output):
        issues.append("譯文開頭多了「以下是翻譯」之類的前言，只要輸出譯文本身")
    if FOREIGN_SCRIPT_RE.search(output):
        issues.append("譯文夾雜了韓文或日文字元，只能用繁體中文")
    flat_out = output.replace(",", "")
    cn_numbers = {str(n) for n in map(_cn_to_int, CN_NUM_RE.findall(output)) if n is not None}
    missing = [
        t for t in _protected(source)
        if t.replace(",", "") not in flat_out and t not in output and t.rstrip("%") not in cn_numbers
    ]
    if missing:
        issues.append("以下片段必須原樣保留但譯文裡找不到：" + "、".join(dict.fromkeys(missing[:6])))
    if MATH_RE is NO_MATCH_RE and re.search(r"\$\d", source) and not re.search(r"\$\d|美元", output):
        issues.append("原文的金額是美元，譯文要保留 $ 符號（例如 $4），不要寫成「元」")
    words = len(re.findall(r"[A-Za-z]+", source))
    if words >= 4 and not CJK_RE.search(output):
        issues.append("這段沒有翻譯成中文")
    elif CJK_RE.search(output):
        # 只看公式、程式碼、網址以外的部分，避免把 `for` 迴圈之類的程式碼誤判成沒翻的英文。
        prose = URL_RE.sub(" ", CODE_RE.sub(" ", MATH_RE.sub(" ", output)))
        leftover = sorted({m.lower() for m in LEFTOVER_EN_RE.findall(prose)})
        if leftover:
            issues.append("譯文還留著沒翻的英文單字：" + "、".join(leftover) + "，請整句翻成中文")
    # 長度比例只比「文字」部分：網址、程式碼、公式兩邊都扣掉，否則網址很多的段落會被誤判。
    plain = len(MATH_RE.sub("", CODE_RE.sub("", URL_RE.sub("", source))))
    if plain >= 60:
        ratio = len(MATH_RE.sub("", CODE_RE.sub("", URL_RE.sub("", output)))) / plain
        if ratio < 0.15:
            issues.append(f"譯文太短（只有原文長度的 {ratio:.0%}），可能漏翻")
        elif ratio > 1.6:
            issues.append(f"譯文太長（原文長度的 {ratio:.0%}），可能加了原文沒有的內容")
    return issues


# ---------------------------------------------------------------- 翻譯單一區塊

def _prompt(text: str, glossary: list[dict], context: str, list_mode: bool) -> str:
    lines = []
    terms = _terms_in(text, glossary)
    if terms:
        lines.append("術語表：")
        for t in terms:
            lines.append(f"- {t['en']} → {t['en'] + '（保留英文）' if t['keep_english'] else t['zh']}")
        lines.append("")
    if context:
        lines += ["前文（僅供理解上下文，不要翻譯）：", context[:600], ""]
    if list_mode:
        lines.append("請翻譯以下清單，每一項保留開頭的 [編號]，一項一行，項目數量不可改變：")
    else:
        lines.append("請翻譯：")
    lines.append(text)
    return "\n".join(lines)


def translate_block(block: dict, glossary: list[dict], context: str, model: str) -> dict:
    if block["type"] == "list" and len(block["items"]) == 1:
        # 單項清單（X 長文常拿來當「Part 2 · …」分節標題）當一般文字翻：加上 [1] 編號時，
        # 模型會被「Part 3」帶偏寫成 [3]。
        r = translate_block({"type": "paragraph", "text": block["items"][0]}, glossary, context, model)
        if "text" in r:
            r["items"] = [r.pop("text")]
        return r
    is_list = block["type"] == "list"
    source = "\n".join(f"[{i + 1}] {item}" for i, item in enumerate(block["items"])) if is_list else block["text"]
    # 檢查保留片段時不能把清單編號 [1]、[2] 也算進去。
    check_source = "\n".join(block["items"]) if is_list else source
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _prompt(source, glossary, context, is_list)},
    ]
    history = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        raw = chat(model, messages).strip()
        converted = unwrap_spurious(check_source, to_taiwan(raw))
        issues = check(check_source, LIST_MARKER_RE.sub("", converted) if is_list else converted)
        items = None
        if is_list and not issues:
            parsed = [LIST_ITEM_RE.match(ln) for ln in converted.splitlines() if ln.strip()]
            items = [m.group(2).strip() for m in parsed if m]
            if len(items) != len(block["items"]) or any(not m for m in parsed):
                issues.append(f"清單應該有 {len(block['items'])} 項、每項以 [編號] 開頭，譯文格式不符")
        history.append(issues)
        if not issues:
            result = {"status": "ok", "attempts": attempt, "opencc_fixed": converted != raw}
            if is_list:
                result["items"] = items
            else:
                result["text"] = converted
            if attempt > 1:
                result["issues_history"] = history[:-1]
            return result
        # 帶著具體錯誤原因重翻：把剛才的譯文跟問題一起告訴模型。
        messages += [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "這份譯文有問題：\n- " + "\n- ".join(issues) + "\n請修正後重新輸出完整譯文，只輸出譯文。"},
        ]
    # 三次都不合格：閱讀頁顯示原文，但留下最後一次譯文方便除錯。
    return {"status": "fallback", "attempts": MAX_ATTEMPTS, "issues_history": history, "last_output": converted}


# ---------------------------------------------------------------- 主流程

# ---------------------------------------------------------------- 重點整理

SUMMARY_CHUNK_CHARS = 7000  # 一次給模型看的原文長度（num_ctx 8192 的安全範圍）
SUMMARY_PROMPT = """以下是一篇英文文章的段落，每段開頭的 [b12] 是段落編號。
請用繁體中文（台灣用語）整理，只根據這些段落，不要加入原文沒有的內容：
- one_line：一句話說明這篇在講什麼（40 字以內）
- key_points：{n} 個最重要的重點，每點 60 字以內，盡量具體（方法、數字、結論）；
  每點附上依據的段落編號 1～3 個（必須是上面出現過的編號）
專有名詞保留英文。只輸出 JSON：
{{"one_line": "...", "key_points": [{{"text": "...", "blocks": ["b12", "b15"]}}]}}
{glossary}
段落：
"""
REDUCE_PROMPT = """以下是同一篇英文文章分段整理出來的重點（繁體中文），每點後面的 [b12] 是原文段落編號。
請合併成整篇文章的重點整理，去掉重複、保留最重要的：
- one_line：一句話說明整篇在講什麼（40 字以內）
- key_points：{n} 個重點，每點 60 字以內；blocks 沿用原本附的段落編號（1～3 個）
只輸出 JSON：{{"one_line": "...", "key_points": [{{"text": "...", "blocks": ["b12"]}}]}}

分段重點：
"""


def _summary_source_blocks(doc: dict) -> list[dict]:
    """拿來整理重點的段落：一般文字類區塊（不含程式碼、提示詞、公式、參考文獻那類短句）。"""
    out = []
    for b in doc["blocks"]:
        if b["type"] in {"paragraph", "quote", "heading", "list"}:
            text = b.get("text") or " ".join(b.get("items", []))
            if text and text != "References" and not text.startswith("（共 "):
                out.append({"id": b["id"], "text": text})
    return out


def _parse_summary(raw: str, valid_ids: set[str]) -> tuple[dict | None, list[str]]:
    """解析並檢查模型給的 JSON：重點至少 2 點、要有中文、引用的段落編號必須真的存在。"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, ["輸出不是合法的 JSON"]
    issues = []
    one_line = to_taiwan(str(data.get("one_line", "")).strip())
    points = []
    for p in data.get("key_points", []) if isinstance(data, dict) else []:
        if not isinstance(p, dict):
            continue
        text = to_taiwan(str(p.get("text", "")).strip())
        cited = [str(x).strip().strip("[]") for x in p.get("blocks", [])]
        cited = [x for x in dict.fromkeys(cited) if x in valid_ids][:3]
        if text and CJK_RE.search(text):
            points.append({"text": text, "blocks": cited})
    if not one_line or not CJK_RE.search(one_line):
        issues.append("缺少中文的 one_line")
    if len(points) < 2:
        issues.append("重點少於 2 點")
    uncited = sum(1 for p in points if not p["blocks"])
    if points and uncited > len(points) // 2:
        issues.append("多數重點沒有附上存在的段落編號")
    if issues:
        return None, issues
    return {"one_line": one_line, "key_points": points}, []


def _ask_summary(model: str, prompt: str, valid_ids: set[str]) -> dict | None:
    messages = [{"role": "user", "content": prompt}]
    for _ in range(3):
        raw = chat(model, messages, json_mode=True, num_predict=1500)
        summary, issues = _parse_summary(raw, valid_ids)
        if summary:
            return summary
        messages += [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "有問題：" + "；".join(issues) + "。請修正後重新輸出完整 JSON。"},
        ]
    return None


def summarize(doc: dict, glossary: list[dict], model: str) -> dict | None:
    """本機模型整理重點，每點附上依據的原文段落編號（閱讀頁用來標記重點段落、點了跳過去）。

    依據英文原文整理（不是譯文），避免翻譯錯誤被帶進重點。文章太長就分段整理再合併。
    """
    blocks = _summary_source_blocks(doc)
    if not blocks:
        return None
    valid_ids = {b["id"] for b in blocks}
    terms = [t for t in glossary if not t["keep_english"]][:20]
    glossary_hint = ("術語譯名：" + "、".join(f"{t['en']}→{t['zh']}" for t in terms) + "\n") if terms else ""

    chunks, cur, size = [], [], 0
    for b in blocks:
        line = f"[{b['id']}] {b['text'][:1500]}"
        if cur and size + len(line) > SUMMARY_CHUNK_CHARS:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(line)
        size += len(line)
    if cur:
        chunks.append(cur)

    if len(chunks) == 1:
        prompt = SUMMARY_PROMPT.format(n="3～5", glossary=glossary_hint) + "\n".join(chunks[0])
        return _ask_summary(model, prompt, valid_ids)

    # 分段整理（每段 2～3 點）再合併；合併時模型看不到原文，只沿用各段附的段落編號。
    notes = []
    for i, chunk in enumerate(chunks, 1):
        print(f"  整理重點：第 {i}/{len(chunks)} 段", flush=True)
        part = _ask_summary(model, SUMMARY_PROMPT.format(n="2～3", glossary=glossary_hint) + "\n".join(chunk), valid_ids)
        if part:
            notes += [f"- {p['text']} " + " ".join(f"[{bid}]" for bid in p["blocks"]) for p in part["key_points"]]
    if not notes:
        return None
    return _ask_summary(model, REDUCE_PROMPT.format(n="4～6") + "\n".join(notes), valid_ids)


def _out_path(doc_path: Path) -> Path:
    return doc_path.with_name(doc_path.stem + ".zh.json")


def translate(doc: dict, model: str, prev: dict | None = None, limit: int | None = None,
              on_progress=None, name: str = "") -> dict:
    """翻譯一份區塊文件，回傳譯文 dict。

    prev：上次（可能中斷）的譯文，同模型、原文沒變的段落直接沿用。
    on_progress(result, done, total)：每翻完一段呼叫一次，呼叫端負責存檔／寫資料庫，
    長論文跑到一半中斷也不會白翻。
    """
    prev = prev or {}
    started = time.time()
    global MATH_RE
    MATH_RE = LATEX_RE if doc["source"] == "arxiv" else NO_MATCH_RE

    glossary = prev.get("glossary") if prev.get("model") == model else None
    if glossary is None:
        print("建立術語表…", flush=True)
        glossary = build_glossary(doc, model)
        print(f"  {len(glossary)} 個術語：" + "、".join(f"{t['en']}→{t['zh']}" for t in glossary[:12]), flush=True)

    result = {
        "schema": 1,
        "doc": name,
        "title": doc.get("title"),
        "model": model,
        "glossary": glossary,
        "blocks": dict(prev.get("blocks", {})) if prev.get("model") == model else {},
        "title_zh": prev.get("title_zh") if prev.get("model") == model else None,
        "summary": prev.get("summary") if prev.get("model") == model else None,
    }
    if not result["title_zh"] and doc.get("title"):
        result["title_zh"] = translate_block({"type": "heading", "text": doc["title"]}, glossary, "", model).get("text")

    todo = [b for b in doc["blocks"] if b["translate"]]
    if limit:
        todo = todo[:limit]
    context = ""
    done_now = 0
    for i, block in enumerate(todo, 1):
        cached = result["blocks"].get(block["id"])
        source_text = block.get("text") or " ".join(block.get("items", []))
        if cached and cached.get("hash") == _hash(block) and cached["status"] == "ok":
            context = source_text
            continue
        t0 = time.time()
        r = translate_block(block, glossary, context, model)
        r["hash"] = _hash(block)
        r["seconds"] = round(time.time() - t0, 1)
        result["blocks"][block["id"]] = r
        done_now += 1
        mark = "OK " if r["status"] == "ok" else "XX "
        retry = f" 重試{r['attempts'] - 1}次" if r["attempts"] > 1 else ""
        print(f"  [{i}/{len(todo)}] {mark}{block['id']:<5} {block['type']:<9} {r['seconds']:>5}s{retry}", flush=True)
        context = source_text
        if on_progress:
            on_progress(result, i, len(todo))

    if not result.get("summary") and not limit:
        print("整理重點…", flush=True)
        result["summary"] = summarize(doc, glossary, model)

    result["stats"] = stats(doc, result, todo, time.time() - started, done_now)
    result["finished_at"] = _now()
    return result


def translate_doc(doc_path: Path, model: str, limit: int | None = None) -> dict:
    """命令列用：讀 data/reader/ 的文件，譯文存在旁邊的 .zh.json。"""
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    out_path = _out_path(doc_path)
    prev = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}

    def save(result, done, total):
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    result = translate(doc, model, prev, limit, on_progress=save, name=doc_path.name)
    save(result, None, None)
    return result


def stats(doc: dict, result: dict, todo: list[dict], seconds: float, done_now: int) -> dict:
    rs = [result["blocks"][b["id"]] for b in todo if b["id"] in result["blocks"]]
    ok = [r for r in rs if r["status"] == "ok"]
    chars = sum(len(b.get("text", "")) + sum(len(x) for x in b.get("items", [])) for b in todo)

    # 術語一致率：要翻成中文的術語，在「原文出現該術語」的段落裡，譯文是否真的用了表上的譯名。
    hits = total = 0
    by_id = {b["id"]: b for b in todo}
    for t in result["glossary"]:
        if t["keep_english"]:
            continue
        for bid, r in result["blocks"].items():
            b = by_id.get(bid)
            if not b or r["status"] != "ok":
                continue
            src = b.get("text") or " ".join(b.get("items", []))
            if _terms_in(src, [t]):
                total += 1
                zh = r.get("text") or " ".join(r.get("items", []))
                hits += t["zh"] in zh
    return {
        "blocks": len(todo),
        "ok": len(ok),
        "fallback": len(rs) - len(ok),
        "first_try_ok": sum(1 for r in ok if r["attempts"] == 1),
        "retried_then_ok": sum(1 for r in ok if r["attempts"] > 1),
        "opencc_fixed": sum(1 for r in ok if r.get("opencc_fixed")),
        "source_chars": chars,
        "seconds_this_run": round(seconds),
        "blocks_this_run": done_now,
        "glossary_terms": len(result["glossary"]),
        "glossary_consistency": f"{hits}/{total}" if total else "n/a",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("doc", type=Path)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--limit", type=int, help="只翻前 N 個區塊（調整用）")
    args = ap.parse_args()
    result = translate_doc(args.doc, args.model, args.limit)
    print("\n" + json.dumps(result["stats"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
