"""文档文本提取（pdf / docx / txt），供合同解析与知识库上传共用。"""


def extract_text(path: str, file_type: str) -> str:
    """按文件类型提取全文文本；提取不到内容时抛 ValueError。"""
    if file_type == "txt":
        with open(path, encoding="utf-8") as f:
            text = f.read()
    elif file_type == "docx":
        from docx import Document
        doc = Document(path)
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    elif file_type == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        raise ValueError(f"不支持的文件类型：{file_type}")

    if not text.strip():
        raise ValueError("未能提取到文本（文件可能为扫描件或已加密）")
    return text
