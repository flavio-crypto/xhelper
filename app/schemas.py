# app/schemas.py
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import date

# Modello per le singole proprietà tecniche (va nel campo JSONB 'properties')
class TechProperty(BaseModel):
    name: str = Field(..., description="Nome della proprietà (es. Conducibilità Termica)")
    value: str = Field(..., description="Valore numerico o stringa (es. 0.035)")
    unit: Optional[str] = Field(None, description="Unità di misura (es. W/mK)")
    standard: Optional[str] = Field(None, description="Norma di riferimento (es. EN 12667)")

# Modello principale di Output (Ciò che vogliamo dal LLM)
class ProductExtraction(BaseModel):
    # Dati Anagrafici
    manufacturer_name: str = Field(..., description="Nome del produttore (es. Mapei)")
    product_name: str = Field(..., description="Nome commerciale del prodotto")
    category: Optional[str] = Field(None, description="Categoria macro (es. Isolante, Intonaco)")
    description: Optional[str] = Field(None, description="Breve descrizione funzionale")
    
    # Dati EPD (Se presenti nel documento)
    epd_registration_number: Optional[str] = Field(None, description="Numero registrazione EPD")
    gwp_total: Optional[float] = Field(None, description="Global Warming Potential totale (GWP)")
    epd_expiration_date: Optional[str] = Field(None, description="Data scadenza EPD (YYYY-MM-DD)")
    
    # Dati Tecnici (Vanno nel JSONB)
    technical_specs: List[TechProperty] = Field(default_factory=list, description="Lista delle proprietà tecniche estratte")

    # Flag
    is_recycled: bool = Field(False, description="True se il testo menziona contenuto riciclato")