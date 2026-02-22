import requests
from bs4 import BeautifulSoup
import re

def get_page_full_details(pno, page_no):
    url = f"https://real-estate.get.com.tw/Columns/journal.aspx?no=1282&pno={pno}&page_no={page_no}"
    r = requests.get(url)
    soup = BeautifulSoup(r.text, 'html.parser')
    links = soup.select('a[href*="detail.aspx?no="]')
    for l in links:
        title = l.text.strip()
        no = re.search(r'no=(\d+)', l.get('href', '')).group(1)
        # Fetch date for each
        dr = requests.get(f"https://real-estate.get.com.tw/Columns/detail.aspx?no={no}")
        ds = BeautifulSoup(dr.text, 'html.parser')
        dm = re.search(r'(\d{4}/\d{2}/\d{2})', ds.text)
        date = dm.group(1) if dm else "Unknown"
        print(f"Date: {date} | Title: {title} | No: {no}")

print("Page 24 Articles:")
get_page_full_details("51121", 24)
