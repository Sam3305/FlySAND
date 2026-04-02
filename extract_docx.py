import zipfile
import xml.etree.ElementTree as ET
import sys

def extract_text(docx_path):
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    text = []
    try:
        with zipfile.ZipFile(docx_path) as docx:
            xml_content = docx.read('word/document.xml')
            tree = ET.fromstring(xml_content)
            for paragraph in tree.iter(f"{{{ns['w']}}}p"):
                texts = [node.text for node in paragraph.iter(f"{{{ns['w']}}}t") if node.text]
                if texts:
                    text.append(''.join(texts))
        return '\n'.join(text)
    except Exception as e:
        return str(e)

if __name__ == '__main__':
    content = extract_text(sys.argv[1])
    with open('extracted.txt', 'w', encoding='utf-8') as f:
        f.write(content)
