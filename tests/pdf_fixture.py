"""Small real PDF for offline transport tests."""
def pdf_bytes(text='CV de prueba: experiencia verificada'):
    import pymupdf as fitz
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), text)
        return doc.tobytes()
PDF = pdf_bytes()
