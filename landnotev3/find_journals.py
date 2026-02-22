import requests
from bs4 import BeautifulSoup
import time

def check_no(no):
    url = f"https://real-estate.get.com.tw/Columns/journal_list.aspx?no={no}"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code != 200: return False
        soup = BeautifulSoup(r.text, 'html.parser')
        title = soup.find('h1')
        if title and "不動產全制霸" in title.text:
            print(f"Found Journal: {no} - {title.text.strip()}")
            # Find pnos
            links = soup.select('a[href*="pno="]')
            for l in links:
                print(f"  PNO: {l.text.strip()} ({l.get('href')})")
            return True
        return False
    except:
        return False

print("Scanning for other journals:")
for no in range(1200, 1300):
    if check_no(no):
        pass
    time.sleep(0.1)
