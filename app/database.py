import os
from supabase import create_client, Client
from dotenv import load_dotenv

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