
import re
import json
from pathlib import Path
from typing import List, Dict, Any

def parse_readme_grouped(file_path: Path) -> List[Dict[str, Any]]:
    """
    Parses the README_grouped.md file and returns a structured list of groups.
    """
    if not file_path.exists():
        print(f"File not found: {file_path}")
        return []

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')
    groups = []
    current_group = None

    # Regex patterns
    group_header_pattern = re.compile(r'^## 組 (\d+)：(.+)$')
    group_keywords_pattern = re.compile(r'^- 相關關鍵詞：(.+)$')
    article_pattern = re.compile(r'^- (\d{4}/\d{2}/\d{2}) \[(.*?)\]\((.*?)\) \(文章編號：(\d+)\) 關鍵詞：(.+)$')
    # 新版格式（grouper 依主題分組）：### <a name='topic-X'></a>📌 主題：X
    topic_header_pattern = re.compile(r'^### .*📌 主題：(.+)$')
    # 連結檔名可能含括號，如「(一).md」，故以 .md) 為結尾
    topic_article_pattern = re.compile(r'^- (\d{4}/\d{2}/\d{2}) \[(.*?)\]\((articles/(\d+)_.*?\.md)\)')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        topic_match = topic_header_pattern.match(line)
        if topic_match:
            if current_group:
                groups.append(current_group)
            topic = topic_match.group(1).strip()
            current_group = {
                "group_id": len(groups) + 1,
                "title": topic,
                "relevant_keywords": [topic],
                "articles": []
            }
            continue

        topic_article_match = topic_article_pattern.match(line)
        if topic_article_match and current_group:
            current_group["articles"].append({
                "date": topic_article_match.group(1),
                "title": topic_article_match.group(2),
                "link": topic_article_match.group(3),
                "article_id": topic_article_match.group(4),
                "keywords": list(current_group["relevant_keywords"]),
            })
            continue

        # Check for group header
        header_match = group_header_pattern.match(line)
        if header_match:
            # If there was a previous group, append it
            if current_group:
                groups.append(current_group)
            
            group_id = int(header_match.group(1))
            group_title = header_match.group(2).strip()
            current_group = {
                "group_id": group_id,
                "title": group_title,
                "relevant_keywords": [],
                "articles": []
            }
            continue

        # Check for group keywords
        keywords_match = group_keywords_pattern.match(line)
        if keywords_match and current_group:
            keywords_text = keywords_match.group(1).strip()
            keywords = [k.strip() for k in keywords_text.split(',')]
            current_group["relevant_keywords"] = keywords
            continue

        # Check for article entry
        article_match = article_pattern.match(line)
        if article_match and current_group:
            date = article_match.group(1)
            title = article_match.group(2)
            link = article_match.group(3)
            article_id = article_match.group(4)
            keywords_text = article_match.group(5)
            keywords = [k.strip() for k in keywords_text.split(',')]

            article = {
                "date": date,
                "title": title,
                "link": link,
                "article_id": article_id,
                "keywords": keywords
            }
            current_group["articles"].append(article)
            continue
            
    # Append the last group
    if current_group:
        groups.append(current_group)

    return groups

def main():
    from landnote.config import OUTPUT_DIR

    readme_path = OUTPUT_DIR / "README_grouped.md"
    output_path = OUTPUT_DIR / "grouped_articles.json"

    print(f"Reading from: {readme_path}")
    
    data = parse_readme_grouped(readme_path)
    
    print(f"Parsed {len(data)} groups.")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"Saved JSON to: {output_path}")

if __name__ == "__main__":
    main()
