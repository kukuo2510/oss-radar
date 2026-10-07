"""深讀功能 M1：把一篇內容（arXiv 論文、X 貼文／長文）抓下來，轉成統一的「區塊」格式。

後續的翻譯 agent 跟閱讀頁都只認這個格式，不需要知道內容原本來自哪裡。

文件格式（dict，存成 JSON）：
    schema       格式版本（目前 1）
    source       "arxiv" | "x"
    source_id    arXiv ID 或推文 ID
    url          原文連結（閱讀頁的「原文」按鈕跟出處區塊都用這個）
    title, authors, published_at, fetched_at
    extraction   用哪種方式抽出來的：arxiv-html / arxiv-pdf / x-article / x-post
    full_text    是否拿到全文（失敗退回只有摘要時為 False）
    warnings     抽取過程中值得讓讀者知道的事（例如 PDF 模式公式會遺失）
    blocks       區塊清單，每個區塊：
        id         "b0"、"b1"…，翻譯結果靠它對回原文
        type       heading / paragraph / quote / list / code / prompt / math / image / table / embed / divider
        translate  這個區塊要不要翻譯（程式碼、提示詞、公式一律 False）
        text       區塊文字（list 用 items；image/table 的 text 是圖說）
        其他依類型：level（heading）、items/ordered（list）、lang（code）、src（image）、
                    url（embed）、links（文字裡的超連結）、marks（粗斜體，Draft.js 原始 offset）

用法（在 src/ 底下）：
    python reader_fetch.py <arXiv ID 或網址> [<X 網址> ...]
    python reader_fetch.py --testset          # 跑 reader_testset.txt 裡的測試文章
"""

import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from pdfminer.high_level import extract_text as pdf_extract_text
from pdfminer.layout import LAParams

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "reader"
TESTSET_PATH = Path(__file__).resolve().parent / "reader_testset.txt"
HEADERS = {"User-Agent": "oss-radar-reader/0.1 (personal reading tool; https://github.com/kukuo2510/oss-radar)"}

# arXiv 的使用規範：同一時間一條連線、每次請求間隔至少 3 秒。
ARXIV_MIN_INTERVAL = 3.0
_last_arxiv_request = 0.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _arxiv_get(url: str) -> requests.Response:
    global _last_arxiv_request
    wait = ARXIV_MIN_INTERVAL - (time.time() - _last_arxiv_request)
    if wait > 0:
        time.sleep(wait)
    try:
        return requests.get(url, headers=HEADERS, timeout=60)
    finally:
        _last_arxiv_request = time.time()


class Blocks:
    """依序收集區塊並自動編號，順便把空白區塊擋掉。"""

    TRANSLATABLE = {"heading", "paragraph", "quote", "list", "image", "table"}

    def __init__(self):
        self.items: list[dict] = []

    def add(self, type_: str, text: str = "", **fields) -> None:
        if type_ in {"heading", "paragraph", "quote", "code", "prompt", "math"} and not text.strip():
            return
        if type_ == "list" and not fields.get("items"):
            return
        block = {"id": f"b{len(self.items)}", "type": type_, "translate": type_ in self.TRANSLATABLE}
        if text:
            block["text"] = text
        block.update({k: v for k, v in fields.items() if v not in (None, [], "")})
        if type_ in {"image", "table"} and not block.get("text"):
            block["translate"] = False  # 沒有圖說就沒東西可翻
        self.items.append(block)


# ---------------------------------------------------------------- arXiv

ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")


def parse_arxiv_id(ref: str) -> str:
    m = ARXIV_ID_RE.search(ref)
    if not m:
        raise ValueError(f"看不出 arXiv ID：{ref}")
    return m.group(1) + (m.group(2) or "")


def arxiv_metadata(arxiv_id: str) -> dict:
    """從 arXiv 官方 API 拿標題、作者、日期、摘要（HTML 版跟 PDF 版共用，PDF 本身抽不準這些）。"""
    resp = _arxiv_get(f"https://export.arxiv.org/api/query?id_list={arxiv_id}")
    resp.raise_for_status()
    feed = feedparser.parse(resp.text)
    if not feed.entries:
        raise ValueError(f"arXiv 查無此 ID：{arxiv_id}")
    e = feed.entries[0]
    return {
        "title": _clean(e.title),
        "authors": [a.name for a in e.get("authors", [])],
        "published_at": e.get("published"),
        "abstract": _clean(e.summary),
    }


