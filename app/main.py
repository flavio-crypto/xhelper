from fastapi import FastAPI, Request, Form, Depends, HTTPException
from app.database import create_project, get_user_projects, get_project_by_id
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
from app.llm import ask_qwen
import secrets

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

# --- ROTTE ADMIN / DATA FACTORY ---

@app.get("/admin/manufacturers", response_class=HTMLResponse)
async def admin_manufacturers(request: Request):
    if not get_current_user(request): return RedirectResponse("/")
    
    # Recupera lista produttori
    res = supabase.table("manufacturers").select("*").order("name").execute()
    
    return templates.TemplateResponse("admin_manufacturers.html", {
        "request": request, 
        "manufacturers": res.data
    })

@app.post("/admin/manufacturers")
async def add_manufacturer(request: Request, name: str = Form(...), website: str = Form(None)):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    supabase.table("manufacturers").insert({"name": name, "website": website}).execute()
    return RedirectResponse("/admin/manufacturers", status_code=302)

@app.get("/admin/ingest", response_class=HTMLResponse)
async def admin_ingest_page(request: Request, manufacturer_id: str):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    # Recupera info produttore per il titolo
    man_res = supabase.table("manufacturers").select("*").eq("id", manufacturer_id).single().execute()
    
    return templates.TemplateResponse("admin_ingest.html", {
        "request": request,
        "manufacturer": man_res.data,
        "analysis_data": None # Nessuna analisi ancora avviata
    })

@app.post("/admin/ingest", response_class=HTMLResponse)
async def admin_ingest_process(
    request: Request, 
    manufacturer_id: str = Form(...),
    file: UploadFile = File(...)
):
    user = get_current_user(request)
    
    # 1. Leggi PDF
    contents = await file.read()
    pdf_file = io.BytesIO(contents)
    reader = PdfReader(pdf_file)
    text = ""
    for page in reader.pages: text += page.extract_text()
    
    # 2. Converti PDF in base64 per mostrarlo nell'iframe (Senza salvarlo su disco per ora)
    pdf_base64 = base64.b64encode(contents).decode('utf-8')
    
    # 3. Chiedi all'AI di estrarre i dati
    extraction_prompt = (
        f"Analizza la scheda tecnica:\n{text[:15000]}\n"
        f"Estrai JSON: manufacturer_name (ignora, lo so già), material_name, category, description, "
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
        "manufacturer": man_res.data,
        "analysis_data": data_dict,
        "pdf_base64": pdf_base64 # Passiamo il PDF da visualizzare
    })

@app.post("/admin/save-material")
async def save_validated_material(
    request: Request,
    manufacturer_id: str = Form(...),
    material_name: str = Form(...),
    category: str = Form(...),
    description: str = Form(...),
    # Nota: per le proprietà dinamiche servirebbe una logica più complessa di parsing del form,
    # per ora salviamo i base data per farti vedere il flusso.
):
    # Salvataggio nel DB con stato 'published'
    data = {
        "manufacturer_id": manufacturer_id,
        "name": material_name,
        "category": category,
        "description": description,
        "status": "published"
    }
    supabase.table("materials").insert(data).execute()
    
    return RedirectResponse("/admin/manufacturers", status_code=302)