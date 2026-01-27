# Material Compliance Helper (Fuller Suite)

**Material Compliance Helper** è una piattaforma SaaS B2B progettata per automatizzare la verifica della conformità ambientale dei materiali edili. Il software centralizza la ricerca, l'analisi tramite AI e l'archiviazione di documentazione tecnica (Schede Tecniche, EPD, Certificazioni Emissioni), supportando società di ingegneria e imprese di costruzione nel rispetto dei protocolli di sostenibilità (CAM, LEED, WELL).

## 🚀 Caratteristiche Principali

* **Ingestion Intelligente:** Crawler automatizzato per il reperimento di schede tecniche e certificazioni dai siti dei produttori.
* **Analisi AI (LLM):** Estrazione automatica di parametri chiave (VOC, contenuto riciclato, scadenze) dai PDF tramite AI.
* **Data Factory:** Database proprietario di materiali "pre-analizzati" e validati.
* **Gestione Progetti:** Organizzazione dei materiali per commessa e verifica dei crediti (es. LEED v4/v4.1).
* **Compliance Checker:** Algoritmi per il controllo automatico dei requisiti normativi.
* **Ereditarietà Documentale:** Condivisione intelligente dei certificati (EPD, Emissioni) tra prodotti dello stesso brand.

## 🛠 Tech Stack

* **Backend:** Python 3.11+, FastAPI
* **Frontend:** Jinja2 Templates, Tailwind CSS, HTMX (per interazioni dinamiche)
* **Database:** Supabase (PostgreSQL)
* **AI Engine:** Integrazione con LLM (es. Qwen/OpenAI via API)
* **PDF Parsing:** `pypdf`, `pdfplumber`

## 📋 Prerequisiti

* Python 3.11 o superiore
* Account Supabase attivo
* Chiavi API per il servizio LLM

## ⚙️ Installazione

1.  **Clona il repository:**
    ```bash
    git clone [https://github.com/tuo-username/xhelper.git](https://github.com/tuo-username/xhelper.git)
    cd xhelper
    ```

2.  **Crea un ambiente virtuale:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # Su Windows: venv\Scripts\activate
    ```

3.  **Installa le dipendenze:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configurazione Variabili d'Ambiente:**
    Crea un file `.env` (o imposta le variabili nel tuo ambiente di deploy) con:
    ```ini
    SUPABASE_URL="[https://tuo-progetto.supabase.co](https://tuo-progetto.supabase.co)"
    SUPABASE_KEY="la-tua-chiave-anon-o-service"
    # Eventuali altre chiavi per LLM
    ```

## 🚀 Avvio dell'Applicazione

Per avviare il server di sviluppo sulla porta **8080** con ricaricamento automatico:

```bash
uvicorn app.main:app --reload --port 8080