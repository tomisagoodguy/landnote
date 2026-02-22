import requests
from bs4 import BeautifulSoup

import re

def get_nos(url):
    resp = requests.get(url)
    soup = BeautifulSoup(resp.text, 'html.parser')
    links = soup.select('a[href*="detail.aspx?no="]')
    nos = []
    for a in links:
        if match := re.search(r'no=(\d+)', a.get('href', '')):
            nos.append(match.group(1))
    return nos

p1 = get_nos('https://real-estate.get.com.tw/Columns/journal.aspx?no=1282&pno=51121&page_no=1')
p10 = get_nos('https://real-estate.get.com.tw/Columns/journal.aspx?no=1282&pno=51121&page_no=10')

print(f"Page 1 nos: {p1}")
print(f"Page 10 nos: {p10}")
print(f"Intersection count: {len(set(p1) & set(p10))}")
