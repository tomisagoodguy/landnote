import requests
from bs4 import BeautifulSoup
import re
import time

def get_first_article_info(pno, page_no):
    url = f"https://real-estate.get.com.tw/Columns/journal.aspx?no=1282&pno={pno}&page_no={page_no}"
    try:
        resp = requests.get(url, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        links = soup.select('a[href*="detail.aspx?no="]')
        # Skip the first one if it's the pinned one (915284)
        for a in links:
            href = a.get('href', '')
            if 'no=915284' in href: continue
            
            # This is likely the first real article on the page
            article_no = re.search(r'no=(\d+)', href).group(1)
            # Fetch the article to get the date
            detail_url = f"https://real-estate.get.com.tw/Columns/detail.aspx?no={article_no}"
            dr = requests.get(detail_url, timeout=10)
            ds = BeautifulSoup(dr.text, 'html.parser')
            # Look for date (usually in a specific tag)
            # From previous learnings, it might be in a meta tag or specific div
            date_text = ds.text
            match = re.search(r'(\d{4}/\d{2}/\d{2})', date_text)
            date = match.group(1) if match else "Unknown"
            return {'no': article_no, 'date': date, 'title': a.text.strip()}
    except Exception as e:
        return None

for page in [20, 25, 30, 35, 40]:
    info = get_first_article_info("51121", page)
    if info:
        print(f"Page {page}: {info['date']} - {info['title']} (no={info['no']})")
    else:
        print(f"Page {page}: No info found")
    time.sleep(1)
