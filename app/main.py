import json
import io
import base64
import secrets
import shutil
import os
from fastapi import FastAPI, Request, Form, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles # FONDAMENTALE PER I PDF
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
from pypdf import PdfReader
from app.llm import ask_qwen
from app.database import supabase, create_project, get_user_projects, get_project_by_id
from app.services.ingestion import process_batch_item, EDILIZIA_CATEGORIES 

app = FastAPI()

# --- 1. CONFIGURAZIONE FILE SYSTEM ---
# Creiamo le cartelle fisiche se non esistono
DOCS_ROOT = "/workspace/documents"
os.makedirs(f"{DOCS_ROOT}/datasheets", exist_ok=True)
os.makedirs(f"{DOCS_ROOT}/epd", exist_ok=True)
os.makedirs(f"{DOCS_ROOT}/emissions", exist_ok=True)

# Montiamo la cartella per renderla accessibile via web
# Es: un file in /workspace/documents/epd/file.pdf sarà visibile su http://.../documents/epd/file.pdf
app.mount("/documents", StaticFiles(directory=DOCS_ROOT), name="documents")

templates = Jinja2Templates(directory="app/templates")

# --- Configurazione Sicurezza ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS_DB = {
    "admin": {
        "username": "admin", "email": "admin@fullerstp.it", "user_code": "LICENSE-FULLER-001", "password_hash": pwd_context.hash("GH2026")
    }
}
ACTIVE_SESSIONS = {}

def verify_credentials(username: str, password: str):
    user = USERS_DB.get(username)
    if not user: return False
    return pwd_context.verify(password, user["password_hash"])

def get_current_user(request: Request):
    token = request.cookies.get("session_token")
    if not token: return None
    username = ACTIVE_SESSIONS.get(token)
    if username: return USERS_DB.get(username)
    return None

# --- ROTTE LOGIN/LOGOUT ---
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    if get_current_user(request): return RedirectResponse("/dashboard")
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
    if token and token in ACTIVE_SESSIONS: del ACTIVE_SESSIONS[token]
    response.delete_cookie("session_token")
    return response

# --- DASHBOARD & PROGETTI ---
@app.get("/dashboard")
async def dashboard_redirect(request: Request):
    if not get_current_user(request): return RedirectResponse("/")
    return RedirectResponse("/projects")

