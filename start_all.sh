#!/bin/bash

# 1. Attivazione dell'ambiente virtuale
source venv/bin/activate

# 2. Configurazione Persistenza per Open WebUI
# Impostiamo la cartella dei dati dentro /workspace
export DATA_DIR="/workspace/open-webui-data"
mkdir -p $DATA_DIR
echo "📁 I dati di Open WebUI verranno salvati in: $DATA_DIR"

# 3. Configurazione Porte e Collegamenti
# Porta per l'interfaccia (3000 per evitare conflitti con la 8080)
export PORT=3000
# Indirizzo del modello Qwen3 già in ascolto
export OLLAMA_BASE_URL="http://127.0.0.1:8000"
export OPENAI_API_BASE_URL="http://127.0.0.1:8000/v1"

# 4. Avvio del server Software (Porta 8080) in background
echo "🚀 Avvio del server software sulla porta 8080..."
uvicorn app.main:app --host 0.0.0.0 --port 8080 &

# 5. Avvio di Open WebUI (Porta 3000) in foreground
echo "💬 Avvio di Open WebUI sulla porta 3000..."
# Usiamo exec per far sì che Open WebUI riceva correttamente i segnali di stop del POD
exec open-webui serve