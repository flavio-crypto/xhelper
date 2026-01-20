import fitz  # PyMuPDF

def extract_text_from_pdf(pdf_path: str, max_pages: int = 5) -> str:
    """
    Legge un PDF da un percorso file locale e restituisce il testo grezzo.
    """
    try:
        doc = fitz.open(pdf_path)
        text_content = []
        
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            text = page.get_text()
            clean_text = " ".join(text.split()) 
            text_content.append(f"--- PAGINA {i+1} ---\n{clean_text}")
            
        doc.close()
        return "\n\n".join(text_content)
    
    except Exception as e:
        print(f"Errore lettura PDF {pdf_path}: {e}")
        return ""

def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """
    Estrae testo da un file PDF direttamente dalla memoria (bytes).
    Utile per i file scaricati dal web senza salvarli su disco.
    """
    try:
        # Apre il PDF direttamente dai bytes usando lo stream
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            text_content = []
            # Leggiamo tutte le pagine (o metti un limitatore se vuoi)
            for page in doc:
                text_content.append(page.get_text())
            
            return "\n".join(text_content)
    except Exception as e:
        print(f"Errore parsing PDF bytes: {e}")
        return ""