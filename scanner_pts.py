import os
import re
import requests
import yfinance as yf
from google import genai

# Configuration de l'API Gemini avec le SDK officiel google-genai
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# 1. Scraper les Tickers du PTS Kabutan via Jina AI Reader
def get_pts_tickers():
    print("Étape 1: Récupération des Top Gainers PTS...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    url_jina = "https://r.jina.ai/https://kabutan.jp/pts/"
    
    try:
        response = requests.get(url_jina, headers=headers, timeout=20)
        print(f"Statut HTTP (via Jina Reader) : {response.status_code}")
        
        if response.status_code != 200:
            print("Erreur d'accès à la page des données PTS.")
            return []

        raw_text = response.text
        
        # Extraction ciblée des codes tickers à 4 chiffres dans les liens Markdown
        found_codes = re.findall(r'code=(\d{4})', raw_text) + re.findall(r'/stock/\?code=(\d{4})', raw_text)
        
        # Fallback par Regex élargie si aucun paramètre URL n'est trouvé
        if not found_codes:
            found_codes = re.findall(r'\b([1-9]\d{3})\b', raw_text)

        tickers = []
        excluded_numbers = {'2024', '2025', '2026', '2027'}
        for code in found_codes:
            if code not in excluded_numbers and code not in tickers:
                tickers.append(code)

        print(f"{len(tickers)} tickers extraits du PTS.")
        return tickers[:30]

    except Exception as e:
        print(f"Erreur de connexion : {e}")
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
            
            # Filtres : Prix 150-2300 JPY, Market Cap <= 100B JPY, Vol 10j >= 100k
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
        print("Erreur: Clé API Gemini non initialisée.")
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
