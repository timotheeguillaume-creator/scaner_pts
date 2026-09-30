import os
import re
import requests
from bs4 import BeautifulSoup
import yfinance as yf
from google import genai

# Configuration de l'API Gemini avec le nouveau SDK officiel google-genai
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# 1. Scraper les Tickers du PTS Kabutan avec entêtes renforcés
def get_pts_tickers():
    print("Étape 1: Récupération des Top Gainers PTS...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept-Language': 'ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://kabutan.jp/'
    }
    url = "https://kabutan.jp/pts/"
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        print(f"Statut HTTP Kabutan : {response.status_code}")
        
        if response.status_code != 200:
            print("Impossible d'accéder à Kabutan (blocage d'accès).")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        tickers = []
        
        # Recherche robuste des codes à 4 chiffres dans les liens
        for a in soup.find_all('a', href=re.compile(r'/stock/.*code=\d{4}')):
            text = a.text.strip()
            match = re.search(r'\b\d{4}\b', text) or re.search(r'code=(\d{4})', a.get('href', ''))
            if match:
                code = match.group(1) if 'code=' in match.group(0) else match.group(0)
                if code.isdigit() and code not in tickers:
                    tickers.append(code)

        # Fallback par Regex brute si le sélecteur HTML échoue
        if not tickers:
            matches = re.findall(r'/stock/\?code=(\d{4})', response.text)
            for code in matches:
                if code not in tickers:
                    tickers.append(code)

        print(f"{len(tickers)} tickers trouvés sur le PTS.")
        return tickers[:30]
    except Exception as e:
        print(f"Erreur de scraping : {e}")
        return []

# 2. Filtrer selon tes critères stricts (Yahoo Finance)
def filter_tickers(tickers):
    print("Étape 2: Filtrage selon tes critères (Prix, Mkt Cap, Volume)...")
    valid_stocks = []
    
    for code in tickers:
        try:
            ticker_yf = yf.Ticker(f"{code}.T")
            info = ticker_yf.info
            
            price = info.get('regularMarketPrice') or info.get('currentPrice', 0)
            mkt_cap = info.get('marketCap', 0)
            avg_vol = info.get('averageVolume10days', 0)
            
            if (150 <= price <= 2300) and \
               (mkt_cap <= 100_000_000_000) and \
               (avg_vol >= 100_000):
                
                valid_stocks.append({
                    'code': code,
                    'price': price,
                    'mkt_cap': mkt_cap,
                    'avg_vol': avg_vol
                })
        except Exception:
            continue
            
    print(f"{len(valid_stocks)} actions correspondent à tes critères.")
    return valid_stocks

# 3. Analyser le catalyseur avec Gemini API
def analyze_catalyst(valid_stocks):
    print("Étape 3: Recherche de news et analyse IA...")
    
    if not client:
        print("Erreur: Client Gemini non initialisé.")
        return

    for stock in valid_stocks:
        code = stock['code']
        ticker_yf = yf.Ticker(f"{code}.T")
        
        try:
            news_list = ticker_yf.news
        except Exception:
            news_list = []
        
        if not news_list:
            news_text = "Pas de titre de news récent disponible."
        else:
            news_text = " | ".join([n.get('title', '') for n in news_list[:3]])
        
        prompt = f"""
        Tu es un analyste financier expert du marché japonais.
        Voici les dernières actualités pour le titre {code} de la bourse de Tokyo : "{news_text}".
        1. Identifie la raison de la hausse (résultats, rachat, contrat, etc.).
        2. Donne-lui un score d'impact de 1 à 10.
        3. Fais un résumé d'une seule phrase en français.
        Réponds uniquement sous le format :
        Catalyseur: [Type] | Score: [X]/10 | Résumé: [Ta phrase]
        """
        
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            print(f"\n✅ ACTION RETENUE : {code} (Prix: {stock['price']} ¥)")
            print(f"Mkt Cap: {stock['mkt_cap']/1_000_000_000:.2f} B¥ | Vol 10j: {stock['avg_vol']}")
            print(response.text.strip())
        except Exception as e:
            print(f"\n[{code}] - Erreur API Gemini : {e}")

# Exécution principale
if __name__ == "__main__":
    if not GEMINI_API_KEY:
        print("Erreur: Clé API Gemini manquante.")
        exit(1)
        
    tickers = get_pts_tickers()
    if tickers:
        filtered = filter_tickers(tickers)
        if filtered:
            analyze_catalyst(filtered)
        else:
            print("Aucune action ne passe les filtres aujourd'hui.")
    else:
        print("Aucun ticker récupéré lors de l'étape 1.")
