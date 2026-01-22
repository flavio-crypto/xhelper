import httpx
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import asyncio

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


async def can_fetch(url: str) -> bool:
    """
    Controlla il robots.txt del dominio per vedere se possiamo accedere.
    """
    try:
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        robots_url = f"{base_url}/robots.txt"
        
        rp = RobotFileParser()
        # Usiamo httpx sincrono o avvolgiamo in run_in_executor se blocca troppo, 
        # ma per semplicità qui facciamo una chiamata rapida.
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(robots_url, timeout=5)
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                    return rp.can_fetch(USER_AGENT, url)
            except:
                # Se non esiste robots.txt, di solito è permesso, ma siamo prudenti
                return True 
        return True
    except Exception:
        return False # Nel dubbio, non scarichiamo

async def fetch_url_content(url: str) -> dict:
    """
    Scarica il contenuto (HTML o PDF).
    Restituisce un dizionario con tipo e contenuto grezzo.
    """
    if not await can_fetch(url):
        return {"error": "Blocked by robots.txt"}

    async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
        try:
            resp = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            resp.raise_for_status()
            
            content_type = resp.headers.get("content-type", "")
            
            if "application/pdf" in content_type:
                return {
                    "type": "pdf",
                    "content": resp.content, # Bytes
                    "url": url
                }
            else:
                return {
                    "type": "html",
                    "text": resp.text, # String HTML
                    "url": url
                }
        except Exception as e:
            return {"error": str(e)}