def _inline_text(el: Tag) -> str:
    """段落內文：公式換成 $LaTeX$（翻譯時原樣保留），拿掉註腳，其餘取純文字。"""
    el = BeautifulSoup(str(el), "html.parser")
    for note in el.select(".ltx_note"):
        note.decompose()
    for math in el.find_all("math"):
        tex = math.get("alttext", "").strip()
        math.replace_with(NavigableString(f" ${tex}$ " if tex else ""))
    return _clean(el.get_text())


def _walk_arxiv(el: Tag, out: Blocks, base: str) -> None:
    for child in el.children:
        if not isinstance(child, Tag):
            continue
        classes = child.get("class", [])
        name = child.name

        if "ltx_bibliography" in classes:
            out.add("heading", "References", level=1)
            out.add("paragraph", f"（共 {len(child.select('li.ltx_bibitem'))} 筆參考文獻，未展開）")
            out.items[-1]["translate"] = False
            continue
        if "ltx_authors" in classes or "ltx_title_document" in classes or "ltx_dates" in classes:
            continue
        if name in {"h2", "h3", "h4", "h5", "h6"} and "ltx_title" in classes:
            level = 1 if "ltx_title_abstract" in classes else {"h2": 1, "h3": 2, "h4": 3}.get(name, 4)
            out.add("heading", _inline_text(child), level=level)
            continue
        if name == "p" and "ltx_p" in classes:
            out.add("paragraph", _inline_text(child))
            continue
        if "ltx_equation" in classes or "ltx_equationgroup" in classes:
            tex = " \\\\ ".join(m.get("alttext", "").strip() for m in child.find_all("math") if m.get("alttext"))
            tag = child.select_one(".ltx_tag_equation")
            out.add("math", tex, label=_clean(tag.get_text()) if tag else None)
            continue
        if name == "figure" and "ltx_table" in classes:
            cap = child.find("figcaption")
            rows = [[_inline_text(td) for td in tr.find_all(["td", "th"])] for tr in child.find_all("tr")]
            out.add("table", _inline_text(cap) if cap else "", rows=[r for r in rows if any(r)])
            continue
        if name == "figure" and "ltx_figure" in classes:
            cap = child.find("figcaption", recursive=False) or child.find("figcaption")
            srcs = [urljoin(base, img["src"]) for img in child.find_all("img") if img.get("src")]
            out.add("image", _inline_text(cap) if cap else "", src=srcs[0] if srcs else None, extra_src=srcs[1:])
            continue
        if name in {"ul", "ol"} and ("ltx_itemize" in classes or "ltx_enumerate" in classes):
            out.add("list", items=[_inline_text(li) for li in child.find_all("li", recursive=False)], ordered=name == "ol")
            continue
        if "ltx_listing" in classes:
            out.add("code", child.get_text("\n").strip())
            continue
        _walk_arxiv(child, out, base)


def _arxiv_from_html(arxiv_id: str, html: str, base: str) -> tuple[list[dict], list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("article.ltx_document") or soup.select_one("article")
    if article is None:
        raise ValueError("HTML 版沒有找到正文")
    out = Blocks()
    _walk_arxiv(article, out, base)
    return out.items, []


HEADING_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,2})\.?\s+([A-Z][A-Za-z][^.]{1,80})$")
MAX_PARAGRAPH = 1500  # PDF 偶爾會把好幾段黏在一起，太長就在句號處切開，免得一段翻譯塞太多


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_PARAGRAPH:
        return [text]
    parts, cur = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text):
        if cur and len(cur) + len(sentence) > MAX_PARAGRAPH:
            parts.append(cur)
            cur = sentence
        else:
            cur = f"{cur} {sentence}".strip()
    return parts + ([cur] if cur else [])


def _pdf_heading(line: str) -> int | None:
    """「1 Introduction」「3.2 Filtered Q-Gradients as a Trust Region」這類行回傳層級，否則 None。
    限制編號最多兩位數、標題要以英文字開頭且大多是字母，排除「10 Wall-clock (hours)」這種圖表標籤。"""
    m = HEADING_RE.match(line)
    if not m or len(line) > 90:
        return None
    title = m.group(2)
    if sum(ch.isalpha() or ch == " " for ch in title) < len(title) * 0.85:
        return None
    return min(m.group(1).count(".") + 1, 3)


