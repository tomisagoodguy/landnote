import requests
from bs4 import BeautifulSoup

def check_journals():
    url = "https://real-estate.get.com.tw/Columns/"
    r = requests.get(url)
    soup = BeautifulSoup(r.text, 'html.parser')
    for a in soup.find_all('a', href=True):
        if 'journal' in a['href']:
            print(f"Link: {a.text.strip()} (HREF: {a['href']})")

check_journals()
