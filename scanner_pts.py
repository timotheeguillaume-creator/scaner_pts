import os
import requests
from bs4 import BeautifulSoup
import yfinance as yf
import google.generativeai as genai

# Configuration de l'API Gemini (La clé sera stockée dans GitHub Secrets)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# 1. Scraper les Tickers du PTS Kabutan (Top Gainers)
def get_pts_tickers():
    print("Étape 1: Récupération des Top Gainers PTS...")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    url = "https://kabutan.jp/pts/"
    
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        tickers = []
        # Extraction des codes à 4 chiffres du marché japonais
        for a in soup.select('td a[href^="/stock/?code="]'):
            code = a.text.strip()
            if code.isdigit() and len(code) == 4 and code not in tickers:
                tickers.append(code)
                
        print(f"{len(tickers)} tickers trouvés sur le PTS.")
        return tickers[:30] # On limite aux 30 plus fortes hausses
    except Exception as e:
        print(f"Erreur de scraping : {e}")
        return []

# 2. Filtrer selon tes critères stricts (Yahoo Finance)
def filter_tickers(tickers):
    print("Étape 2: Filtrage selon tes critères (Prix, Mkt Cap, Volume)...")
    valid_stocks = []
    
    for code in tickers:
        try:
            # ".T" est le suffixe Yahoo Finance pour la Bourse de Tokyo
            ticker_yf = yf.Ticker(f"{code}.T")
            info = ticker_yf.info
            
            # Récupération sécurisée des données
            price = info.get('regularMarketPrice') or info.get('currentPrice', 0)
            mkt_cap = info.get('marketCap', 0)
            avg_vol = info.get('averageVolume10days', 0)
            float_shares = info.get('floatShares', 0) 
            
            # Application de tes règles
            if (150 <= price <= 2300) and \
               (mkt_cap <= 100_000_000_000) and \
               (avg_vol >= 100_000):
                
                # Note: float_shares n'est pas toujours dispo sur les micro-caps JP, 
                # le Market Cap < 100B fait déjà office de filtre principal.
                
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

# 3. Analyser le catalyseur avec l'IA Gemini
def analyze_catalyst(valid_stocks):
    print("Étape 3: Recherche de news et analyse IA...")
    
    for stock in valid_stocks:
        code = stock['code']
        ticker_yf = yf.Ticker(f"{code}.T")
        news_list = ticker_yf.news
        
        if not news_list:
            print(f"\n[{code}] - Aucune news récente trouvée.")
            continue
            
        # Concaténer les titres récents pour l'IA
        news_text = " | ".join([n['title'] for n in news_list[:3]])
        
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
            response = model.generate_content(prompt)
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
