import zipfile
import xml.etree.ElementTree as ET

def extract_text_from_docx(docx_path):
    try:
        with zipfile.ZipFile(docx_path) as docx:
            xml_content = docx.read('word/document.xml')
            tree = ET.fromstring(xml_content)
            
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            
            text = []
            for paragraph in tree.findall('.//w:p', ns):
                para_text = []
                for run in paragraph.findall('.//w:r', ns):
                    for text_node in run.findall('.//w:t', ns):
                        if text_node.text:
                            para_text.append(text_node.text)
                if para_text:
                    text.append(''.join(para_text))
            
            return '\n'.join(text)
    except Exception as e:
        return f"Error: {e}"

print(extract_text_from_docx(r'c:\Users\RIYAN\Desktop\Ex\YoutubeEX\ytxprd-addition.docx'))
