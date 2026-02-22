import os
import shutil
import pandas as pd
from pathlib import Path
import re
from datetime import datetime
from tqdm import tqdm

def migrate_articles():
    # Paths
    old_base = Path(r'c:\Users\user\Documents\GitHub\landnote\landnotev3\real_estate_articles')
    new_base = Path(r'c:\Users\user\Documents\GitHub\landnote\landnotev3\data\real_estate_articles')
    
    old_articles_dir = old_base / "articles"
    new_articles_dir = new_base / "articles"
    old_images_dir = old_articles_dir / "images"
    new_images_dir = new_articles_dir / "images"
    
    # Ensure new directories exist
    new_articles_dir.mkdir(parents=True, exist_ok=True)
    new_images_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Migrating articles from {old_articles_dir} to {new_articles_dir}...")
    
    # 1. Copy Markdown files
    md_files = list(old_articles_dir.glob("*.md"))
    for f in tqdm(md_files, desc="Copying MD files"):
        dest = new_articles_dir / f.name
        if not dest.exists():
            shutil.copy2(f, dest)
            
    # 2. Copy Images
    if old_images_dir.exists():
        img_files = list(old_images_dir.glob("*.*"))
        for f in tqdm(img_files, desc="Copying images"):
            dest = new_images_dir / f.name
            if not dest.exists():
                shutil.copy2(f, dest)

    print("Migration of files completed.")

def rebuild_excel():
    new_base = Path(r'c:\Users\user\Documents\GitHub\landnote\landnotev3\data\real_estate_articles')
    articles_dir = new_base / "articles"
    excel_path = new_base / "articles.xlsx"
    
    articles_data = []
    md_files = list(articles_dir.glob("*.md"))
    
    print(f"Rebuilding Excel from {len(md_files)} files...")
    
    for f in tqdm(md_files, desc="Parsing MD files"):
        try:
            with open(f, 'r', encoding='utf-8') as file:
                content = file.read()
            
            # Extract metadata using regex
            title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
            no_match = re.search(r'文章編號：(\d+)', content)
            author_match = re.search(r'作者：(.+)', content)
            date_match = re.search(r'發布日期：(\d{4}/\d{2}/\d{2})', content)
            url_match = re.search(r'原文連結：\[閱讀原文\]\((.+)\)', content)
            crawl_match = re.search(r'爬取時間：(.+)', content)
            keywords_match = re.search(r'關鍵詞：(.+)', content)
            
            articles_data.append({
                '文章編號': int(no_match.group(1)) if no_match else 0,
                '標題': title_match.group(1).strip() if title_match else f.stem,
                '作者': author_match.group(1).strip() if author_match else "Unknown",
                '日期': date_match.group(1) if date_match else "Unknown",
                'URL': url_match.group(1) if url_match else "",
                '爬取時間': crawl_match.group(1).strip() if crawl_match else "",
                '關鍵詞': keywords_match.group(1).strip() if keywords_match else ""
            })
        except Exception as e:
            print(f"Error parsing {f}: {e}")
            
    df = pd.DataFrame(articles_data)
    # Sort by ID descending
    df = df.sort_values(by='文章編號', ascending=False)
    df.to_excel(excel_path, index=False)
    print(f"Excel rebuilt with {len(df)} entries at {excel_path}")

if __name__ == "__main__":
    migrate_articles()
    rebuild_excel()
