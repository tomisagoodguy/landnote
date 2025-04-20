#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import sys
import logging
from pathlib import Path
import time

# 導入原有的兩個類
from getlandarticle import ArticleScraper
from group_similar_titles import ArticleGrouper


def setup_logger(name, log_dir="logs"):
    """設定日誌系統"""
    logger = logging.getLogger(name)
    logger.handlers = []
    logger.setLevel(logging.INFO)

    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(parents=True, exist_ok=True)

    from datetime import datetime
    log_file = log_dir_path / \
        f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    handlers = [
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    for handler in handlers:
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def crawl_command(args):
    """執行爬蟲功能"""
    logger = setup_logger("crawler")
    logger.info(f"開始執行爬蟲 (模式: {args.scan_mode})")

    scraper = ArticleScraper(
        scan_mode=args.scan_mode,
        check_specific=args.check_specific,
        data_file=args.data_file
    )

    if args.buffer_size:
        scraper.buffer_size = args.buffer_size

    if args.reprocess:
        article_numbers = None
        if args.article_numbers:
            article_numbers = [num.strip()
                               for num in args.article_numbers.split(',')]
        scraper.reprocess_articles(article_numbers)
    else:
        if scraper.check_specific:
            specific_articles = scraper.load_specific_articles()
            for article_no in specific_articles:
                scraper.check_specific_article(article_no)
        scraper.run()

    logger.info("爬蟲功能執行完成")

    # 如果設置了自動分組參數，則自動執行分組功能
    if args.auto_group:
        logger.info("檢測到自動分組標誌，即將開始分組文章...")
        time.sleep(1)  # 暫停一秒，讓日誌更清晰
        return group_command(args)

    return 0


def group_command(args):
    """執行文章分組功能"""
    logger = setup_logger("grouper")
    logger.info("開始執行文章分組功能")

    grouper = ArticleGrouper(
        articles_dir=args.articles_dir,
        output_dir=args.output_dir
    )

    if hasattr(args, 'similarity_threshold') and args.similarity_threshold:
        grouper.similarity_threshold = args.similarity_threshold

    grouper.run()

    logger.info("文章分組功能執行完成")
    return 0


def auto_command(args):
    """自動執行爬蟲和分組功能"""
    logger = setup_logger("auto")
    logger.info("開始自動執行爬蟲和分組功能")

    # 先執行爬蟲
    result = crawl_command(args)
    if result != 0:
        logger.error("爬蟲功能執行失敗，中止自動流程")
        return result

    logger.info("爬蟲完成，即將開始分組...")
    time.sleep(2)  # 暫停兩秒，讓日誌更清晰

    # 再執行分組
    result = group_command(args)
    if result != 0:
        logger.error("分組功能執行失敗")
        return result

    logger.info("自動流程全部完成")
    return 0


def main():
    """主函數，處理命令行參數"""
    # 創建頂層解析器
    parser = argparse.ArgumentParser(
        description="房地產文章爬取與分組工具",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", help="選擇要執行的功能")

    # 爬蟲子命令
    crawl_parser = subparsers.add_parser("crawl", help="爬取房地產文章")
    crawl_parser.add_argument('--scan_mode', type=str, default='all',
                              choices=['all', 'recent'], help="掃描模式: 'all' 或 'recent'")
    crawl_parser.add_argument('--check_specific', type=lambda x: (str(x).lower() == 'true'),
                              default=True, help="檢查特定文章: True 或 False")
    crawl_parser.add_argument('--buffer_size', type=int, default=500,
                              help="文章編號範圍緩衝區大小")
    crawl_parser.add_argument('--reprocess', action='store_true',
                              help="重新處理現有文章以修復表格格式")
    crawl_parser.add_argument('--article_numbers', type=str, default=None,
                              help="要重新處理的文章編號，以逗號分隔")
    crawl_parser.add_argument('--data_file', type=str, default="articles.xlsx",
                              help="存儲文章數據的Excel文件路徑")
    crawl_parser.add_argument('--auto_group', action='store_true',
                              help="爬取完成後自動進行文章分組")
    crawl_parser.add_argument('--articles_dir', type=str, default="real_estate_articles/articles",
                              help="文章目錄路徑 (用於自動分組)")
    crawl_parser.add_argument('--output_dir', type=str, default="real_estate_articles",
                              help="輸出目錄路徑 (用於自動分組)")
    crawl_parser.add_argument('--similarity_threshold', type=int, default=80,
                              help="標題相似度閾值 (0-100) (用於自動分組)")

    # 分組子命令
    group_parser = subparsers.add_parser("group", help="對爬取的文章進行分組和生成索引")
    group_parser.add_argument('--articles_dir', type=str, default="real_estate_articles/articles",
                              help="文章目錄路徑")
    group_parser.add_argument('--output_dir', type=str, default="real_estate_articles",
                              help="輸出目錄路徑")
    group_parser.add_argument('--similarity_threshold', type=int, default=80,
                              help="標題相似度閾值 (0-100)")

    # 自動執行子命令 (爬取+分組)
    auto_parser = subparsers.add_parser("auto", help="自動執行爬取和分組功能")
    auto_parser.add_argument('--scan_mode', type=str, default='recent',
                             choices=['all', 'recent'], help="掃描模式: 'all' 或 'recent'")
    auto_parser.add_argument('--check_specific', type=lambda x: (str(x).lower() == 'true'),
                             default=True, help="檢查特定文章: True 或 False")
    auto_parser.add_argument('--buffer_size', type=int, default=500,
                             help="文章編號範圍緩衝區大小")
    auto_parser.add_argument('--data_file', type=str, default="articles.xlsx",
                             help="存儲文章數據的Excel文件路徑")
    auto_parser.add_argument('--articles_dir', type=str, default="real_estate_articles/articles",
                             help="文章目錄路徑")
    auto_parser.add_argument('--output_dir', type=str, default="real_estate_articles",
                             help="輸出目錄路徑")
    auto_parser.add_argument('--similarity_threshold', type=int, default=80,
                             help="標題相似度閾值 (0-100)")

    # 解析命令行參數
    args = parser.parse_args()

    # 根據子命令執行相應的功能
    if args.command == "crawl":
        return crawl_command(args)
    elif args.command == "group":
        return group_command(args)
    elif args.command == "auto":
        return auto_command(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())


''''
# 爬取最新文章並自動分組
python realestate_tool.py crawl --scan_mode recent --auto_group

# 爬取所有文章並自動分組，同時設置分組參數
python realestate_tool.py crawl --scan_mode all --auto_group --similarity_threshold 85

'''


