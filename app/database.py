import os
from supabase import create_client, Client
from dotenv import load_dotenv
from typing import Optional
import json

# 1. Carica le variabili dal file .env
load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    raise ValueError("ATTENZIONE: Manca SUPABASE_URL o SUPABASE_KEY nel file .env")

# 2. Crea la connessione (Singleton)
# Usiamo questa variabile 'supabase' in tutto il progetto per parlare col DB
supabase: Client = create_client(url, key)

def test_connection():
    """Prova a leggere la tabella manufacturers per vedere se funziona"""
    try:
        response = supabase.table("manufacturers").select("*").limit(1).execute()
        print(f"✅ Connessione Supabase RIUSCITA! Dati: {response.data}")
        return True
    except Exception as e:
        print(f"❌ Errore connessione Supabase: {e}")
        return False

# Se esegui questo file direttamente, fa un test
if __name__ == "__main__":
    test_connection()




def assign_material_to_project(project_id: str, material_id: str, credit_code: str):
    """
    Collega un materiale a un progetto. 
    Se il collegamento esiste già, aggiunge il credit_code alla lista JSON esistente.
    """
    
    # 1. Controlliamo se esiste già questo materiale nel progetto
    existing = supabase.table("project_materials")\
        .select("*")\
        .eq("project_id", project_id)\
        .eq("material_id", material_id)\
        .execute()
        
    if existing.data:
        # CASO A: Il materiale è già nel progetto. Aggiorniamo i crediti.
        row_id = existing.data[0]['id']
        current_credits = existing.data[0]['assigned_credits'] or []
        
        # Se il credito non è già nella lista, lo aggiungiamo
        if credit_code not in current_credits:
            current_credits.append(credit_code)
            
            supabase.table("project_materials")\
                .update({"assigned_credits": current_credits})\
                .eq("id", row_id)\
                .execute()
                
    else:
        # CASO B: È la prima volta che usiamo questo materiale nel progetto.
        new_entry = {
            "project_id": project_id,
            "material_id": material_id,
            "assigned_credits": [credit_code], # Creiamo la lista con il primo credito
            "quantity": 1 # Default
        }
        supabase.table("project_materials").insert(new_entry).execute()
        
    return True

# ... (codice esistente: import e connessione supabase) ...

def create_project(user_code: str, name: str, location: str, protocol: str) -> str:
    """Crea un nuovo progetto e restituisce il suo ID"""
    try:
        data = {
            "user_code": user_code,
            "name": name,
            "location": location,
            "protocol": protocol
        }
        res = supabase.table("projects").insert(data).execute()
        return res.data[0]["id"]
    except Exception as e:
        print(f"❌ Errore creazione progetto: {e}")
        raise e

def get_user_projects(user_code: str):
    """Restituisce la lista dei progetti di un utente specifico"""
    try:
        res = supabase.table("projects").select("*").eq("user_code", user_code).order("created_at", desc=True).execute()
        return res.data
    except Exception as e:
        print(f"❌ Errore recupero progetti: {e}")
        return []

def get_project_by_id(project_id: str):
    """Recupera i dettagli di un singolo progetto"""
    try:
        res = supabase.table("projects").select("*").eq("id", project_id).single().execute()
        return res.data
    except Exception as e:
        print(f"❌ Errore recupero progetto {project_id}: {e}")
        return None

def search_materials_db(category: str, epd_type: Optional[int], search_text: str):
    """
    Esegue la query su Supabase unendo Materials ed EPDs.
    """
    # Costruiamo la selezione base. 
    # Vogliamo i dati del materiale, il nome del produttore, e i dati EPD.
    # Sintassi: tabella_collegata(colonne)
    select_query = "*, manufacturers(name), epds(*)"

    # Se l'utente filtra per un TIPO SPECIFICO di EPD, dobbiamo usare "!inner"
    # Questo forza la query a restituire solo materiali che HANNO quel tipo di EPD.
    # Se non mettiamo !inner, ci ridarebbe il materiale con epds=[], che non vogliamo se filtriamo.
    if epd_type is not None:
        select_query = "*, manufacturers(name), epds!inner(*)"
    
    query = supabase.table("materials").select(select_query)
    
    # 1. Filtro Categoria (sulla tabella materials)
    if category and category != "Tutte":
        query = query.eq("category", category)
    
    # 2. Filtro Tipo EPD (sulla tabella epds collegata)
    if epd_type is not None:
        query = query.eq("epds.epd_type", epd_type)
        
    # 3. Filtro Testo (sulla tabella materials)
    if search_text:
        or_condition = f"name.ilike.%{search_text}%,description.ilike.%{search_text}%"
        query = query.or_(or_condition)
        
    result = query.execute()
    return result.data

    