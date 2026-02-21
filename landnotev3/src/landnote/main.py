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

    # Command: site (Generate Website)
    site_parser = subparsers.add_parser("site", help="Generate static site structure")

    # Command: serve (Preview Website)
    serve_parser = subparsers.add_parser("serve", help="Preview website locally")

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
            crawler.run(max_pages=args.max_pages)

    elif args.command == "group":
        grouper = ArticleGrouper(similarity_threshold=args.threshold)
        grouper.run()

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
