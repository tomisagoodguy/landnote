"""掃描檔考古題 OCR：抽不到文字的 PDF 逐頁辨識，寫成 data/exam_ocr/<科目>/<檔名>.txt。

快取提交進 repo，exam_bank._pdf_text 遇到掃描檔會改讀快取，CI 不需要 OCR 套件。
新的掃描檔下載後在本機跑一次（server 模型在 CPU 約一頁 60 秒）：

    uv run --project landnotev3 --with pymupdf --with "rapidocr>=3" --with onnxruntime \
        python landnotev3/scripts/ocr_scanned.py [--force] [--limit N]

模型用 PP-OCRv5 server：舊版（PP-OCRv4）把「採購」認成「探購」並混出簡體字，v5 才堪用。

`--check` 只列出還沒有 OCR 快取的掃描檔、不辨識（只需 pymupdf），每月 update_exams.yml 用它提醒：
在 GitHub Actions 中會輸出 warning 註記並寫入執行摘要。
"""

import argparse
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from landnote.processors.exam_bank import EXAM_DIR, MIN_PDF_TEXT, ocr_cache_path  # noqa: E402

DPI = 250
MIN_SCORE = 0.5  # 低於此信心值多半是印章、框線之類的雜訊


def scanned_pdfs() -> list:
    """抽不到文字、但打得開的 PDF（損毀檔無法 OCR，略過）。"""
    import pymupdf

    out = []
    for folder in sorted(p for p in EXAM_DIR.iterdir() if p.is_dir() and p.name != "合併後PDF檔案"):
        for pdf in sorted(folder.glob("*.pdf")):
            try:
                with pymupdf.open(pdf) as doc:
                    if len("".join(page.get_text() for page in doc).strip()) < MIN_PDF_TEXT:
                        out.append(pdf)
            except Exception as e:  # 損毀檔
                print(f"略過無法開啟的檔案 {pdf.name}：{e}")
    return out


GOOD_SCORE = 0.8
# 偵測參數沒有一組每頁都最好：預設值會整行漏掉行首是括號或題號的行（偵測框只框到「（」），
# 放寬外擴比例能找回這些行，卻會在行距密的頁面吃掉別行。所以每頁各組都跑，取結果最好的一組
DET_VARIANTS = [
    {"Det.limit_side_len": 1600, "Det.limit_type": "max"},
    {"Det.limit_side_len": 1600, "Det.limit_type": "max", "Det.unclip_ratio": 2.0},
    {"Det.limit_side_len": 1200, "Det.limit_type": "max"},
    {"Det.limit_side_len": 1600, "Det.limit_type": "max", "Det.model_type": "mobile"},
]


def _page_quality(txts: list, scores: list) -> int:
    """高信心文字的總字數：漏行、亂碼（「（）（）」）都會讓它變少。"""
    return sum(len(t) for t, s in zip(txts, scores, strict=True) if s >= GOOD_SCORE)


def ocr_pdf(pdf: Path, engines: list) -> Tuple[str, Counter]:
    """逐頁用每組引擎辨識，取品質最高者；回傳 (文字, 各組被選中的頁數)。"""
    import pymupdf

    pages, picked = [], Counter()
    with pymupdf.open(pdf) as doc:
        for page in doc:
            img = page.get_pixmap(dpi=DPI).tobytes("png")
            results = []
            for i, engine in enumerate(engines):
                res = engine(img)
                txts, scores = list(res.txts or []), list(res.scores or [])
                results.append((_page_quality(txts, scores), -i, txts, scores))
            quality, neg_i, txts, scores = max(results)
            picked[-neg_i] += 1
            pages.append("\n".join(t for t, s in zip(txts, scores, strict=True) if s >= MIN_SCORE))
    return "\n".join(pages) + "\n", picked


def report_pending() -> None:
    """列出還沒有 OCR 快取的掃描檔；在 GitHub Actions 中另寫 warning 註記與執行摘要。不改變結束碼。"""
    pending = [p for p in scanned_pdfs() if not ocr_cache_path(p).exists()]
    in_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    if not pending:
        print("沒有待 OCR 的掃描檔")
        return
    print(f"有 {len(pending)} 份掃描檔還沒有 OCR 快取（逐題讀只會提供原卷連結）：")
    for pdf in pending:
        rel = f"{pdf.parent.name}/{pdf.name}"
        print(f"  {rel}")
        if in_actions:
            print(f"::warning title=掃描檔待 OCR::{rel}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"## 掃描檔待 OCR（{len(pending)} 份）\n\n"
                    "這些考卷抽不到文字，逐題讀暫時只提供原卷連結。請在本機執行：\n\n"
                    "```bash\nuv run --project landnotev3 --with pymupdf --with \"rapidocr>=3\" --with onnxruntime "
                    "python landnotev3/scripts/ocr_scanned.py\n```\n\n"
                    "並提交 `landnotev3/data/exam_ocr/`，下次每月更新就會自動拆題。\n\n"
                    + "".join(f"- `{p.parent.name}/{p.name}`\n" for p in pending))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="已有快取也重新辨識")
    parser.add_argument("--limit", type=int, default=0, help="最多處理幾份（測試用）")
    parser.add_argument("--check", action="store_true", help="只列出待 OCR 的掃描檔，不辨識")
    args = parser.parse_args()
    if args.check:
        report_pending()
        return

    from rapidocr import LangDet, LangRec, ModelType, OCRVersion, RapidOCR

    base = {
        "Det.ocr_version": OCRVersion.PPOCRV5, "Det.lang_type": LangDet.CH, "Det.model_type": ModelType.SERVER,
        "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.lang_type": LangRec.CH, "Rec.model_type": ModelType.SERVER,
        "Global.text_score": 0.0,  # 信心值改由 MIN_SCORE 自行過濾
    }
    engines = [RapidOCR(params={**base, **{k: ModelType.MOBILE if v == "mobile" else v for k, v in variant.items()}})
               for variant in DET_VARIANTS]
    todo = [p for p in scanned_pdfs() if args.force or not ocr_cache_path(p).exists()]
    if args.limit:
        todo = todo[:args.limit]
    print(f"待辨識 {len(todo)} 份")
    for i, pdf in enumerate(todo, 1):
        start = time.time()
        text, picked = ocr_pdf(pdf, engines)
        out = ocr_cache_path(pdf)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"[{i}/{len(todo)}] {pdf.parent.name}/{pdf.name}：{len(text)} 字，"
              f"{time.time() - start:.0f} 秒，各頁採用參數組 {dict(sorted(picked.items()))}", flush=True)


if __name__ == "__main__":
    main()
