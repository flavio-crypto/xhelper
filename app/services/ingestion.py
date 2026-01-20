import json
import io
from app.services.crawler import fetch_url_content
from app.pdf_parser import extract_text_from_pdf_bytes # Dovremo adattare il parser per accettare bytes
from app.llm import ask_qwen
from app.database import supabase

# Funzione helper per parsing PDF da bytes (da aggiungere in pdf_parser.py o qui)
import fitz
def extract_text_from_bytes(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text

async def process_batch_item(manufacturer: str, product_name: str, url: str):
    """
    Processa una singola riga della lista materiali.
    """
    print(f"⚙️ Processing: {manufacturer} - {product_name}...")
    
    # 1. Gestione Azienda (Upsert)
    # Cerchiamo se esiste l'azienda, altrimenti la creiamo
    company_res = supabase.table("companies").select("id").ilike("name", manufacturer).execute()
    if company_res.data:
        company_id = company_res.data[0]['id']
    else:
        # Creiamo nuova azienda
        new_comp = supabase.table("companies").insert({"name": manufacturer}).execute()
        company_id = new_comp.data[0]['id']

    # 2. Controlliamo se il prodotto esiste già (per evitare lavoro inutile)
    prod_res = supabase.table("products")\
        .select("id")\
        .eq("company_id", company_id)\
        .ilike("name", product_name)\
        .execute()
        
    if prod_res.data:
        return {"status": "skipped", "reason": "Prodotto già esistente"}

    # 3. Scaricamento Dati
    scraped_data = await fetch_url_content(url)
    if "error" in scraped_data:
        return {"status": "error", "reason": scraped_data["error"]}

    # 4. Estrazione Testo
    text_content = ""
    if scraped_data["type"] == "pdf":
        text_content = extract_text_from_bytes(scraped_data["content"])
    else:
        # Per HTML servirebbe BeautifulSoup per pulire, per ora inviamo raw text troncato
        text_content = scraped_data["text"][:15000] # Qwen ha un limite context

    # 5. Prompt per Qwen (Aggiornato alla Lavagna)
    prompt = f"""
    Analizza il testo tecnico di un materiale edile.
    Estrai i dati per popolare il database.
    
    DATI RICHIESTI (JSON):
    - category: (es. Isolanti, Intonaci)
    - description: breve descrizione
    - epd_url: se trovi link a EPD
    - epd_expiration: data scadenza EPD (YYYY-MM-DD) o null
    - is_recycled: true/false se menziona contenuto riciclato
    - properties: oggetto JSON con dati tecnici (es. {{ "lambda": "0.035", "density": "100" }})
    - leed_v4: true/false se menziona conformità LEED v4 (VOC, emissioni)
    
    Testo:
    {text_content[:10000]}
    """
    
    ai_resp = ask_qwen(prompt, json_mode=True)
    
    try:
        data = json.loads(ai_resp)
    except:
        data = {}

    # 6. Inserimento nel DB (Tabella PRODUCTS piatta)
    product_payload = {
        "company_id": company_id,
        "name": product_name,
        "category": data.get("category", "Sconosciuto"),
        "description": data.get("description", ""),
        "epd_url": data.get("epd_url") or (url if "epd" in url.lower() else None),
        "epd_expiration": data.get("epd_expiration"),
        "is_recycled": data.get("is_recycled", False),
        "properties": data.get("properties", {}),
        "is_validated": False, # IMPORTANTE: Va in bozza
        "url_technical_sheet": url
    }
    
    new_prod = supabase.table("products").insert(product_payload).execute()
    new_prod_id = new_prod.data[0]['id']
    
    # 7. Inserimento Emissioni (Tabella EMISSION_PRODUCTS)
    # Se l'AI ha rilevato compliance LEED
    if data.get("leed_v4") or data.get("leed_v41"):
        emission_payload = {
            "product_id": new_prod_id,
            "leed_v4_compliant": data.get("leed_v4", False),
            "leed_v41_compliant": data.get("leed_v41", False)
        }
        supabase.table("emission_products").insert(emission_payload).execute()

    return {"status": "success", "product": product_name}