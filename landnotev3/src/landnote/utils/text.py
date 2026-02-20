import re
from bs4 import BeautifulSoup

class TextUtils:
    @staticmethod
    def html_table_to_markdown(table: BeautifulSoup) -> str:
        """將 HTML 表格轉換為 Markdown 表格，並處理長文本換行"""
        try:
            # 收集所有表格數據
            headers = []
            data_rows = []

            # 尋找表頭行
            thead = table.find('thead')
            if thead:
                header_row = thead.find('tr')
                if header_row:
                    headers = [th.get_text().strip() for th in header_row.find_all(['th', 'td'])]

            # 如果沒有找到表頭，嘗試從第一行獲取
            if not headers and table.find('tr'):
                first_row = table.find('tr')
                if first_row.find('th'):
                    headers = [th.get_text().strip() for th in first_row.find_all('th')]
                else:
                    headers = [td.get_text().strip() for td in first_row.find_all('td')]
                    # 如果使用第一行作為表頭，從數據行中移除
                    data_rows = []

            # 收集數據行
            for tr in table.find_all('tr'):
                # 跳過已處理的表頭行
                if tr == table.find('tr') and not thead and headers == [td.get_text().strip() for td in tr.find_all('td')]:
                    continue

                row_data = []
                for td in tr.find_all(['td', 'th']):
                    # 處理合併單元格
                    colspan = int(td.get('colspan', 1))
                    cell_text = td.get_text().strip()
                    cell_text = re.sub(r'\s+', ' ', cell_text)
                    
                    # 處理長文本自動換行
                    cell_text = TextUtils.wrap_text(cell_text, 25)

                    # 添加單元格文本
                    row_data.append(cell_text)

                    # 如果有合併單元格，添加額外的空單元格
                    for _ in range(colspan - 1):
                        row_data.append('')

                if row_data and not (len(row_data) == len(headers) and all(cell == '' for cell in row_data)):
                    data_rows.append(row_data)

            # 如果仍然沒有表頭，創建默認表頭
            if not headers:
                max_cols = max(len(row) for row in data_rows) if data_rows else 0
                headers = [f"欄位 {i+1}" for i in range(max_cols)]

            # 確保所有數據行的列數與表頭一致
            for i in range(len(data_rows)):
                while len(data_rows[i]) < len(headers):
                    data_rows[i].append('')
                # 截斷過長的行
                data_rows[i] = data_rows[i][:len(headers)]

            # 生成 Markdown 表格
            md_table = []

            # 添加表頭
            md_table.append('| ' + ' | '.join(headers) + ' |')

            # 添加分隔行
            md_table.append('| ' + ' | '.join(['---' for _ in headers]) + ' |')

            # 添加數據行
            for row in data_rows:
                md_table.append('| ' + ' | '.join(row) + ' |')

            return '\n'.join(md_table)
        except Exception as e:
            # 這裡應該記錄日誌，但在工具函數中我們先返回錯誤訊息
            return f"*表格轉換失敗: {str(e)}*"

    @staticmethod
    def wrap_text(text: str, max_width: int = 30) -> str:
        """智能地將文本按照自然斷句點換行"""
        if len(text) <= max_width:
            return text
            
        # 嘗試在標點符號處換行
        punctuation = ['.', '，', '。', '；', '：', '、', '!', '?', '；', '：']
        wrapped_text = []
        current_chunk = ""
        
        for char in text:
            current_chunk += char
            
            # 如果當前塊達到最大寬度，尋找合適的換行點
            if len(current_chunk) >= max_width:
                # 尋找最後的標點符號位置
                last_punct = -1
                for p in punctuation:
                    pos = current_chunk.rfind(p)
                    if pos > last_punct:
                        last_punct = pos
                
                # 如果找到標點符號且不是在開頭，則在標點後換行
                if last_punct > 0 and last_punct < len(current_chunk) - 1:
                    wrapped_text.append(current_chunk[:last_punct+1])
                    current_chunk = current_chunk[last_punct+1:]
                else:
                    # 如果沒有找到合適的標點，則直接在最大寬度處換行
                    wrapped_text.append(current_chunk)
                    current_chunk = ""
        
        # 添加剩餘的文本
        if current_chunk:
            wrapped_text.append(current_chunk)
            
        return "<br>".join(wrapped_text)

    @staticmethod
    def format_content(soup: BeautifulSoup) -> str:
        """格式化文章內容，處理換行和縮排，並自動處理列表項目"""
        allowed_tags = {'p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li'}
        # 複製一份 soup 以免修改原始物件
        import copy
        soup = copy.copy(soup)
        
        for tag in soup.find_all():
            if tag.name not in allowed_tags:
                tag.unwrap()

        # 處理段落和標題
        for p in soup.find_all('p'):
            text = p.get_text().strip()
            if text:
                p.string = ' '.join(text.split())
                p.append('\n\n')

        for h in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            level = int(h.name[1])
            prefix = '#' * level + ' '
            h.string = f'\n{prefix}{h.get_text().strip()}\n'

        # 處理已有的列表
        for li in soup.find_all('li'):
            indent = '  '
            if li.parent.name == 'ol':
                index = len(li.find_previous_siblings('li')) + 1
                li.insert(0, f'{indent}{index}. ')
            else:
                li.insert(0, f'{indent}• ')
            li.append('\n')

        # 獲取基本文本內容
        content = soup.get_text()

        # 自動檢測和處理未標記的列表項目
        lines = content.split('\n')
        processed_lines = []

        list_patterns = [
            # 數字列表: 1. 2. 3.
            (r'^(\d+)\.(.+)$', lambda m: f"  {m.group(1)}. {m.group(2).strip()}"),
            # 中文數字列表: 一、二、三、
            (r'^([一二三四五六七八九十百千]+)、(.+)$', lambda m: f"  • {m.group(1)}、{m.group(2).strip()}"),
            # 帶括號的數字: (1) (2) (3)
            (r'^\((\d+)\)(.+)$', lambda m: f"  • ({m.group(1)}) {m.group(2).strip()}"),
            # 帶括號的中文數字: (一) (二) (三)
            (r'^\(([一二三四五六七八九十百千]+)\)(.+)$', lambda m: f"  • ({m.group(1)}) {m.group(2).strip()}"),
            # 英文字母列表: A. B. C. 或 A B C
            (r'^([A-Za-z])\.?(.+)$', lambda m: f"  • {m.group(1)}. {m.group(2).strip()}")
        ]

        for line in lines:
            line = line.strip()
            if not line:
                processed_lines.append('')
                continue

            # 檢查是否匹配任何列表模式
            matched = False
            for pattern, replacement in list_patterns:
                if re.match(pattern, line):
                    processed_line = re.sub(pattern, replacement, line)
                    processed_lines.append(processed_line)
                    matched = True
                    break

            # 如果沒有匹配任何列表模式，保持原樣
            if not matched:
                processed_lines.append(line)

        # 合併處理後的行
        content = '\n'.join(processed_lines)

        # 清理多餘的空白和換行
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = re.sub(r'[ \t]+', ' ', content)
        content = re.sub(r' *\n *', '\n', content)

        # 將內容分段並重新組合
        paragraphs = [p.strip() for p in content.split('\n') if p.strip()]
        formatted_content = '\n\n'.join(paragraphs)

        return formatted_content.strip()