@app.get("/projects", response_class=HTMLResponse)
async def list_projects(request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    user_projects = get_user_projects(user["user_code"])
    return templates.TemplateResponse("projects_list.html", {"request": request, "user": user, "projects": user_projects, "active_project": None})

@app.get("/projects/new", response_class=HTMLResponse)
async def new_project_form(request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    return templates.TemplateResponse("new_project.html", {"request": request, "user": user, "active_project": None})

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
    if not project: raise HTTPException(status_code=404, detail="Progetto non trovato")
    return templates.TemplateResponse("project_home.html", {"request": request, "user": user, "active_project": project})

# --- GESTIONE PRODUTTORI ---
@app.get("/admin/manufacturers", response_class=HTMLResponse)
async def admin_manufacturers(request: Request, edit_id: str = None):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    res = supabase.table("companies").select("*").order("name").execute()
    edit_data = None
    if edit_id:
        single_res = supabase.table("companies").select("*").eq("id", edit_id).single().execute()
        edit_data = single_res.data
    return templates.TemplateResponse("admin_manufacturers.html", {"request": request, "user": user, "companies": res.data, "edit_data": edit_data})

@app.post("/admin/manufacturers/save")
async def save_manufacturer(request: Request, id: str = Form(None), name: str = Form(...), website: str = Form(None), email: str = Form(None), phone: str = Form(None)):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    data = {"name": name, "website": website, "email": email, "phone": phone}
    if id and id.strip():
        supabase.table("companies").update(data).eq("id", id).execute()
    else:
        supabase.table("companies").insert(data).execute()
    return RedirectResponse("/admin/manufacturers", status_code=302)

@app.get("/admin/manufacturers/delete/{man_id}")
async def delete_manufacturer(request: Request, man_id: str):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    supabase.table("companies").delete().eq("id", man_id).execute()
    return RedirectResponse("/admin/manufacturers", status_code=302)

# --- DATA FACTORY ---
@app.get("/admin/data-factory", response_class=HTMLResponse)
async def admin_data_factory(request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    drafts = supabase.table("products").select("*, companies(name)").eq("is_validated", False).order("created_at", desc=True).limit(20).execute()
    return templates.TemplateResponse("admin_data_factory.html", {"request": request, "user": user, "drafts": drafts.data})

@app.post("/admin/data-factory/process")
async def admin_process_list(request: Request, raw_list: str = Form(...)):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    lines = raw_list.strip().split("\n")
    results = []
    for line in lines:
        parts = line.split(",")
        if len(parts) >= 3:
            man = parts[0].strip(); prod = parts[1].strip(); url = parts[2].strip()
            res = await process_batch_item(man, prod, url)
            results.append(res)
    return templates.TemplateResponse("partials/ingestion_log.html", {"request": request, "results": results})

@app.post("/admin/validate-product/{product_id}")
async def validate_product(product_id: str):
    supabase.table("products").update({"is_validated": True}).eq("id", product_id).execute()
    return HTMLResponse('<span class="text-green-600 font-bold">Validato!</span>')

# --- GESTIONE PRODOTTI (CRUD) ---
@app.get("/admin/products", response_class=HTMLResponse)
async def admin_products_list(request: Request, q: str = "", category: str = "", status: str = ""):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    query = supabase.table("products").select("*, companies(name)")
    if q: query = query.ilike("name", f"%{q}%")
    if category: query = query.eq("category", category)
    if status == "draft": query = query.eq("is_validated", False)
    elif status == "valid": query = query.eq("is_validated", True)
    res = query.order("created_at", desc=True).limit(50).execute()
    return templates.TemplateResponse("admin_products_list.html", {
        "request": request, "user": user, "products": res.data, "categories": EDILIZIA_CATEGORIES, "filters": {"q": q, "category": category, "status": status}
    })

@app.get("/admin/products/{product_id}", response_class=HTMLResponse)
async def admin_product_detail(request: Request, product_id: str):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    prod_res = supabase.table("products").select("*, companies(id, name)").eq("id", product_id).single().execute()
    comp_res = supabase.table("companies").select("id, name").order("name").execute()
    return templates.TemplateResponse("admin_product_detail.html", {
        "request": request, "user": user, "product": prod_res.data, "companies": comp_res.data, "categories": EDILIZIA_CATEGORIES
    })

# --- NUOVA ROUTE UPLOAD DOCUMENTI ---
@app.post("/admin/products/upload_doc")
async def upload_product_doc(
    request: Request,
    product_id: str = Form(...),
    doc_type: str = Form(...), # "datasheet", "epd", "emission"
    file: UploadFile = File(...)
):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")

    # Mappatura Tipo Documento -> Cartella -> Colonna DB
    if doc_type == "datasheet":
        subfolder = "datasheets"
        db_column = "tech_file_path"
    elif doc_type == "epd":
        subfolder = "epd"
        db_column = "epd_file_path"
    elif doc_type == "emission":
        subfolder = "emissions"
        db_column = "emission_file_path"
    else:
        raise HTTPException(status_code=400, detail="Tipo doc non valido")

    # Nome file sicuro
    safe_filename = f"{product_id}_{file.filename.replace(' ', '_')}"
    file_path_on_disk = f"{DOCS_ROOT}/{subfolder}/{safe_filename}"
    
    # Salvataggio fisico
    try:
        with open(file_path_on_disk, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        print(f"Errore salvataggio: {e}")
        return HTMLResponse("Errore I/O", status_code=500)

    # Aggiornamento DB con path web relativo
    web_path = f"/documents/{subfolder}/{safe_filename}"
    supabase.table("products").update({db_column: web_path}).eq("id", product_id).execute()

    return RedirectResponse(f"/admin/products/{product_id}", status_code=302)

@app.post("/admin/products/save")
async def admin_product_save(
    request: Request,
    id: str = Form(...),
    name: str = Form(...),
    company_id: str = Form(...),
    category: str = Form(...),
    description: str = Form(""),
    is_validated: bool = Form(False),
    epd_url: str = Form(None),
    epd_expiration: str = Form(None),
    emission_url: str = Form(None),
    emission_expiration: str = Form(None),
    is_recycled: bool = Form(False) 
):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    def clean_date(d): return d if d and d.strip() else None
    
    data = {
        "name": name,
        "company_id": company_id,
        "category": category,
        "description": description,
        "is_validated": True if is_validated else False,
        "epd_url": epd_url,
        "epd_expiration": clean_date(epd_expiration),
        "emission_url": emission_url,
        "emission_expiration": clean_date(emission_expiration),
        "is_recycled": True if is_recycled else False
    }
    supabase.table("products").update(data).eq("id", id).execute()
    return RedirectResponse(f"/admin/products/{id}", status_code=302)

@app.get("/admin/products/delete/{product_id}")
async def admin_product_delete(request: Request, product_id: str):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    supabase.table("products").delete().eq("id", product_id).execute()
    return RedirectResponse("/admin/products", status_code=302)

    # --- ROTTE PER I CREDITI LEED (AGGIUNTE) ---

@app.post("/projects/{project_id}/credits/mr_epd/search", response_class=HTMLResponse)
async def search_credit_mr_epd(
    request: Request, 
    project_id: str,
    category: str = Form(...),
    epd_type: str = Form(...),
    search_text: str = Form("")
):
    user = get_current_user(request)
    if not user: return HTMLResponse("Sessione scaduta", status_code=403)
    
    # Usiamo la nuova funzione di ricerca sui PRODUCTS
    from app.database import search_products_db
    results = search_products_db(category, epd_type, search_text)
    
    return templates.TemplateResponse("partials/material_results_list.html", {
        "request": request,
        "materials": results, # Passiamo i risultati al template parziale
        "active_project_id": project_id
    })

@app.post("/projects/{project_id}/credits/mr_epd/assign")
async def assign_credit_mr_epd(
    request: Request, 
    project_id: str,
    material_id: str = Form(...),
    epd_id: str = Form(None)
):
    user = get_current_user(request)
    if not user: return HTMLResponse("Errore auth", status_code=403)
    
    from app.database import assign_material_to_project
    # Nota: material_id qui corrisponde all'ID della tabella products
    assign_material_to_project(project_id, material_id, "MR_EPD")
    
    return HTMLResponse('<button class="text-green-600 border border-green-200 bg-green-50 px-3 py-1.5 rounded-lg text-xs font-bold cursor-default"><i class="fa-solid fa-check"></i> Aggiunto</button>')

# --- ALTRE ROTTE LEGACY ---
@app.get("/admin/ingest", response_class=HTMLResponse)
async def admin_ingest_page(request: Request, manufacturer_id: str):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    man_res = supabase.table("companies").select("*").eq("id", manufacturer_id).single().execute()
    return templates.TemplateResponse("admin_ingest.html", {"request": request, "user": user, "manufacturer": man_res.data, "analysis_data": None})

@app.get("/projects/{project_id}/credits/mr_epd", response_class=HTMLResponse)
async def view_credit_mr_epd(request: Request, project_id: str):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    project = get_project_by_id(project_id)
    res_cats = supabase.table("products").select("category").execute()
    categories = sorted(list(set([row['category'] for row in res_cats.data if row['category']])))
    return templates.TemplateResponse("credits/mr_epd.html", {"request": request, "user": user, "active_project": project, "categories": categories})

    # ... (altre rotte) ...

@app.get("/admin/products/delete_doc/{product_id}/{doc_type}")
async def delete_product_doc(request: Request, product_id: str, doc_type: str):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    # 1. Mappatura
    column_map = {
        "datasheet": "tech_file_path",
        "epd": "epd_file_path",
        "emission": "emission_file_path"
    }
    
    target_col = column_map.get(doc_type)
    if not target_col:
        raise HTTPException(status_code=400, detail="Tipo documento non valido")
        
    # 2. Recuperiamo il percorso attuale dal DB
    res = supabase.table("products").select(target_col).eq("id", product_id).single().execute()
    current_web_path = res.data.get(target_col)
    
    # 3. Se il file esiste, lo cancelliamo dal DISCO e dal DB
    if current_web_path:
        # Trasformiamo il percorso web (/documents/...) in percorso fisico (/workspace/documents/...)
        # DOCS_ROOT è definito in alto nel main.py come "/workspace/documents"
        file_system_path = current_web_path.replace("/documents", DOCS_ROOT)
        
        try:
            if os.path.exists(file_system_path):
                os.remove(file_system_path)
                print(f"File eliminato: {file_system_path}")
        except Exception as e:
            print(f"Errore eliminazione file fisico: {e}")
            
        # 4. Aggiorniamo il DB settando a NULL
        supabase.table("products").update({target_col: None}).eq("id", product_id).execute()
        
    return RedirectResponse(f"/admin/products/{product_id}", status_code=302)