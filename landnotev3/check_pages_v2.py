import requests
from bs4 import BeautifulSoup
import re

def get_page_articles(pno, page_no):
    url = f"https://real-estate.get.com.tw/Columns/journal.aspx?no=1282&pno={pno}&page_no={page_no}"
    try:
        r = requests.get(url, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        links = soup.select('a[href*="detail.aspx?no="]')
        articles = []
        for l in links:
            no_match = re.search(r'no=(\d+)', l.get('href', ''))
            if no_match:
                articles.append({'title': l.text.strip(), 'no': no_match.group(1)})
        return articles
    except:
        return []

print("Checking pno=51121 pages 20-30:")
for p in range(20, 31):
    articles = get_page_articles("51121", p)
    if articles:
        # Get date of the first non-pinned article
        first_real = next((a for a in articles if a['no'] != '915284'), None)
        if first_real:
            dr = requests.get(f"https://real-estate.get.com.tw/Columns/detail.aspx?no={first_real['no']}")
            ds = BeautifulSoup(dr.text, 'html.parser')
            dm = re.search(r'(\d{4}/\d{2}/\d{2})', ds.text)
            date = dm.group(1) if dm else "Unknown"
            print(f"Page {p}: {date} - {first_real['title']} (no={first_real['no']})")
        else:
            print(f"Page {p}: Only pinned article found")
    else:
        print(f"Page {p}: No articles found")
