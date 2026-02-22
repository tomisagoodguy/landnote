import requests
from bs4 import BeautifulSoup

url = 'https://real-estate.get.com.tw/Columns/journal.aspx?no=1282&pno=51121&page_no=24'
r = requests.get(url)
soup = BeautifulSoup(r.text, 'html.parser')
links = soup.find_all('a', href=True)
page_links = [l.get('href') for l in links if 'page_no=' in l.get('href')]
print("Page links found on Page 24:")
for pl in set(page_links):
    print(pl)
