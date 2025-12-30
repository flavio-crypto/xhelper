from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
from app.llm import ask_qwen  # Assumo che questa funzione sia sincrona o gestita correttaemente
import secrets

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")

# --- Configurazione Utente (Demo) ---
USERNAME = "admin"
# Hash di "GH2026"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASSWORD_HASH = pwd_context.hash("GH2026")

def verify_credentials(username: str, password: str):
    # Verifica semplice: controlla username e hash della password
    if username != USERNAME:
        return False
    return pwd_context.verify(password, PASSWORD_HASH)

def check_auth(request: Request):
    """Funzione helper per verificare se il cookie di sessione esiste"""
    return request.cookies.get("session_token") is not None

# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    if check_auth(request):
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/", response_class=HTMLResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if verify_credentials(username, password):
        response = RedirectResponse("/dashboard", status_code=302)
        # In produzione, gestire i token in un database o cache (Redis)
        response.set_cookie(key="session_token", value=secrets.token_hex(16), httponly=True)
        return response
    return templates.TemplateResponse("login.html", {"request": request, "error": "Credenziali errate"})

@app.get("/logout")
async def logout():
    response = RedirectResponse("/")
    response.delete_cookie("session_token")
    return response

# --- Dashboard e LLM ---

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_view(request: Request):
    if not check_auth(request):
        return RedirectResponse("/")
    
    # Mostra la dashboard pulita
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "response": None
    })

@app.post("/dashboard", response_class=HTMLResponse)
async def dashboard_ask(request: Request, user_query: str = Form(...)):
    if not check_auth(request):
        return RedirectResponse("/")

    # 1. Chiama il tuo modulo LLM
    try:
        # Passiamo la query dell'utente alla tua funzione ask_qwen
        llm_response = ask_qwen(user_query)
    except Exception as e:
        llm_response = f"Errore nella comunicazione con l'LLM: {str(e)}"

    # 2. Ricarica la pagina mostrando la risposta
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user_query": user_query, # Utile per lasciare il testo nella casella
        "response": llm_response
    })

# Route di test rapido (opzionale, utile per debug API)
@app.get("/test-llm")
async def test_llm():
    response = ask_qwen("Dimmi ciao in italiano")
    return {"risposta": response}