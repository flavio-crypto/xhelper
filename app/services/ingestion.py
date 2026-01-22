import json
from bs4 import BeautifulSoup
from app.services.crawler import fetch_url_content
from app.pdf_parser import extract_text_from_pdf_bytes
from app.llm import ask_qwen
from app.database import supabase

EDILIZIA_CATEGORIES = [
    "Isolanti Termici", "Impermeabilizzanti", "Cartongesso e Lastre",
    "Intonaci e Malte", "Adesivi e Sigillanti", "Pavimenti e Rivestimenti",
    "Vernici e Finiture", "Calcestruzzi e Cementi", "Laterizi e Blocchi",
    "Facciate e Cappotti", "Serramenti e Vetri", "Impianti HVAC"
]

import json
from bs4 import BeautifulSoup
from app.services.crawler import fetch_url_content
from app.pdf_parser import extract_text_from_pdf_bytes
from app.llm import ask_qwen
from app.database import supabase

EDILIZIA_CATEGORIES = [
    "Isolanti Termici", "Impermeabilizzanti", "Cartongesso e Lastre",
    "Intonaci e Malte", "Adesivi e Sigillanti", "Pavimenti e Rivestimenti",
    "Vernici e Finiture", "Calcestruzzi e Cementi", "Laterizi e Blocchi",
    "Facciate e Cappotti", "Serramenti e Vetri", "Impianti HVAC"
]

async def process_batch_item(manufacturer: str, product_name: str, url: str):
    print(f"⚙️ Processing (Volatile): {manufacturer} - {product_name}...")
    
    # 1. Gestione Azienda
    company_res = supabase.table("companies").select("id").ilike("name", manufacturer).execute()
    if company_res.data:
        company_id = company_res.data[0]['id']
    else:
        new_comp = supabase.table("companies").insert({"name": manufacturer}).execute()
        company_id = new_comp.data[0]['id']

    # 2. Check Esistenza (Solo warning)
    exists_warning = False
    try:
        prod_res = supabase.table("products").select("id").eq("company_id", company_id).ilike("name", product_name).execute()
        if prod_res.data:
            exists_warning = True
    except:
        pass

    # 3. Scaricamento & Gestione Errori Intelligente
    scraped_data = await fetch_url_content(url)
    
    if "error" in scraped_data:
        error_msg = str(scraped_data["error"])
        
        # CASO A: Link Sbagliato (404) -> STOP (Card Rossa)
        if "404" in error_msg or "Not Found" in error_msg:
            return {
                "status": "error", 
                "reason": "Link non valido (404). Verifica URL.", 
                "product": product_name
            }
        
        # CASO B: Anti-Bot (403) o Altri Errori -> FORZATURA (Card Verde "Cieca")
        # Creiamo la bozza con i dati del CSV, avvisando che l'AI non ha girato.
        else:
            print(f"⚠️ Scraping bloccato ({error_msg}), creo bozza manuale.")
            return {
                "status": "ready_to_load",
                "company_id": company_id,
                "company_name": manufacturer,
                "original_name": product_name,
                "final_name": product_name, # Usiamo il nome CSV
                "category": "Da Revisionare", # Non sappiamo la categoria
                "description": "⚠️ Analisi AI non disponibile (Accesso Web Negato). Caricare PDF manualmente.",
                "url_technical_sheet": url,
                "epd_url": None,
                "is_recycled": False,
                "exists_warning": exists_warning
            }

    # --- SE SIAMO QUI, IL DOWNLOAD È RIUSCITO ---

    # 4. Estrazione Testo
    text_content = ""
    if scraped_data["type"] == "pdf":
        text_content = extract_text_from_pdf_bytes(scraped_data["content"])
    else:
        soup = BeautifulSoup(scraped_data["text"], "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "form"]):
            tag.decompose()
        text_content = soup.get_text(separator="\n")
        text_content = "\n".join([line.strip() for line in text_content.splitlines() if line.strip()])
        text_content = text_content[:12000]

    # 5. Prompt AI
    prompt = f"""
    Sei un assistente per la catalogazione di materiali edili.
    Analizza il testo fornito.
    
    OBIETTIVI:
    1. Identifica il Nome Commerciale esatto.
    2. Classificalo in: {str(EDILIZIA_CATEGORIES)}.
    3. Rileva PRESENZA documentazione (EPD, Emissioni, Riciclato).
    
    Rispondi SOLO JSON:
    {{
        "product_name": "Nome esatto trovato",
        "description": "Breve descrizione",
        "category": "Categoria scelta",
        "has_epd_mention": true/false,
        "has_emission_mention": true/false,
        "has_recycled_mention": true/false,
        "detected_epd_url": "URL se presente o null"
    }}

    TESTO:
    {text_content}
    """
    
    ai_resp = ask_qwen(prompt, json_mode=True)
    
    try:
        data = json.loads(ai_resp)
    except:
        data = {
            "product_name": product_name, 
            "category": "Da Revisionare", 
            "description": "Errore parsing AI"
        }

    # 6. Preparazione Dati AI
    real_name = data.get("product_name") or product_name
    
    desc = data.get("description", "")
    if data.get("has_epd_mention"): desc += " [EPD Rilevata]"
    if data.get("has_emission_mention"): desc += " [Emissioni Rilevate]"
    
    return {
        "status": "ready_to_load",
        "company_id": company_id,
        "company_name": manufacturer,
        "original_name": product_name,
        "final_name": real_name,
        "category": data.get("category", "Altro"),
        "description": desc,
        "url_technical_sheet": url,
        "epd_url": data.get("detected_epd_url"),
        "is_recycled": data.get("has_recycled_mention", False),
        "exists_warning": exists_warning
    }