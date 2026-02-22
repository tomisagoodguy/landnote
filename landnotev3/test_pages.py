import requests
from bs4 import BeautifulSoup
import re

def check_page(pno, page_no):
    url = f"https://real-estate.get.com.tw/Columns/journal.aspx?no=1282&pno={pno}&page_no={page_no}"
    try:
        resp = requests.get(url, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        articles = []
        for link in soup.select('a[href*="detail.aspx?no="]'):
            title = link.text.strip()
            href = link.get('href', '')
            if match := re.search(r'no=(\d+)', href):
                articles.append({'title': title, 'no': match.group(1)})
        return articles
    except Exception as e:
        print(f"Error: {e}")
        return []

for pno in ["51120", "51121"]:
    print(f"Checking pno={pno}")
    for page in [1, 10, 20, 30, 40, 50, 60, 70, 80]:
        articles = check_page(pno, page)
        if articles:
            print(f"  Page {page}: {len(articles)} articles found. First title: {articles[0]['title']}")
        else:
            print(f"  Page {page}: No articles found.")
