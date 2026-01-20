# app/services/pdf_parser.py
import fitz  # PyMuPDF

def extract_text_from_pdf(pdf_path: str, max_pages: int = 5) -> str:
    """
    Legge un PDF e restituisce il testo grezzo.
    Limita a max_pages per evitare di mandare al LLM manuali di posa di 50 pagine.
    """
    try:
        doc = fitz.open(pdf_path)
        text_content = []
        
        # Iteriamo sulle pagine (fino al limite)
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            text = page.get_text()
            # Pulizia base: rimuove spazi multipli e ritorni a capo eccessivi
            clean_text = " ".join(text.split()) 
            text_content.append(f"--- PAGINA {i+1} ---\n{clean_text}")
            
        doc.close()
        return "\n\n".join(text_content)
    
    except Exception as e:
        print(f"Errore lettura PDF {pdf_path}: {e}")
        return ""