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
import math

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

    # --- FIX: Recuperiamo i materiali assegnati al credito MR EPD ---
    # Senza questa parte, la lista nel riquadro della dashboard rimane vuota
    from app.database import get_project_materials
    try:
        assigned_materials = get_project_materials(project_id, "MR_EPD")
    except Exception as e:
        print(f"Errore recupero materiali: {e}")
        assigned_materials = []

    return templates.TemplateResponse("project_home.html", {
        "request": request, 
        "user": user, 
        "active_project": project,
        "assigned_materials": assigned_materials # <--- Passiamo i dati al template
    })

# --- INCOLLA IN app/main.py (es. dopo la rotta view_project) ---

@app.delete("/projects/{project_id}")
async def delete_project(request: Request, project_id: str):
    user = get_current_user(request)
    if not user: return HTMLResponse("Non autorizzato", status_code=403)
    
    # Importiamo la funzione appena creata
    from app.database import delete_project_db
    
    if delete_project_db(project_id):
        # Restituisce stringa vuota: HTMX rimuoverà l'elemento HTML dalla pagina
        return HTMLResponse("")
    else:
        return HTMLResponse("Impossibile eliminare il progetto", status_code=500)



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

# Cerca questa funzione in app/main.py e sostituiscila

@app.get("/admin/manufacturers/delete/{man_id}")
async def delete_manufacturer(request: Request, man_id: str):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    try:
        # Tenta l'eliminazione
        supabase.table("companies").delete().eq("id", man_id).execute()
        return RedirectResponse("/admin/manufacturers", status_code=302)
        
    except Exception as e:
        print(f"Errore eliminazione produttore: {e}")
        
        # In caso di errore (es. Foreign Key), ricarichiamo la lista e mostriamo l'errore
        res = supabase.table("companies").select("*").order("name").execute()
        
        return templates.TemplateResponse("admin_manufacturers.html", {
            "request": request, 
            "user": user, 
            "companies": res.data, 
            "edit_data": None, # Reset del form modifica
            "error_msg": "Impossibile eliminare: ci sono prodotti collegati a questo produttore. Elimina prima i prodotti."
        })

# --- DATA FACTORY ---

