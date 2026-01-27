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
supabase: Client = create_client(url, key)

def test_connection():
    """Prova a leggere la tabella manufacturers per vedere se funziona"""
    try:
        response = supabase.table("companies").select("*").limit(1).execute()
        print(f"✅ Connessione Supabase RIUSCITA! Dati: {response.data}")
        return True
    except Exception as e:
        print(f"❌ Errore connessione Supabase: {e}")
        return False

# Se esegui questo file direttamente, fa un test
if __name__ == "__main__":
    test_connection()

# Sostituisci/Aggiungi in app/database.py

def assign_material_to_project(project_id: str, material_id: str, credit_code: str):
    """
    Inserisce una nuova riga nella tabella project_materials.
    Se la combinazione (project_id, material_id, credit) esiste già, non fa nulla (grazie all'UNIQUE constraint o al check).
    """
    # Usiamo upsert con 'ignoreDuplicates' o controlliamo prima.
    # Supabase-py non ha "ignore_duplicates" facile su insert, quindi facciamo check manuale o try/except
    
    # 1. Check esistenza
    exists = supabase.table("project_materials")\
        .select("id")\
        .eq("project_id", project_id)\
        .eq("material_id", material_id)\
        .eq("credit", credit_code)\
        .execute()
        
    if not exists.data:
        # 2. Inserimento
        new_entry = {
            "project_id": project_id,
            "material_id": material_id,
            "credit": credit_code
        }
        supabase.table("project_materials").insert(new_entry).execute()
        return True
    
    return False # Già presente

def get_project_materials(project_id: str, credit_code: str):
    """
    Recupera tutti i materiali assegnati a un certo credito di un progetto.
    Fa una join con la tabella 'products' per avere i dettagli (nome, produttore, ecc).
    """
    # Select: prendi tutto da project_materials E i campi di products collegati a material_id
    # Sintassi Join Supabase: material_id:products(...)
    res = supabase.table("project_materials")\
        .select("id, created_at, products!material_id(*, companies(name))")\
        .eq("project_id", project_id)\
        .eq("credit", credit_code)\
        .order("created_at", desc=True)\
        .execute()
        
    # Appiattiamo leggermente la risposta se necessario, o la passiamo così al template
    return res.data

def remove_material_from_project(assignment_id: str):
    """Cancella una riga dalla tabella project_materials tramite il suo ID"""
    supabase.table("project_materials").delete().eq("id", assignment_id).execute()
    return True

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

def search_products_db(category: str, leed_version: str, search_text: str, exclude_ids: list[str] = None):
    """
    Cerca prodotti per il credito MR EPD in base alla versione LEED.
    """
    # Query base
    query = supabase.table("products").select("*, companies(name)")
    
    # --- 1. FILTRI DI BASE (OBBLIGATORI PER TUTTI) ---
    # Validato, EPD presente, Scadenza presente, Documento presente
    query = query.eq("is_validated", True)
    query = query.not_.is_("epd_type", "null")
    query = query.not_.is_("epd_expiration", "null")
    query = query.or_("epd_url.neq.null,epd_file_path.neq.null")

    # --- 2. LOGICA VERSIONE LEED ---
    if leed_version == "v4":
        # LEED v4 è più restrittivo: accetta solo EPD Specifiche Certificate o Industry-wide.
        # Esclude quelle "Internally Reviewed" (autodichiarate non certificate).
        allowed_types = [
            "Industry-wide (generic) EPD", 
            "Product-specific Type III EPD with third-party certification"
        ]
        query = query.in_("epd_type", allowed_types)
        
    elif leed_version == "v4.1":
        # LEED v4.1 accetta TUTTO purché sia un'EPD (anche le "Internally Reviewed").
        # I filtri di base (not null) hanno già escluso chi non ha EPD.
        pass 

    # --- 3. ESCLUSIONE MATERIALI GIÀ PRESENTI ---
    if exclude_ids and len(exclude_ids) > 0:
        query = query.not_.in_("id", exclude_ids)

    # --- 4. ALTRI FILTRI UTENTE ---
    if category and category != "Tutte":
        query = query.eq("category", category)
    
    if search_text:
        or_condition = f"name.ilike.%{search_text}%,description.ilike.%{search_text}%"
        query = query.or_(or_condition)
        
    query = query.order("name")
    result = query.execute()
    return result.data