def _arxiv_from_pdf(pdf_bytes: bytes) -> tuple[list[dict], list[str]]:
    """PDF 備援：只能拿到純文字。用 pdfminer（pypdf 實測會把英文單字間的空格吃掉），
    它會用空行分出文字框，大致等於段落；章節標題常跟段落第一行黏在同一個文字框，要先拆出來。"""
    text = pdf_extract_text(io.BytesIO(pdf_bytes), laparams=LAParams())
    out = Blocks()
    dropped = 0
    for chunk in re.split(r"\n\s*\n", text):
        lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
        if not lines:
            continue
        if re.fullmatch(r"(references|bibliography)", lines[0], re.I):
            # 參考文獻之後通常是附錄；PDF 模式抽不準附錄的版面，到這裡就停。
            out.add("heading", "References", level=1)
            break
        level = _pdf_heading(lines[0])
        if level:
            out.add("heading", lines[0], level=level)
            lines = lines[1:]
            if not lines:
                continue
        joined = _clean(re.sub(r"(\w)-\s+(\w)", r"\1\2", " ".join(lines)))  # 行尾連字號斷字
        # 很短、字母很少的文字框多半是頁碼、圖表座標軸標籤、公式碎片，不是正文。
        letters = sum(ch.isalpha() for ch in joined)
        if len(joined) < 40 or letters < len(joined) * 0.5:
            dropped += 1
            continue
        # 跨頁、跨欄的段落會被切成兩個文字框：上一段沒有句尾標點、這段又是小寫開頭，就接回去。
        prev = out.items[-1] if out.items else None
        if prev and prev["type"] == "paragraph" and joined[0].islower() and not re.search(r"[.!?:]$", prev["text"]):
            joined = prev["text"] + " " + joined
            out.items.pop()
        for part in _split_long(joined):
            out.add("paragraph", part)
    warnings = [
        "這篇沒有 arXiv HTML 版，改從 PDF 抽文字：公式、表格、圖片會遺失，段落切分可能不準，參考文獻之後的附錄不收。",
        f"略過 {dropped} 個疑似頁碼／圖表標籤／公式碎片的短文字框。",
    ]
    return out.items, warnings


def fetch_arxiv(ref: str) -> dict:
    arxiv_id = parse_arxiv_id(ref)
    meta = arxiv_metadata(arxiv_id)
    doc = {
        "schema": 1,
        "source": "arxiv",
        "source_id": arxiv_id,
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "title": meta["title"],
        "authors": meta["authors"],
        "published_at": meta["published_at"],
        "fetched_at": _now(),
    }

    resp = _arxiv_get(f"https://arxiv.org/html/{arxiv_id}")
    if resp.status_code == 200 and "ltx_document" in resp.text:
        base = resp.url  # 圖片路徑是相對於這頁網址的，用 urljoin 解析，不能自己接字串
        blocks, warnings = _arxiv_from_html(arxiv_id, resp.text, base)
        return {**doc, "extraction": "arxiv-html", "full_text": True, "warnings": warnings, "blocks": blocks}

    pdf = _arxiv_get(f"https://arxiv.org/pdf/{arxiv_id}")
    if pdf.status_code == 200 and pdf.content.startswith(b"%PDF"):
        blocks, warnings = _arxiv_from_pdf(pdf.content)
        return {**doc, "extraction": "arxiv-pdf", "full_text": True, "warnings": warnings, "blocks": blocks}

    out = Blocks()
    out.add("heading", "Abstract", level=1)
    out.add("paragraph", meta["abstract"])
    return {**doc, "extraction": "arxiv-abstract", "full_text": False,
            "warnings": ["HTML 與 PDF 都抓不到，只有摘要。"], "blocks": out.items}


# ---------------------------------------------------------------- X

X_STATUS_RE = re.compile(r"(?:x|twitter)\.com/(?:(\w+)|i)/status(?:es)?/(\d+)")

