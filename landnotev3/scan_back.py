import requests
from bs4 import BeautifulSoup
import re
import time

def get_info(no):
    try:
        r = requests.get(f'https://real-estate.get.com.tw/Columns/detail.aspx?no={no}', timeout=5)
        soup = BeautifulSoup(r.text, 'html.parser')
        dm = re.search(r'(\d{4}/\d{2}/\d{2})', soup.text)
        date = dm.group(1) if dm else 'N/A'
        title = soup.find('h1').text.strip() if soup.find('h1') else "No Title"
        # If title is generic, it might be a redirect or list page
        if "不動產期刊" in title or "許文昌/曾榮耀不動產全制霸" == title:
             return None
        return {'date': date, 'title': title}
    except:
        return None

print("Checking range 408000 to 409200:")
for no in range(409180, 409100, -5):
    info = get_info(no)
    if info:
        print(f"{no}: {info['date']} - {info['title']}")
    else:
        print(f"{no}: Not an article")
    time.sleep(0.5)
