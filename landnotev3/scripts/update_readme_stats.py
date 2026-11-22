"""依實際資料重算根目錄 README.md 的收錄數字。

README 中以標記包住要自動更新的數字，標記外的文字不動：

    <!-- stats:articles -->994 篇<!-- /stats -->
    <!-- stats:land_exams -->832 份<!-- /stats -->
    <!-- stats:land_subjects -->74 科<!-- /stats -->
    <!-- stats:subject=不動產估價理論 -->16 份<!-- /stats -->

只用標準函式庫，CI 兩個 workflow 都能直接執行。

Usage:
    python landnotev3/scripts/update_readme_stats.py          # 改寫 README
    python landnotev3/scripts/update_readme_stats.py --check  # 數字過期時 exit 1
"""

import argparse
import re
import sys
from pathlib import Path

LANDNOTE_DIR = Path(__file__).resolve().parent.parent
README_PATH = LANDNOTE_DIR.parent / "README.md"
ARTICLES_DIR = LANDNOTE_DIR / "data" / "real_estate_articles" / "articles"
LAND_EXAM_DIR = LANDNOTE_DIR / "地政考古題"
# 地政考古題底下不是科目的資料夾
NON_SUBJECT_DIRS = {"合併後PDF檔案", "__pycache__"}

MARKER_RE = re.compile(r"<!-- stats:(?P<key>[^ ]+?) -->(?P<value>.*?)<!-- /stats -->")


def count_subject_pdfs() -> dict[str, int]:
    """回傳 {科目資料夾名: PDF 份數}，只含至少一份 PDF 的科目。"""
    counts: dict[str, int] = {}
    for subject_dir in LAND_EXAM_DIR.iterdir():
        if not subject_dir.is_dir() or subject_dir.name in NON_SUBJECT_DIRS:
            continue
        n = sum(1 for _ in subject_dir.rglob("*.pdf"))
        if n:
            counts[subject_dir.name] = n
    return counts


def collect_stats() -> dict[str, str]:
    """計算所有可用的標記值。"""
    subjects = count_subject_pdfs()
    stats = {
        "articles": f"{sum(1 for _ in ARTICLES_DIR.glob('*.md')):,} 篇",
        "land_exams": f"{sum(subjects.values()):,} 份",
        "land_subjects": f"{len(subjects)} 科",
    }
    for name, n in subjects.items():
        stats[f"subject={name}"] = f"{n} 份"
    return stats


def render(text: str, stats: dict[str, str]) -> str:
    """把 README 內每個標記的值換成最新統計；未知的標記直接報錯。"""

    def replace(match: re.Match[str]) -> str:
        key = match.group("key")
        if key not in stats:
            raise KeyError(f"README 標記 stats:{key} 沒有對應的統計（科目資料夾改名或刪除？）")
        return f"<!-- stats:{key} -->{stats[key]}<!-- /stats -->"

    return MARKER_RE.sub(replace, text)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="只檢查，不寫入")
    args = parser.parse_args()

    original = README_PATH.read_text(encoding="utf-8")
    if not MARKER_RE.search(original):
        print("README.md 沒有任何 stats 標記")
        return 1
    updated = render(original, collect_stats())

    if updated == original:
        print("README 收錄數字已是最新")
        return 0
    if args.check:
        print("README 收錄數字過期，請執行 update_readme_stats.py")
        return 1
    README_PATH.write_text(updated, encoding="utf-8", newline="\n")
    print("README 收錄數字已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
