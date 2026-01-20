# ingest_worker.py (nella root del progetto, fuori da app/ o dentro, come preferisci)
import asyncio
import os
import sys
import json

# Aggiungiamo la cartella corrente al path per importare i moduli app
sys.path.append(os.getcwd())

from app.pdf_parser import extract_text_from_pdf
from app.llm import ask_qwen
from app.schemas import ProductExtraction

async def process_document(file_path: str):
    print(f"🔄 1. Avvio elaborazione: {file_path}")
    
    # 1. Estrazione Testo
    raw_text = extract_text_from_pdf(file_path)
    if not raw_text:
        print("❌ Errore: Impossibile estrarre testo dal PDF.")
        return

    print(f"📄 2. Testo estratto ({len(raw_text)} caratteri). Invio al LLM...")

    # 2. Analisi AI
    # Tronchiamo il testo se è enorme (es. > 12.000 caratteri) per non saturare il contesto
    text_payload = raw_text[:12000]
    
    extraction_prompt = f"""Analizza il seguente testo estratto da una scheda tecnica/datasheet di prodotto.
Estrai le informazioni strutturate nel formato JSON richiesto.

Testo:
{text_payload}

Formato JSON richiesto:
{{
    "manufacturer_name": "Nome del produttore",
    "product_name": "Nome commerciale del prodotto",
    "category": "Categoria macro (es. Isolante, Intonaco, etc.)",
    "description": "Breve descrizione funzionale",
    "epd_registration_number": null,
    "gwp_total": null,
    "epd_expiration_date": null,
    "technical_specs": [],
    "is_recycled": false
}}"""
    
    try:
        result_json = ask_qwen(extraction_prompt, json_mode=True)
        result = ProductExtraction(**json.loads(result_json))
        
        if result:
            print("\n✅ 3. ANALISI COMPLETATA CON SUCCESSO!")
            print("-" * 50)
            print(f"🏭 Produttore: {result.manufacturer_name}")
            print(f"📦 Prodotto:   {result.product_name}")
            print(f"🏷️  Categoria:  {result.category}")
            
            if result.epd_registration_number:
                print(f"🌍 EPD Found:  {result.epd_registration_number} (GWP: {result.gwp_total})")
            
            print(f"\n📊 Proprietà Tecniche ({len(result.technical_specs)} trovate):")
            for prop in result.technical_specs:
                print(f"   - {prop.name}: {prop.value} [{prop.unit or ''}]")
            print("-" * 50)
            
            # TODO: Qui inseriremo la chiamata a Supabase per salvare i dati
            # save_to_db(result)
            
        else:
            print("⚠️  Il LLM non ha restituito dati validi.")

    except Exception as e:
        print(f"❌ Errore critico nel processo AI: {e}")

if __name__ == "__main__":
    # Esempio di utilizzo da riga di comando: python ingest_worker.py files/scheda.pdf
    if len(sys.argv) < 2:
        print("Uso: python ingest_worker.py <percorso_del_pdf>")
    else:
        pdf_file = sys.argv[1]
        asyncio.run(process_document(pdf_file))