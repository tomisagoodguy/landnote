import json
from collections import defaultdict

from pathlib import Path

# 由 `python -m landnote.utils.md_to_json` 產生
file_path = Path(__file__).parent / "data" / "real_estate_articles" / "grouped_articles.json"

with open(file_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

date_ranges = defaultdict(list)
for group in data:
    for article in group.get('articles', []):
        date = article.get('date')
        if date:
            year = date.split('/')[0]
            date_ranges[year].append(article.get('article_id'))

for year in sorted(date_ranges.keys()):
    ids = [int(i) for i in date_ranges[year] if i and i.isdigit()]
    if ids:
        print(f"Year {year}: {len(ids)} articles, IDs {min(ids)} to {max(ids)}")
    else:
        print(f"Year {year}: {len(date_ranges[year])} articles (non-numeric IDs)")