@app.get("/admin/data-factory", response_class=HTMLResponse)
async def admin_data_factory(request: Request):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    # Carichiamo la pagina base vuota a destra (nessun dato dal DB!)
    return templates.TemplateResponse("admin_data_factory.html", {
        "request": request, "user": user, "drafts": [] 
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
            # process_batch_item ora restituisce dati, NON salva
            res = await process_batch_item(man, prod, url)
            results.append(res)
            
    # Usiamo il template delle card volatili
    return templates.TemplateResponse("partials/draft_list.html", {
        "request": request, "results": results
    })

# Modifica questa funzione in app/main.py

@app.post("/admin/products/confirm-draft")
async def confirm_draft(
    request: Request,
    company_id: str = Form(...),
    name: str = Form(...),
    category: str = Form(...),
    description: str = Form(""),
    url_technical_sheet: str = Form(""),
    epd_url: str = Form(None),
    is_recycled: str = Form("false")
):
    user = get_current_user(request)
    if not user: return HTMLResponse("Errore auth", status_code=403)

    # 1. Salvataggio nel DB
    data = {
        "company_id": company_id,
        "name": name,
        "category": category,
        "description": description,
        "url_technical_sheet": url_technical_sheet,
        "epd_url": epd_url if epd_url else None,
        "is_recycled": True if is_recycled == 'true' else False,
        "is_validated": False
    }
    
    try:
        res = supabase.table("products").insert(data).execute()
        new_id = res.data[0]['id']
        
        # 2. RISPOSTA HTMX (Non redirect!)
        # Restituiamo un nuovo blocco di pulsanti che sostituisce quelli vecchi
        return HTMLResponse(f"""
            <div class="flex flex-col gap-2 shrink-0 animate-fade-in">
                <a href="/admin/products/{new_id}" target="_blank"
                   class="bg-green-100 text-green-700 border border-green-200 px-3 py-1.5 rounded-lg text-xs font-bold hover:bg-green-200 text-center w-24 flex items-center justify-center">
                   <i class="fa-solid fa-pen-to-square mr-1"></i> Modifica
                </a>
                <span class="text-[10px] text-green-600 text-center font-medium">
                   <i class="fa-solid fa-check"></i> Salvato
                </span>
            </div>
        """)
        
    except Exception as e:
        print(f"Errore salvataggio: {e}")
        return HTMLResponse(f"<div class='text-red-500 text-xs'>Errore: {str(e)}</div>", status_code=500)


@app.post("/admin/validate-product/{product_id}")
async def validate_product(product_id: str):
    supabase.table("products").update({"is_validated": True}).eq("id", product_id).execute()
    return HTMLResponse('<span class="text-green-600 font-bold">Validato!</span>')

# --- GESTIONE PRODOTTI (CRUD) ---
import math

# ... (altre funzioni e import)

@app.get("/admin/products", response_class=HTMLResponse)
async def admin_products_list(
    request: Request, 
    search_company: str = "", 
    search_product: str = "", 
    search_category: str = "", 
    page: int = 1
):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")

    limit = 20
    offset = (page - 1) * limit

    # Query Base
    query = supabase.table("products").select("*, companies!inner(name)", count="exact")

    # 1. Filtro Azienda (se presente)
    if search_company:
        query = query.ilike("companies.name", f"%{search_company}%")
    
    # 2. Filtro Prodotto/Descrizione (se presente)
    if search_product:
        # Cerca nel nome O nella descrizione
        query = query.or_(f"name.ilike.%{search_product}%,description.ilike.%{search_product}%")

    # 3. Filtro Categoria (se presente)
    if search_category:
        query = query.ilike("category", f"%{search_category}%")

    # Esecuzione con paginazione
    res = query.order("name").range(offset, offset + limit - 1).execute()

    products = res.data
    total_items = res.count if res.count else 0
    total_pages = math.ceil(total_items / limit)

    return templates.TemplateResponse("admin_products_list.html", {
        "request": request, 
        "user": user, 
        "products": products,
        "search_company": search_company,
        "search_product": search_product,
        "search_category": search_category,
        "page": page,
        "total_pages": total_pages,
        "total_items": total_items
    })

@app.get("/admin/products/{id}", response_class=HTMLResponse)
async def admin_product_detail(request: Request, id: str):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")

    # 1. Recupera il Prodotto
    prod_res = supabase.table("products").select("*, companies(name)").eq("id", id).single().execute()
    product = prod_res.data

    # 2. Recupera la Compliance (Tabella emission_products)
    # Cerchiamo se esiste una riga per questo prodotto
    try:
        emis_res = supabase.table("emission_products").select("*").eq("product_id", id).single().execute()
        emission_data = emis_res.data
    except:
        # Se non c'è, passiamo un dizionario vuoto
        emission_data = {}

    companies = supabase.table("companies").select("*").order("name").execute().data
    categories = [
        "Isolanti Termici", "Impermeabilizzanti", "Cartongesso e Lastre",
        "Intonaci e Malte", "Adesivi e Sigillanti", "Pavimenti e Rivestimenti",
        "Vernici e Finiture", "Calcestruzzi e Cementi", "Laterizi e Blocchi",
        "Facciate e Cappotti", "Serramenti e Vetri", "Impianti HVAC"
    ]

    return templates.TemplateResponse("admin_product_detail.html", {
        "request": request, 
        "user": user, 
        "product": product,
        "emission_data": emission_data, # Passiamo i dati specifici
        "companies": companies, 
        "categories": categories
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
    url_technical_sheet: str = Form(""),
    
    # EPD
    epd_url: str = Form(None),
    epd_expiration: str = Form(None),
    epd_type: str = Form(None), # <--- NUOVO CAMPO
    
    # Emissioni
    emission_url: str = Form(None),
    emission_expiration: str = Form(None),
    
    # Flags
    is_validated: str = Form("false"),
    is_recycled: str = Form("false"),
    
    # Compliance LEED (Tabella Separata)
    leed_v4: str = Form("false"),
    leed_v41: str = Form("false"),
    leed_v5: str = Form("false")
):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")

    # 1. Aggiornamento Tabella PRODUCTS
    prod_data = {
        "name": name,
        "company_id": company_id,
        "category": category,
        "description": description,
        "url_technical_sheet": url_technical_sheet,
        
        # Gestione EPD
        "epd_url": epd_url or None,
        "epd_expiration": epd_expiration or None,
        "epd_type": epd_type or None, # <--- Salvataggio tipo
        
        "emission_url": emission_url or None,
        "emission_expiration": emission_expiration or None,
        
        "is_validated": True if is_validated == 'true' else False,
        "is_recycled": True if is_recycled == 'true' else False,
    }

    if id:
        supabase.table("products").update(prod_data).eq("id", id).execute()
        product_id = id
    else:
        res = supabase.table("products").insert(prod_data).execute()
        product_id = res.data[0]['id']

    # 2. Aggiornamento Tabella EMISSION_PRODUCTS (Compliance)
    existing_check = supabase.table("emission_products").select("id").eq("product_id", product_id).execute()
    
    emission_payload = {
        "leed_v4_compliant": True if leed_v4 == 'true' else False,
        "leed_v41_compliant": True if leed_v41 == 'true' else False,
        "leed_v5_compliant": True if leed_v5 == 'true' else False
    }

    if existing_check.data:
        row_id = existing_check.data[0]['id']
        supabase.table("emission_products").update(emission_payload).eq("id", row_id).execute()
    else:
        emission_payload["product_id"] = product_id
        supabase.table("emission_products").insert(emission_payload).execute()

    return RedirectResponse(f"/admin/products/{product_id}", status_code=302)


@app.get("/admin/products/delete/{product_id}")
async def admin_product_delete(request: Request, product_id: str):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    supabase.table("products").delete().eq("id", product_id).execute()
    return RedirectResponse("/admin/products", status_code=302)

    # --- ROTTE PER I CREDITI LEED (AGGIUNTE) ---

# In app/main.py

@app.post("/projects/{project_id}/credits/mr_epd/search", response_class=HTMLResponse)
async def search_credit_mr_epd(
    request: Request, 
    project_id: str,
    category: str = Form(...),
    leed_version: str = Form(...), # <--- Cambiato da epd_type a leed_version
    search_text: str = Form("")
):
    user = get_current_user(request)
    if not user: return HTMLResponse("Sessione scaduta", status_code=403)
    
    from app.database import search_products_db, get_project_materials
    
    # 1. Recuperiamo i materiali GIÀ assegnati (Blacklist)
    assigned_data = get_project_materials(project_id, "MR_EPD")
    
    excluded_ids = []
    if assigned_data:
        for row in assigned_data:
            if row.get('products') and row['products'].get('id'):
                excluded_ids.append(row['products']['id'])
    
    # 2. Cerchiamo nel DB passando la versione LEED
    results = search_products_db(
        category=category, 
        leed_version=leed_version, # <--- Passiamo il nuovo parametro
        search_text=search_text, 
        exclude_ids=excluded_ids
    )
    
    return templates.TemplateResponse("partials/material_results_list.html", {
        "request": request,
        "materials": results, 
        "active_project_id": project_id
    })

@app.post("/projects/{project_id}/credits/mr_epd/assign")
async def assign_credit_mr_epd(
    request: Request, 
    project_id: str,
    material_id: str = Form(...)
):
    user = get_current_user(request)
    if not user: return HTMLResponse("Errore auth", status_code=403)
    
    from app.database import assign_material_to_project, get_project_materials
    
    # 1. Eseguiamo l'assegnazione
    assign_material_to_project(project_id, material_id, "MR_EPD")
    
    # 2. Recuperiamo la lista aggiornata
    updated_list = get_project_materials(project_id, "MR_EPD")
    
    # 3. Restituiamo il partial della lista aggiornata
    return templates.TemplateResponse("partials/project_materials_list.html", {
        "request": request,
        "assigned_materials": updated_list,
        "active_project_id": project_id
    })


# Incolla in app/main.py se non c'è già

@app.delete("/projects/{project_id}/credits/mr_epd/remove/{assignment_id}")
async def remove_credit_material(
    request: Request,
    project_id: str,
    assignment_id: str
):
    user = get_current_user(request)
    if not user: return HTMLResponse("Errore auth", status_code=403)
    
    from app.database import remove_material_from_project
    
    # Cancelliamo la riga
    remove_material_from_project(assignment_id)
    
    # Restituiamo stringa vuota per rimuovere l'elemento HTML dalla pagina
    return HTMLResponse("")

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
    
    # Recuperiamo le categorie per il filtro
    res_cats = supabase.table("products").select("category").execute()
    categories = sorted(list(set([row['category'] for row in res_cats.data if row['category']])))
    
    # Recuperiamo i materiali GIÀ assegnati a questo credito
    from app.database import get_project_materials
    assigned_materials = get_project_materials(project_id, "MR_EPD")

    return templates.TemplateResponse("credits/mr_epd.html", {
        "request": request, 
        "user": user, 
        "active_project": project, 
        "categories": categories,
        "assigned_materials": assigned_materials # Passiamo la lista al template
    })

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


    # --- FUNZIONI DI CONDIVISIONE DOCUMENTI (SHARING) ---

@app.get("/admin/products/share-candidates/{doc_type}/{company_id}/{current_id}", response_class=HTMLResponse)
async def get_share_candidates(request: Request, doc_type: str, company_id: str, current_id: str):
    user = get_current_user(request)
    if not user: return HTMLResponse("Accesso negato", status_code=403)

    # Definiamo quale colonna controllare per vedere se il documento esiste
    # Cerchiamo prodotti che abbiano ALMENO il file fisico O il link web
    if doc_type == "epd":
        filter_condition = "or(epd_file_path.neq.null,epd_url.neq.null)"
    elif doc_type == "emission":
        filter_condition = "or(emission_file_path.neq.null,emission_url.neq.null)"
    else:
        return HTMLResponse("Tipo documento non valido")

    # Query: Stessa azienda, documento presente, ESCLUSO se stesso
    # Nota: Supabase-py ha limiti sui filtri complessi OR, facciamo una select più ampia e filtriamo in Python per sicurezza
    candidates_res = supabase.table("products")\
        .select("id, name, epd_expiration, emission_expiration, epd_file_path, emission_file_path")\
        .eq("company_id", company_id)\
        .neq("id", current_id)\
        .order("name")\
        .execute()
    
    # Filtriamo in python per precisione
    valid_candidates = []
    for p in candidates_res.data:
        if doc_type == "epd" and (p.get('epd_file_path') or p.get('epd_url')): # Nota: epd_url non era nella select, aggiungiamolo se serve, ma qui controlliamo il path primario
             valid_candidates.append(p)
        elif doc_type == "emission" and (p.get('emission_file_path') or p.get('emission_url')):
             valid_candidates.append(p)
    
    # Renderizziamo una lista HTML parziale (da iniettare nella modale)
    html_content = """<div class="space-y-2 max-h-[300px] overflow-y-auto">"""
    
    if not valid_candidates:
        html_content += """<div class="text-slate-400 text-sm text-center py-4">Nessun altro prodotto di questa azienda ha questo documento.</div>"""
    else:
        for cand in valid_candidates:
            # Info da mostrare
            date_info = ""
            if doc_type == "epd" and cand.get('epd_expiration'): date_info = f"<span class='text-xs text-slate-400 ml-2'>Scad: {cand['epd_expiration']}</span>"
            if doc_type == "emission" and cand.get('emission_expiration'): date_info = f"<span class='text-xs text-slate-400 ml-2'>Scad: {cand['emission_expiration']}</span>"
            
            # Badge File
            file_badge = ""
            has_file = cand.get(f"{doc_type}_file_path")
            if has_file: file_badge = "<i class='fa-solid fa-file-pdf text-brand-500 mr-2' title='File Fisico presente'></i>"
            else: file_badge = "<i class='fa-solid fa-link text-blue-500 mr-2' title='Solo Link Web'></i>"

            html_content += f"""
            <div class="flex items-center justify-between p-3 bg-slate-50 hover:bg-slate-100 rounded-lg border border-slate-200 transition-colors cursor-pointer"
                 onclick="selectSourceProduct('{cand['id']}')">
                <div class="flex items-center">
                    {file_badge}
                    <span class="font-bold text-slate-700 text-sm">{cand['name']}</span>
                    {date_info}
                </div>
                <button type="button" class="text-xs bg-white border border-slate-300 px-3 py-1 rounded shadow-sm hover:text-brand-600 font-bold">
                    Usa Questo
                </button>
            </div>
            """
    html_content += "</div>"
    
    return HTMLResponse(html_content)


@app.post("/admin/products/copy-doc-data")
async def copy_doc_data(
    request: Request,
    target_id: str = Form(...),
    source_id: str = Form(...),
    doc_type: str = Form(...)
):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")

    # 1. Recuperiamo i dati del prodotto SORGENTE (Donatore)
    source_res = supabase.table("products").select("*").eq("id", source_id).single().execute()
    source_data = source_res.data
    
    if not source_data:
        return HTMLResponse("Prodotto sorgente non trovato", status_code=404)

    # 2. Prepariamo i dati da copiare in base al tipo
    update_data = {}
    
    if doc_type == "epd":
        update_data = {
            "epd_url": source_data.get("epd_url"),
            "epd_file_path": source_data.get("epd_file_path"),
            "epd_expiration": source_data.get("epd_expiration"),
            "epd_type": source_data.get("epd_type")
        }
    elif doc_type == "emission":
        update_data = {
            "emission_url": source_data.get("emission_url"),
            "emission_file_path": source_data.get("emission_file_path"),
            "emission_expiration": source_data.get("emission_expiration")
        }
    
    # 3. Aggiorniamo il prodotto TARGET (Ricevente)
    supabase.table("products").update(update_data).eq("id", target_id).execute()
    
    # Ricarichiamo la pagina
    return RedirectResponse(f"/admin/products/{target_id}", status_code=302)

    # Aggiungi questa funzione in app/main.py

@app.post("/admin/products/bulk-delete")
async def bulk_delete_products(request: Request, product_ids: list[str] = Form(...)):
    user = get_current_user(request)
    if not user: return RedirectResponse("/")
    
    try:
        # Cancellazione massiva usando il filtro .in_()
        supabase.table("products").delete().in_("id", product_ids).execute()
        return RedirectResponse("/admin/products", status_code=302)
        
    except Exception as e:
        print(f"Errore eliminazione massiva: {e}")
        # In caso di errore (es. integrità referenziale), ricarichiamo la pagina con errore
        # Nota: per semplicità facciamo redirect, ma l'ideale sarebbe passare l'errore come query param
        return RedirectResponse("/admin/products?error=bulk_delete_error", status_code=302)