import requests
import re
import time
from bs4 import BeautifulSoup

def get_article_info(no):
    url = f"https://real-estate.get.com.tw/Columns/detail.aspx?no={no}"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, 'html.parser')
        text = soup.get_text()
        
        # Extract date
        date_match = re.search(r'(\d{4}/\d{2}/\d{2})', text)
        date = date_match.group(1) if date_match else None
        
        # Extract title (usually in <h1> or specific class)
        title = "Unknown"
        h1 = soup.select_one('h1')
        if h1:
            title = h1.get_text().strip()
            
        return {'date': date, 'title': title}
    except:
        return None

# Probe range
print("Probing ID ranges for dates:")
for no in range(200000, 450000, 10000):
    info = get_article_info(no)
    if info and info['date']:
        print(f"ID {no}: {info['date']} - {info['title']}")
    else:
        print(f"ID {no}: Not found or no date")
    time.sleep(0.5)