# 「提示詞」與「程式碼」都保留原文不翻，但閱讀頁的呈現不同（提示詞附複製鈕）。
# X 長文裡的 code fence 語言標籤不可靠（純英文提示詞也常被標成 python），所以改看內容。
CODE_LINE_RE = re.compile(
    r"[;{}]\s*$|=>|==|\w\(.*\)|^\s*(import|from|const|let|var|def|class|function|export|return|async|await|try|except)\b"
    r"|^\s*(npm|npx|pip|brew|apt|ffmpeg|mkdir|cd|node|python3?|git|curl|source|export)\b|^\s*//|^\s*<\w+"
    r"|^\s*[\w.]+\s*=\s*\S|^\s*\w+=|^\s*[)\]}]+,?\s*$|\($"
)
# 第一行就是 import／賦值／函式呼叫，幾乎一定是程式碼（裡面就算夾著很長的提示詞字串也一樣）。
CODE_FIRST_LINE_RE = re.compile(r"^\s*(import |from \S+ import |def |class |const |let |async |[\w.]+\s*=\s*[\w.]+\()")


def _classify_fence(body: str) -> str:
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if not lines:
        return "code"
    if CODE_FIRST_LINE_RE.match(lines[0]):
        return "code"
    code_like = sum(1 for ln in lines if CODE_LINE_RE.search(ln))
    return "code" if code_like / len(lines) >= 0.3 else "prompt"


def _parse_fence(markdown: str) -> tuple[str, str]:
    m = re.match(r"^```([\w+-]*)\n(.*?)\n?```\s*$", markdown.strip(), re.S)
    return (m.group(1), m.group(2)) if m else ("", markdown.strip())


def parse_x_status(ref: str) -> str:
    m = X_STATUS_RE.search(ref)
    if m:
        return m.group(2)
    if re.fullmatch(r"\d{10,25}", ref):
        return ref
    raise ValueError(f"看不出推文 ID：{ref}")


