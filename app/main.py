import json
import io
from fastapi import FastAPI, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
from pypdf import PdfReader  # <--- NUOVO IMPORT NECESSARIO
from app.llm import ask_qwen
from app.database import supabase, create_project, get_user_projects, get_project_by_id
import secrets
import base64

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")

# --- Configurazione Sicurezza ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- DATABASE UTENTI SIMULATO (Hardcoded) ---
# Qui inseriamo i dati che in futuro staranno nel DB
USERS_DB = {
    "admin": {
        "username": "admin",
        "email": "admin@fullerstp.it",
        "user_code": "LICENSE-FULLER-001",  # Codice univoco per la licenza
        "password_hash": pwd_context.hash("GH2026")
    }
}

# --- GESTIONE SESSIONI IN MEMORIA ---
# Collega il token del cookie allo username
# Es: {"a1b2c3...": "admin"}
ACTIVE_SESSIONS = {}

def verify_credentials(username: str, password: str):
    user = USERS_DB.get(username)
    if not user:
        return False
    return pwd_context.verify(password, user["password_hash"])

def get_current_user(request: Request):
    """
    Recupera i dati dell'utente loggato tramite il cookie.
    Restituisce il dizionario utente o None.
    """
    token = request.cookies.get("session_token")
    if not token:
        return None
    
    username = ACTIVE_SESSIONS.get(token)
    if username:
        return USERS_DB.get(username)
    return None

# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    # Se l'utente è già loggato, va diretto alla dashboard
    if get_current_user(request):
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/", response_class=HTMLResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if verify_credentials(username, password):
        # Login corretto
        response = RedirectResponse("/dashboard", status_code=302)
        
        # Genera token e salva la sessione in memoria
        token = secrets.token_hex(16)
        ACTIVE_SESSIONS[token] = username
        
        # Imposta il cookie
        response.set_cookie(key="session_token", value=token, httponly=True)
        return response
    
    return templates.TemplateResponse("login.html", {"request": request, "error": "Credenziali errate"})

@app.get("/logout")
async def logout(request: Request):
    response = RedirectResponse("/")
    
    # Rimuove la sessione dalla memoria server
    token = request.cookies.get("session_token")
    if token and token in ACTIVE_SESSIONS:
        del ACTIVE_SESSIONS[token]
    
    # Rimuove il cookie dal client
    response.delete_cookie("session_token")
    return response

# --- Dashboard e LLM ---

# ... import esistenti ...
# IMPORTIAMO LE NUOVE FUNZIONI DAL DATABASE
from app.database import create_project, get_user_projects, get_project_by_id

# ... codice login invariato ...

# --- GESTIONE PROGETTI ---

@app.get("/dashboard")
async def dashboard_redirect(request: Request):
    """La dashboard generica ora ridirige alla lista progetti"""
    if not get_current_user(request):
        return RedirectResponse("/")
    return RedirectResponse("/projects")

