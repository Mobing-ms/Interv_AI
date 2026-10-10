import os
import re
import io
import zipfile
from typing import Tuple, Optional
import pypdf
import pdfplumber
import docx

class CVValidationError(Exception):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def validate_cv_file(file_bytes: bytes, filename: str) -> str:
    """
    Validates file extension, magic bytes/MIME, size, encryption, and corruption.
    Returns detected file type: 'pdf' or 'docx'.
    Raises CVValidationError on any validation failure.
    """
    file_size = len(file_bytes)

    # 1. Check if empty
    if file_size == 0:
        raise CVValidationError("UNREADABLE", "The uploaded file is empty.")

    # 2. Check maximum size (5 MB)
    max_size = 5 * 1024 * 1024
    if file_size > max_size:
        raise CVValidationError("TOO_LARGE", f"File size ({file_size / (1024*1024):.2f} MB) exceeds the 5 MB limit.")

    # 3. Check extension
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".pdf", ".docx"):
        raise CVValidationError("UNSUPPORTED_TYPE", "Only PDF and DOCX files are supported.")

    # 4. Check magic bytes & format integrity
    if ext == ".pdf":
        # Check PDF header
        if not file_bytes.startswith(b"%PDF-"):
            raise CVValidationError("UNSUPPORTED_TYPE", "File is not a valid PDF document.")

        try:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            if reader.is_encrypted:
                raise CVValidationError("ENCRYPTED", "The PDF file is password-protected or encrypted.")
            # Verify we can read page count
            _ = len(reader.pages)
        except CVValidationError:
            raise
        except Exception as e:
            raise CVValidationError("UNREADABLE", f"The PDF file is corrupted and could not be read: {str(e)}")

        return "pdf"

    elif ext == ".docx":
        # Check DOCX zip magic bytes
        if not file_bytes.startswith(b"PK\x03\x04"):
            raise CVValidationError("UNSUPPORTED_TYPE", "File is not a valid DOCX document.")

        try:
            # Check zip contents for word document
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                namelist = z.namelist()
                if "word/document.xml" not in namelist:
                    raise CVValidationError("UNSUPPORTED_TYPE", "The file is not a valid Microsoft Word document.")
            # Verify python-docx can open it
            _ = docx.Document(io.BytesIO(file_bytes))
        except CVValidationError:
            raise
        except Exception as e:
            raise CVValidationError("UNREADABLE", f"The DOCX file is corrupted and could not be read: {str(e)}")

        return "docx"

    raise CVValidationError("UNSUPPORTED_TYPE", "Only PDF and DOCX files are supported.")


def clean_extracted_text(raw_text: str) -> str:
    """
    Cleans raw text layout:
    - Merges broken hyphenated lines
    - Removes standalone page numbers
    - Normalizes spacing while preserving section headings
    """
    if not raw_text:
        return ""

    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")

    # 1. Merge hyphenated words at line breaks (e.g. "experi-\nence" -> "experience")
    text = re.sub(r'(\b[A-Za-z]+)-\n([A-Za-z]+\b)', r'\1\2', text)

    # 2. Remove standalone page numbers (e.g. "Page 1 of 2", "1 / 3", or solitary line numbers)
    text = re.sub(r'(?i)^\s*(?:page\s+\d+(?:\s*(?:of|/)\s*\d+)?|\d+\s*/\s*\d+)\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\s*$', '', text, flags=re.MULTILINE)

    # 3. Clean consecutive empty lines (leave at most 2 newlines)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 4. Clean trailing whitespace per line
    lines = [line.strip() for line in text.split('\n')]
    
    # 5. Merge soft line breaks within sentences (lines not ending with sentence punctuation or headings)
    cleaned_lines = []
    heading_patterns = [
        r'^[A-Z\s]{3,30}$',  # All caps headings e.g. "WORK EXPERIENCE"
        r'^(?:Education|Experience|Skills|Projects|Summary|Certifications|Achievements|Publications|Contact|Awards):?$',
    ]

    for line in lines:
        if not line:
            cleaned_lines.append("")
            continue
        cleaned_lines.append(line)

    result = "\n".join(cleaned_lines).strip()
    return re.sub(r'\n{3,}', '\n\n', result)


def extract_text_from_pdf(file_path: str) -> str:
    """Extracts text and tables from PDF with OCR fallback for scanned pages."""
    text_parts = []
    has_text = False

    try:
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                # 1. Extract regular text
                page_text = page.extract_text() or ""
                
                # 2. Extract tables
                tables = page.extract_tables() or []
                table_texts = []
                for table in tables:
                    for row in table:
                        row_cells = [str(cell).strip() for cell in row if cell is not None]
                        if any(row_cells):
                            table_texts.append(" | ".join(row_cells))

                combined_page = page_text
                if table_texts:
                    combined_page += "\n" + "\n".join(table_texts)

                if combined_page.strip():
                    text_parts.append(combined_page)
                    has_text = True
    except Exception as e:
        raise CVValidationError("UNREADABLE", f"Error reading PDF: {str(e)}")

    full_text = "\n\n".join(text_parts).strip()

    # If text is minimal (< 50 chars), trigger OCR fallback for scanned PDF
    if len(full_text) < 50:
        ocr_text = try_ocr_pdf_fallback(file_path)
        if ocr_text and len(ocr_text) > len(full_text):
            full_text = ocr_text

    return clean_extracted_text(full_text)


def try_ocr_pdf_fallback(file_path: str) -> str:
    """OCR fallback using pytesseract or image rendering if available."""
    try:
        import pytesseract
        import pypdfium2

        pdf = pypdfium2.PdfDocument(file_path)
        ocr_results = []
        for page_idx in range(len(pdf)):
            page = pdf[page_idx]
            pil_image = page.render(scale=2.0).to_pil_image()
            try:
                txt = pytesseract.image_to_string(pil_image)
                if txt.strip():
                    ocr_results.append(txt)
            except Exception:
                # Tesseract executable might not be installed in system PATH
                pass
        return "\n\n".join(ocr_results).strip()
    except Exception:
        return ""


def extract_text_from_docx(file_path: str) -> str:
    """Extracts text, headers, and tables from DOCX document."""
    try:
        doc = docx.Document(file_path)
        text_parts = []

        # 1. Extract headers from sections
        for section in doc.sections:
            header = section.header
            if header:
                for hp in header.paragraphs:
                    if hp.text.strip():
                        text_parts.append(hp.text.strip())

        # 2. Extract paragraphs
        for p in doc.paragraphs:
            if p.text.strip():
                text_parts.append(p.text.strip())

        # 3. Extract tables
        for table in doc.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    text_parts.append(" | ".join(cells))

        full_text = "\n\n".join(text_parts).strip()
        return clean_extracted_text(full_text)
    except Exception as e:
        raise CVValidationError("UNREADABLE", f"Error reading DOCX: {str(e)}")


def extract_cv_text(file_path: str, file_type: str) -> str:
    """Route extraction to appropriate handler."""
    if file_type == "pdf":
        return extract_text_from_pdf(file_path)
    elif file_type == "docx":
        return extract_text_from_docx(file_path)
    else:
        raise CVValidationError("UNSUPPORTED_TYPE", f"Unsupported file type: {file_type}")
