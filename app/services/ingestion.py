import json
import io
from bs4 import BeautifulSoup
from app.services.crawler import fetch_url_content
from app.pdf_parser import extract_text_from_pdf_bytes
from app.llm import ask_qwen
from app.database import supabase

# --- LISTA CATEGORIE (MODIFICAMI!) ---
# Qwen sarà forzato a scegliere una di queste.
EDILIZIA_CATEGORIES = [
    "Isolanti Termici",
    "Impermeabilizzanti",
    "Cartongesso e Lastre",
    "Intonaci e Malte",
    "Adesivi e Sigillanti",
    "Pavimenti e Rivestimenti",
    "Vernici e Finiture",
    "Calcestruzzi e Cementi",
    "Laterizi e Blocchi",
    "Facciate e Cappotti",
    "Serramenti e Vetri",
    "Impianti HVAC"
]

async def process_batch_item(manufacturer: str, product_name: str, url: str):
    print(f"⚙️ Processing: {manufacturer} - {product_name}...")
    
    # 1. Gestione Azienda (Upsert o Get)
    company_res = supabase.table("companies").select("id").ilike("name", manufacturer).execute()
    if company_res.data:
        company_id = company_res.data[0]['id']
    else:
        new_comp = supabase.table("companies").insert({"name": manufacturer}).execute()
        company_id = new_comp.data[0]['id']

    # 2. Controllo Esistenza Prodotto
    prod_res = supabase.table("products")\
        .select("id")\
        .eq("company_id", company_id)\
        .ilike("name", product_name)\
        .execute()
        
    if prod_res.data:
        return {"status": "skipped", "reason": "Prodotto già esistente"}

    # 3. Scaricamento e Pulizia Contenuto
    scraped_data = await fetch_url_content(url)
    if "error" in scraped_data:
        return {"status": "error", "reason": scraped_data["error"]}

    text_content = ""
    if scraped_data["type"] == "pdf":
        text_content = extract_text_from_pdf_bytes(scraped_data["content"])
    else:
        # Pulizia HTML con BeautifulSoup
        soup = BeautifulSoup(scraped_data["text"], "html.parser")
        # Rimuoviamo tag inutili
        for tag in soup(["script", "style", "nav", "footer", "header", "form"]):
            tag.decompose()
        text_content = soup.get_text(separator="\n")
        # Riduciamo spazi vuoti
        text_content = "\n".join([line.strip() for line in text_content.splitlines() if line.strip()])
        # Tronchiamo per non intasare l'LLM
        text_content = text_content[:12000]

    # 4. Prompt "Classification & Discovery"
    prompt = f"""
    Sei un assistente per la catalogazione di materiali edili.
    Analizza il testo fornito (che proviene da una pagina prodotto o scheda tecnica).
    
    OBIETTIVI:
    1. Identifica il Nome Commerciale esatto del prodotto.
    2. Classificalo in UNA delle seguenti categorie: {str(EDILIZIA_CATEGORIES)}. Se non rientra, usa "Altro".
    3. Rileva la PRESENZA di documentazione ambientale (EPD, CAM, Emissioni).
    
    Rispondi SOLO con un JSON valido in questo formato:
    {{
        "product_name": "Nome trovato nel testo",
        "description": "Breve descrizione di 1 frase (es. Pannello in lana di roccia per cappotto)",
        "category": "Una delle categorie fornite",
        "has_epd_mention": true/false (se il testo cita EPD o Dichiarazione Ambientale),
        "has_emission_mention": true/false (se il testo cita VOC, GEV Emicode, Indoor Air Comfort, o Classe A+),
        "detected_epd_url": "URL se trovi un link esplicito al PDF EPD, altrimenti null"
    }}

    TESTO DA ANALIZZARE:
    {text_content}
    """
    
    # 5. Chiamata AI
    ai_resp = ask_qwen(prompt, json_mode=True)
    
    try:
        data = json.loads(ai_resp)
    except:
        # Fallback in caso di JSON rotto
        data = {
            "product_name": product_name,
            "category": "Da Revisionare", 
            "description": "Errore parsing AI",
            "has_epd_mention": False
        }

    # 6. Preparazione Payload DB
    # Nota: Mettiamo i flag "detected" nelle note o descrizione per aiutare l'operatore
    # Oppure potremmo creare un campo 'ai_notes' nel DB, ma per ora usiamo la descrizione o i campi url come 'placeholder'
    
    # Se l'AI ha trovato un URL EPD, lo pre-carichiamo. 
    # Altrimenti lasciamo null per l'operatore.
    epd_url_candidate = data.get("detected_epd_url")
    
    # Costruiamo una descrizione arricchita dai flag AI
    rich_description = data.get("description", "")
    flags = []
    if data.get("has_epd_mention"): flags.append("[EPD Rilevata]")
    if data.get("has_emission_mention"): flags.append("[Emissioni Rilevate]")
    if flags:
        rich_description += " " + " ".join(flags)

    product_payload = {
        "company_id": company_id,
        "name": data.get("product_name") or product_name, # Preferiamo il nome AI se lo ha trovato pulito
        "category": data.get("category", "Altro"),
        "description": rich_description,
        "epd_url": epd_url_candidate, # Se l'AI è stata brava, lo mette.
        "is_validated": False,        # SEMPRE FALSE: Richiede intervento umano
        "url_technical_sheet": url,   # Link alla fonte originale
        "is_recycled": False,         # Default prudente
        "properties": {}              # JSON vuoto, niente dati tecnici per ora
    }
    
    # Inserimento
    supabase.table("products").insert(product_payload).execute()

    return {"status": "success", "product": product_name}