def _fxtwitter(status_id: str) -> dict:
    # fxtwitter 是非官方服務，隨時可能失效；只用來抓使用者主動分享的單篇連結。
    resp = requests.get(f"https://api.fxtwitter.com/status/{status_id}", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 200 or "tweet" not in data:
        raise ValueError(f"fxtwitter 回應異常：{data.get('message')}")
    return data["tweet"]


def _x_article_blocks(article: dict) -> list[dict]:
    content = article["content"]
    entities = {str(e["key"]): e["value"] for e in content.get("entityMap", [])}
    media = {
        str(m.get("media_id")): (m.get("media_info") or {}).get("original_img_url")
        for m in article.get("media_entities") or []
    }
    out = Blocks()
    cover = (article.get("cover_media") or {}).get("media_info", {}).get("original_img_url")
    if cover:
        out.add("image", src=cover)

    list_buf: list[str] = []
    list_ordered = False

    def flush_list():
        if list_buf:
            out.add("list", items=list(list_buf), ordered=list_ordered)
            list_buf.clear()

    for b in content["blocks"]:
        btype, text = b["type"], b.get("text", "")
        if btype in {"unordered-list-item", "ordered-list-item"}:
            ordered = btype == "ordered-list-item"
            if list_buf and ordered != list_ordered:
                flush_list()
            list_ordered = ordered
            if text.strip():
                list_buf.append(text.strip())
            continue
        flush_list()

        links = []
        for r in b.get("entityRanges", []):
            ent = entities.get(str(r["key"]), {})
            if ent.get("type") == "LINK":
                links.append({"text": text[r["offset"]: r["offset"] + r["length"]], "url": ent["data"].get("url")})
        marks = [{"offset": s["offset"], "length": s["length"], "style": s["style"]} for s in b.get("inlineStyleRanges", [])]

        if btype == "atomic":
            for r in b.get("entityRanges", []):
                ent = entities.get(str(r["key"]), {})
                etype, data = ent.get("type"), ent.get("data", {})
                if etype == "MARKDOWN":
                    # X 長文編輯器的語言標籤不可靠（JS、shell 也常被標成 python），所以不保留。
                    _, body = _parse_fence(data.get("markdown", ""))
                    out.add(_classify_fence(body), body)
                elif etype == "MEDIA":
                    for mi in data.get("mediaItems", []):
                        out.add("image", src=media.get(str(mi.get("mediaId"))))
                elif etype == "TWEET":
                    out.add("embed", url=f"https://x.com/i/status/{data.get('tweetId')}")
                elif etype == "DIVIDER":
                    out.add("divider")
        elif btype in {"header-one", "header-two", "header-three"}:
            out.add("heading", text.strip(), level={"header-one": 1, "header-two": 2}.get(btype, 3))
        elif btype == "blockquote":
            out.add("quote", text.strip(), links=links, marks=marks)
        else:
            # 一個 Draft.js 區塊裡可能用空行分成好幾段，拆開來翻譯比較準。
            parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
            for part in parts:
                own_links = [lk for lk in links if lk["text"] and lk["text"] in part]
                out.add("paragraph", part, links=own_links, marks=marks if len(parts) == 1 else None)
    flush_list()
    return out.items


def _x_post_blocks(tweet: dict) -> list[dict]:
    out = Blocks()
    for part in re.split(r"\n\s*\n", tweet.get("text") or ""):
        part = re.sub(r"\s*https://t\.co/\w+$", "", part.strip())
        out.add("paragraph", part)
    for photo in (tweet.get("media") or {}).get("photos", []):
        out.add("image", src=photo.get("url"))
    quote = tweet.get("quote")
    if quote:
        out.add("embed", url=quote.get("url"))
    return out.items


def fetch_x(ref: str) -> dict:
    status_id = parse_x_status(ref)
    tweet = _fxtwitter(status_id)
    # 分享的貼文常常只是「引用一篇 X 長文」的引子，真正要讀的是被引用的那篇長文。
    target = tweet
    if not tweet.get("article") and (tweet.get("quote") or {}).get("article"):
        target = tweet["quote"]
    author = target.get("author") or {}
    doc = {
        "schema": 1,
        "source": "x",
        "source_id": str(target.get("id")),
        "url": target.get("url"),
        "shared_url": tweet.get("url") if target is not tweet else None,
        "authors": [f"{author.get('name')} (@{author.get('screen_name')})"],
        "published_at": target.get("created_at"),
        "fetched_at": _now(),
        "full_text": True,
        "warnings": [],
    }
    article = target.get("article")
    if article:
        return {**doc, "title": _clean(article.get("title") or ""), "extraction": "x-article",
                "blocks": _x_article_blocks(article)}
    first_line = _clean((target.get("text") or "").split("\n")[0])
    return {**doc, "title": first_line[:80] or f"@{author.get('screen_name')} 的貼文", "extraction": "x-post",
            "warnings": ["一般貼文：fxtwitter 不提供整串討論串，只有這一則。"],
            "blocks": _x_post_blocks(target)}


# ---------------------------------------------------------------- 入口

def fetch(ref: str) -> dict:
    if X_STATUS_RE.search(ref):
        return fetch_x(ref)
    if "arxiv.org" in ref or ARXIV_ID_RE.fullmatch(ref.strip()):
        return fetch_arxiv(ref)
    raise ValueError(f"不支援的來源：{ref}")


def save(doc: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{doc['source']}_{doc['source_id'].replace('/', '_')}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def summarize(doc: dict) -> str:
    counts: dict[str, int] = {}
    for b in doc["blocks"]:
        counts[b["type"]] = counts.get(b["type"], 0) + 1
    chars = sum(len(b.get("text", "")) + sum(len(i) for i in b.get("items", [])) for b in doc["blocks"] if b["translate"])
    kinds = " ".join(f"{k}={v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
    return f"{doc['extraction']:<14} {len(doc['blocks']):>4} 區塊  待翻 {chars:>6} 字元  {kinds}"


def main(argv: list[str]) -> int:
    refs = argv
    if argv[:1] == ["--testset"]:
        refs = [ln.split("#")[0].strip() for ln in TESTSET_PATH.read_text(encoding="utf-8").splitlines()]
        refs = [r for r in refs if r]
    if not refs:
        print(__doc__)
        return 1
    failed = 0
    for ref in refs:
        try:
            doc = fetch(ref)
            save(doc)
            print(f"[OK]   {ref:<58} {summarize(doc)}")
            for w in doc["warnings"]:
                print(f"       ! {w}")
        except Exception as e:  # 測試集要跑完全部，單篇失敗只記錄
            failed += 1
            print(f"[FAIL] {ref:<58} {type(e).__name__}: {e}")
    print(f"\n{len(refs) - failed}/{len(refs)} 成功，輸出在 {OUT_DIR}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
