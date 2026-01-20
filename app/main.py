import json
import io
import base64
import secrets
from fastapi import FastAPI, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
from pypdf import PdfReader  # Assicurati di aver installato pypdf
from app.llm import ask_qwen
from app.database import supabase, create_project, get_user_projects, get_project_by_id
from app.services.ingestion import process_batch_item # Import per la Data Factory

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")

# --- Configurazione Sicurezza ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- DATABASE UTENTI SIMULATO (Hardcoded) ---
USERS_DB = {
    "admin": {
        "username": "admin",
        "email": "admin@fullerstp.it",
        "user_code": "LICENSE-FULLER-001",
        "password_hash": pwd_context.hash("GH2026")
    }
}

ACTIVE_SESSIONS = {}

def verify_credentials(username: str, password: str):
    user = USERS_DB.get(username)
    if not user:
        return False
    return pwd_context.verify(password, user["password_hash"])

def get_current_user(request: Request):
    token = request.cookies.get("session_token")
    if not token:
        return None
    username = ACTIVE_SESSIONS.get(token)
    if username:
        return USERS_DB.get(username)
    return None

# --- Routes Login/Logout ---

@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/", response_class=HTMLResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if verify_credentials(username, password):
        response = RedirectResponse("/dashboard", status_code=302)
        token = secrets.token_hex(16)
        ACTIVE_SESSIONS[token] = username
        response.set_cookie(key="session_token", value=token, httponly=True)
        return response
    return templates.TemplateResponse("login.html", {"request": request, "error": "Credenziali errate"})

@app.get("/logout")
async def logout(request: Request):
    response = RedirectResponse("/")
    token = request.cookies.get("session_token")
    if token and token in ACTIVE_SESSIONS:
        del ACTIVE_SESSIONS[token]
    response.delete_cookie("session_token")
    return response

# --- Dashboard e Progetti ---

@app.get("/dashboard")
async def dashboard_redirect(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/")
    return RedirectResponse("/projects")

@app.get("/projects", response_class=HTMLResponse)
async def list_projects(request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    user_projects = get_user_projects(user["user_code"])
    return templates.TemplateResponse("projects_list.html", {
        "request": request, 
        "user": user,
        "projects": user_projects,
        "active_project": None
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
async def create_new_project(request: Request, name: str = Form(...), location: str = Form(...), protocol: str = Form(...)):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    project_id = create_project(user["user_code"], name, location, protocol)
    return RedirectResponse(f"/projects/{project_id}", status_code=302)

@app.get("/projects/{project_id}", response_class=HTMLResponse)
async def view_project(request: Request, project_id: str):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    project = get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Progetto non trovato")
    return templates.TemplateResponse("project_home.html", {
        "request": request,
        "user": user,
        "active_project": project
    })

# --- GESTIONE COMPANIES (ex Manufacturers) ---
# CORREZIONE: Aggiornato per usare la tabella 'companies'

@app.get("/admin/manufacturers", response_class=HTMLResponse)
async def admin_manufacturers(request: Request, edit_id: str = None):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    # Query sulla tabella 'companies' invece di 'manufacturers'
    res = supabase.table("companies").select("*").order("name").execute()
    
    edit_data = None
    if edit_id:
        single_res = supabase.table("companies").select("*").eq("id", edit_id).single().execute()
        edit_data = single_res.data

    # Passiamo 'companies' al template
    return templates.TemplateResponse("admin_manufacturers.html", {
        "request": request, 
        "user": user,
        "companies": res.data,  # Cambiato nome variabile per chiarezza
        "edit_data": edit_data
    })

@app.post("/admin/manufacturers/save")
async def save_manufacturer(
    request: Request, 
    id: str = Form(None),
    name: str = Form(...), 
    website: str = Form(None),
    email: str = Form(None),
    phone: str = Form(None)
):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    # CORREZIONE: Salviamo email e phone direttamente nelle colonne, non in un JSON
    data = {
        "name": name, 
        "website": website,
        "email": email,
        "phone": phone
    }
    
    if id and id.strip():
        supabase.table("companies").update(data).eq("id", id).execute()
    else:
        supabase.table("companies").insert(data).execute()
    
    return RedirectResponse("/admin/manufacturers", status_code=302)

@app.get("/admin/manufacturers/delete/{man_id}")
async def delete_manufacturer(request: Request, man_id: str):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    try:
        supabase.table("companies").delete().eq("id", man_id).execute()
    except Exception as e:
        print(f"Errore eliminazione: {e}")
    return RedirectResponse("/admin/manufacturers", status_code=302)

# --- NUOVA SEZIONE DATA FACTORY (Ingestion Massiva) ---

@app.get("/admin/data-factory", response_class=HTMLResponse)
async def admin_data_factory(request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    # Recupera bozze dalla tabella 'products'
    drafts = supabase.table("products").select("*, companies(name)")\
        .eq("is_validated", False)\
        .order("created_at", desc=True).limit(20).execute()
        
    return templates.TemplateResponse("admin_data_factory.html", {
        "request": request,
        "user": user,
        "drafts": drafts.data
    })

@app.post("/admin/data-factory/process")
async def admin_process_list(request: Request, raw_list: str = Form(...)):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    lines = raw_list.strip().split("\n")
    results = []
    
    for line in lines:
        parts = line.split(",")
        if len(parts) >= 3:
            man = parts[0].strip()
            prod = parts[1].strip()
            url = parts[2].strip()
            
            # Qui chiamiamo la funzione asincrona definita in services/ingestion.py
            res = await process_batch_item(man, prod, url)
            results.append(res)
            
    return templates.TemplateResponse("partials/ingestion_log.html", {
        "request": request,
        "results": results
    })

@app.post("/admin/validate-product/{product_id}")
async def validate_product(product_id: str):
    supabase.table("products").update({"is_validated": True}).eq("id", product_id).execute()
    return HTMLResponse('<span class="text-green-600 font-bold">Validato!</span>')

# --- Ingestion Singola (Vecchio metodo, mantenuto per compatibilità) ---

@app.get("/admin/ingest", response_class=HTMLResponse)
async def admin_ingest_page(request: Request, manufacturer_id: str):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    # Query su companies
    man_res = supabase.table("companies").select("*").eq("id", manufacturer_id).single().execute()
    
    return templates.TemplateResponse("admin_ingest.html", {
        "request": request,
        "user": user,
        "manufacturer": man_res.data,
        "analysis_data": None
    })

# --- Crediti LEED ---

@app.get("/projects/{project_id}/credits/mr_epd", response_class=HTMLResponse)
async def view_credit_mr_epd(request: Request, project_id: str):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    project = get_project_by_id(project_id)
    
    # Nota: materials ora si chiama products. 
    res_cats = supabase.table("products").select("category").execute()
    categories = sorted(list(set([row['category'] for row in res_cats.data if row['category']])))
    
    return templates.TemplateResponse("credits/mr_epd.html", {
        "request": request,
        "user": user,
        "active_project": project,
        "categories": categories
    })