import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Configurazione Client vLLM (RunPod)
client = OpenAI(
    api_key="EMPTY",
    base_url="http://localhost:8000/v1",
)

MODEL_NAME = "Qwen/Qwen2.5-32B-Instruct-AWQ" 

def ask_qwen(query: str, system_prompt: str = None, json_mode: bool = False) -> str:
    """
    Invia la richiesta a vLLM.
    - json_mode=True: Forza il sistema a comportarsi come un estrattore dati JSON rigoroso.
    """
    
    # Se attiviamo la modalità JSON ma non c'è un prompt specifico, ne usiamo uno di default
    if system_prompt is None:
        if json_mode:
            system_prompt = (
                "Sei un analista dati esperto. Il tuo compito è estrarre informazioni strutturate dal testo fornito. "
                "Rispondi ESCLUSIVAMENTE con un oggetto JSON valido. "
                "Non aggiungere commenti, spiegazioni o blocchi di codice markdown (```json). "
                "Restituisci solo il raw JSON string."
            )
        else:
            system_prompt = (
                "Sei un assistente tecnico esperto per Fuller STP srl. "
                "Ti occupi di ingegneria energetica e sostenibilità. Rispondi in italiano in modo professionale."
            )

    try:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]

        # Parametri ottimizzati per l'estrazione dati
        temperature = 0.1 if json_mode else 0.7
        
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=temperature,
            max_tokens=2000, # Aumentiamo i token per gestire JSON lunghi
        )
        
        return response.choices[0].message.content

    except Exception as e:
        print(f"❌ Errore LLM: {str(e)}")
        return "{}" if json_mode else f"Errore nel generare la risposta: {str(e)}"