@app.get("/projects", response_class=HTMLResponse)
async def list_projects(request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    # Recupera progetti dal DB
    user_projects = get_user_projects(user["user_code"])
    
    return templates.TemplateResponse("projects_list.html", {
        "request": request, 
        "user": user,
        "projects": user_projects,
        "active_project": None # Indica che siamo nella lista, non dentro un progetto
    })

@app.get("/projects/new", response_class=HTMLResponse)
async def new_project_form(request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    return templates.TemplateResponse("new_project.html", {
        "request": request, 
        "user": user,
        "active_project": None
    })

@app.post("/projects/new", response_class=HTMLResponse)
async def create_new_project(
    request: Request, 
    name: str = Form(...), 
    location: str = Form(...), 
    protocol: str = Form(...)
):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    # Crea nel DB
    project_id = create_project(user["user_code"], name, location, protocol)
    
    # Redireziona direttamente dentro al progetto appena creato
    return RedirectResponse(f"/projects/{project_id}", status_code=302)

@app.get("/projects/{project_id}", response_class=HTMLResponse)
async def view_project(request: Request, project_id: str):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    # Recupera i dettagli del progetto
    project = get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Progetto non trovato")
    
    # Qui renderizziamo la dashboard specifica del progetto (Verifica/Cerca)
    return templates.TemplateResponse("project_home.html", {
        "request": request,
        "user": user,
        "active_project": project # Questo attiva il menu laterale dei crediti!
    })

# Route di test rapido
@app.get("/test-llm")
async def test_llm():
    response = ask_qwen("Dimmi ciao in italiano")
    return {"risposta": response}

    import base64
# Assicurati di importare i nuovi moduli
from app.database import supabase # Import generico

# --- Modifica queste funzioni esistenti ---

@app.get("/admin/manufacturers", response_class=HTMLResponse)
async def admin_manufacturers(request: Request, edit_id: str = None):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    # Recupera tutti
    res = supabase.table("manufacturers").select("*").order("name").execute()
    
    # Se c'è edit_id, recuperiamo quel singolo record per riempire il form
    edit_data = None
    if edit_id:
        single_res = supabase.table("manufacturers").select("*").eq("id", edit_id).single().execute()
        edit_data = single_res.data

    return templates.TemplateResponse("admin_manufacturers.html", {
        "request": request, 
        "user": user,
        "manufacturers": res.data,
        "edit_data": edit_data # Passiamo i dati da modificare al template
    })

@app.post("/admin/manufacturers/save")
async def save_manufacturer(
    request: Request, 
    id: str = Form(None), # Se è vuoto -> Nuovo, Se c'è -> Modifica
    name: str = Form(...), 
    website: str = Form(None),
    email: str = Form(None),
    phone: str = Form(None)
):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    contacts_data = {"email": email, "phone": phone}
    
    data = {
        "name": name, 
        "website": website,
        "contacts": contacts_data
    }
    
    if id and id.strip():
        # UPDATE: Se c'è l'ID, aggiorniamo il record esistente
        supabase.table("manufacturers").update(data).eq("id", id).execute()
    else:
        # INSERT: Se non c'è ID, ne creiamo uno nuovo
        supabase.table("manufacturers").insert(data).execute()
    
    return RedirectResponse("/admin/manufacturers", status_code=302)

@app.get("/admin/manufacturers/delete/{man_id}")
async def delete_manufacturer(request: Request, man_id: str):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    # DELETE
    try:
        supabase.table("manufacturers").delete().eq("id", man_id).execute()
    except Exception as e:
        print(f"Errore eliminazione: {e}")
        # Qui potremmo gestire l'errore se ci sono materiali collegati (foreign key constraint)
        
    return RedirectResponse("/admin/manufacturers", status_code=302)

@app.get("/admin/ingest", response_class=HTMLResponse)
async def admin_ingest_page(request: Request, manufacturer_id: str):
    user = get_current_user(request) # 1. Catturiamo l'utente
    if not user: return RedirectResponse("/")
    
    # Recupera info produttore per il titolo
    man_res = supabase.table("manufacturers").select("*").eq("id", manufacturer_id).single().execute()
    
    return templates.TemplateResponse("admin_ingest.html", {
        "request": request,
        "user": user,          # <--- 2. Lo passiamo al template
        "manufacturer": man_res.data,
        "analysis_data": None
    })

@app.post("/admin/ingest", response_class=HTMLResponse)
async def admin_ingest_process(
    request: Request, 
    manufacturer_id: str = Form(...),
    file: UploadFile = File(...)
):
    user = get_current_user(request) # 1. Catturiamo l'utente
    if not user: return RedirectResponse("/")
    
    # 1. Leggi PDF
    contents = await file.read()
    pdf_file = io.BytesIO(contents)
    reader = PdfReader(pdf_file)
    text = ""
    for page in reader.pages: text += page.extract_text()
    
    # 2. Converti PDF in base64 per mostrarlo nell'iframe
    pdf_base64 = base64.b64encode(contents).decode('utf-8')
    
    # 3. Chiedi all'AI
    extraction_prompt = (
        f"Analizza la scheda tecnica:\n{text[:15000]}\n"
        f"Estrai JSON: manufacturer_name (ignora), material_name, category, description, "
        f"technical_properties (cerca valori numerici, conducibilità, riciclato, certificazioni)."
    )
    
    raw_response = ask_qwen(extraction_prompt, json_mode=True)
    cleaned_json = raw_response.replace("```json", "").replace("```", "").strip()
    
    try:
        data_dict = json.loads(cleaned_json)
    except:
        data_dict = {"material_name": "Errore AI", "description": raw_response, "technical_properties": {}}

    # Recupera info produttore
    man_res = supabase.table("manufacturers").select("*").eq("id", manufacturer_id).single().execute()

    return templates.TemplateResponse("admin_ingest.html", {
        "request": request,
        "user": user,          # <--- 2. Lo passiamo al template anche qui
        "manufacturer": man_res.data,
        "analysis_data": data_dict,
        "pdf_base64": pdf_base64
    })


    # --- SEZIONE CREDITI LEED ---

@app.get("/projects/{project_id}/credits/mr_epd", response_class=HTMLResponse)
async def view_credit_mr_epd(request: Request, project_id: str):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    project = get_project_by_id(project_id)
    
    # Recuperiamo le categorie uniche presenti nel DB per popolare la tendina
    # (Usiamo un set python per rimuovere duplicati se il DB non supporta .distinct() facile via API)
    res_cats = supabase.table("materials").select("category").execute()
    categories = sorted(list(set([row['category'] for row in res_cats.data if row['category']])))
    
    return templates.TemplateResponse("credits/mr_epd.html", {
        "request": request,
        "user": user,
        "active_project": project,
        "categories": categories
    })


# In main.py

@app.post("/projects/{project_id}/credits/mr_epd/assign")
async def assign_credit_mr_epd(
    request: Request, 
    project_id: str,
    material_id: str = Form(...),
    epd_id: str = Form(None) # Opzionale, se serve tracciare quale EPD specifica
):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    # Usiamo la funzione creata sopra specificando il codice del credito attuale
    # Potresti importarla da app.database
    assign_material_to_project(project_id, material_id, "MR_EPD")
    
    # Rispondiamo con un piccolo tocco di UI:
    # Invece di ricaricare tutto, restituiamo un bottone "Check" verde tramite HTMX
    return HTMLResponse('<button class="btn btn-sm btn-success" disabled><i class="fa fa-check"></i> Aggiunto</button>')

@app.post("/projects/{project_id}/credits/mr_epd/search", response_class=HTMLResponse)
async def search_credit_mr_epd(
    request: Request, 
    project_id: str,
    category: str = Form(...),
    epd_type: str = Form(...), # Arriva come stringa dalla select HTML
    search_text: str = Form("")
):
    user = get_current_user(request)
    
    # Conversione input
    epd_type_int = int(epd_type) if epd_type.isdigit() else None
    
    # Esecuzione Ricerca
    results = search_materials_db(category, epd_type_int, search_text)
    
    # Restituiamo solo il frammento HTML della tabella (pattern HTMX) 
    # oppure ricarichiamo la pagina con i risultati. 
    # Per semplicità ora, usiamo un template "partials" per aggiornare solo la lista.
    return templates.TemplateResponse("partials/material_results_list.html", {
        "request": request,
        "materials": results
    })

    # Route placeholder per la Verifica (Card di sinistra)
@app.get("/projects/{project_id}/credits/mr_epd/verify", response_class=HTMLResponse)
async def verify_credit_mr_epd_page(request: Request, project_id: str):
    user = get_current_user(request)
    project = get_project_by_id(project_id)
    
    # Per ora mostriamo un template semplice o un "Work in Progress"
    # Puoi creare un template 'verify_material.html' simile a quello di 'ingest' ma user-facing
    return templates.TemplateResponse("credits/verify_material.html", {
        "request": request, 
        "user": user, 
        "active_project": project
    })