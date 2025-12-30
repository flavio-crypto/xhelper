from openai import OpenAI
import sys

# CONFIGURAZIONE
# vLLM gira sulla porta 8000 di default.
# Noi usiamo "localhost" perché siamo nello stesso container o macchina.
VLLM_BASE_URL = "http://localhost:8000/v1"
VLLM_API_KEY = "EMPTY"  # vLLM locale non richiede key reale

# Inizializza il client compatibile con OpenAI
client = OpenAI(
    base_url=VLLM_BASE_URL,
    api_key=VLLM_API_KEY,
)

def get_active_model():
    """
    Recupera dinamicamente il nome del modello caricato in vLLM.
    Evita di dover hardcodare stringhe come 'Qwen/Qwen2.5-...'
    """
    try:
        models = client.models.list()
        # Prende il primo modello disponibile (vLLM di solito ne serve uno alla volta)
        model_id = models.data[0].id
        print(f"INFO: Modello rilevato su vLLM: {model_id}")
        return model_id
    except Exception as e:
        print(f"ATTENZIONE: Impossibile connettersi a vLLM sulla porta 8000. È acceso?\nErrore: {e}")
        # Ritorna un valore di fallback, ma probabilmente la chiamata fallirà dopo
        return "unknown-model"

# Carichiamo il nome del modello una volta sola all'avvio dell'app
MODEL_NAME = get_active_model()

def ask_qwen(query: str, system_prompt: str = None) -> str:
    """
    Invia la richiesta al modello vLLM e restituisce il testo della risposta.
    """
    
    # Prompt di sistema personalizzato per il tuo contesto (Fuller STP)
    if system_prompt is None:
        system_prompt = (
            "Sei un assistente tecnico esperto per Fuller STP srl. "
            "Ti occupi di ingegneria energetica, sostenibilità (CAM, DNSH, LEED) "
            "e verifica normativa. Rispondi in italiano in modo preciso e professionale."
        )

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ],
            temperature=0.7,      # 0.0 = deterministico, 1.0 = creativo
            max_tokens=2048,      # Lunghezza massima della risposta
        )
        return response.choices[0].message.content

    except Exception as e:
        return f"Errore di comunicazione con l'LLM: {str(e)}"

# Blocco di test: se esegui "python app/llm.py" verifichi subito se funziona
if __name__ == "__main__":
    print("Test connessione a vLLM...")
    risposta = ask_qwen("Ciao, sei operativo?")
    print(f"Risposta: {risposta}")