import argparse
import sys
from pathlib import Path

# Add project root to sys.path to ensure modules can be found
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from landnote.crawlers.article import ArticleCrawler
from landnote.crawlers.exam_land import LandExamCrawler
from landnote.crawlers.exam_law import LawExamCrawler
from landnote.crawlers.jasper_crawler import JasperCrawler
from landnote.processors.grouper import ArticleGrouper

def main():
    parser = argparse.ArgumentParser(description="Landnote Unified Crawler CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: articles (Real Estate Articles)
    articles_parser = subparsers.add_parser("articles", help="Crawl real estate articles")
    articles_parser.add_argument("--update", action="store_true", help="Only update new articles")
    articles_parser.add_argument("--auto-group", action="store_true", help="Run grouping after crawling")

    # Command: jasper (Jasper Articles)
    jasper_parser = subparsers.add_parser("jasper", help="Crawl Jasper articles")
    jasper_parser.add_argument("--update", action="store_true", help="Only update new articles")
    
    # Command: exams (Exams)
    exams_parser = subparsers.add_parser("exams", help="Crawl exam papers")
    exams_parser.add_argument("--type", choices=["land", "law"], required=True, help="Type of exam (land or law)")
    exams_parser.add_argument("--years", type=int, default=10, help="Number of years to crawl (for land exams)")
    exams_parser.add_argument("--update", action="store_true", help="Only update new exams")
    exams_parser.add_argument("--max-pages", type=int, default=None, help="Max pages to crawl (for law exams)")

    # Command: group (Group Articles)
    group_parser = subparsers.add_parser("group", help="Group processed articles")
    group_parser.add_argument("--threshold", type=int, default=80, help="Similarity threshold (0-100)")

    # Command: exambank (估價師考古題主題題庫，需 pymupdf)
    subparsers.add_parser("exambank", help="Build appraiser exam question bank JSON (requires pymupdf)")

    # Command: laws (從全國法規資料庫更新修法時間軸，供法規時效提醒)
    subparsers.add_parser("laws", help="Download law amendment histories from law.moj.gov.tw")

    # Command: obsidian (把逐題讀考古題匯出成 Obsidian vault；需先跑 site 產生文章)
    obsidian_parser = subparsers.add_parser("obsidian", help="Export exam questions as an Obsidian vault")
    obsidian_parser.add_argument("--out", type=Path, default=Path.home() / "Documents" / "Landnote考古題",
                                 help="Vault directory (default: ~/Documents/Landnote考古題)")
    obsidian_parser.add_argument("--zip", type=Path, default=None,
                                 help="Write a zip for download instead of a vault directory (CI uses this)")

    # Command: site (Generate Website)
    subparsers.add_parser("site", help="Generate static site structure")

    # Command: serve (Preview Website)
    subparsers.add_parser("serve", help="Preview website locally")

    args = parser.parse_args()

    if args.command == "articles":
        mode = "update" if args.update else "all"
        crawler = ArticleCrawler(mode=mode)
        crawler.run()
        
        if args.auto_group:
            print("Running auto-grouping...")
            grouper = ArticleGrouper()
            grouper.run()
            
    elif args.command == "jasper":
        mode = "update" if args.update else "all"
        crawler = JasperCrawler(mode=mode)
        crawler.run()
        
    elif args.command == "exams":
        if args.type == "land":
            crawler = LandExamCrawler(debug=True)
            crawler.run(years=args.years, only_update=args.update)
            
        elif args.type == "law":
            crawler = LawExamCrawler(debug=True)
            crawler.run(max_pages=args.max_pages, only_update=args.update)

    elif args.command == "group":
        grouper = ArticleGrouper(similarity_threshold=args.threshold)
        grouper.run()

    elif args.command == "exambank":
        from landnote.processors import exam_bank
        out = exam_bank.build()
        if out is None:
            sys.exit("找不到估價師考古題 PDF，題庫未產生")
        print(f"Exam bank written to {out}")
        from landnote.processors import exam_reader
        readers = exam_reader.build()
        if not readers:
            sys.exit("找不到可逐題閱讀的考古題 PDF，閱讀版未產生")
        print("Exam reader written to " + ", ".join(str(r) for r in readers))

    elif args.command == "laws":
        from landnote.processors import law_timeline
        print(f"Law timeline written to {law_timeline.build()}")

    elif args.command == "obsidian":
        from landnote.processors import obsidian_vault
        docs = PROJECT_ROOT / "site_src" / "docs"
        posts = [docs / "blog" / "posts", docs / "jasper" / "posts"]
        if not posts[0].exists():
            sys.exit("找不到 site_src/docs/blog/posts，請先執行 main.py site 產生文章")
        target = args.zip or args.out
        counts = (obsidian_vault.export_zip(args.zip, posts) if args.zip
                  else obsidian_vault.export(args.out, posts))
        if counts is None:
            sys.exit("找不到逐題讀資料（data/exam_bank/*.json），請先執行 main.py exambank")
        print(f"Obsidian vault written to {target}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))

    elif args.command == "site":
        from landnote.processors.site_generator import SiteGenerator
        generator = SiteGenerator()
        generator.run()

    elif args.command == "serve":
        from landnote.processors.site_generator import SiteGenerator
        import subprocess
        
        # 1. Generate the site first
        print("Generating site content...")
        generator = SiteGenerator()
        generator.run()
        
        # 2. Serve it
        print("Starting local server...")
        print("Please open http://127.0.0.1:8000 in your browser")
        subprocess.run([sys.executable, "-m", "mkdocs", "serve"], cwd="site_src")
        
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
