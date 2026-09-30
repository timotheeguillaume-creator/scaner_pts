import os
import re
import requests
import yfinance as yf
from google import genai

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# 1. Scraper les Tickers PTS depuis Minkabu
def get_pts_tickers():
    print("Étape 1: Récupération des Top Gainers PTS...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    url_minkabu = "https://r.jina.ai/https://minkabu.jp/ranking/pts/gainers"
    url_yahoo_jp = "https://r.jina.ai/https://finance.yahoo.co.jp/data/ranking/pts-price-increase"

    tickers = []
    
    # Tentative via Minkabu
    try:
        res = requests.get(url_minkabu, headers=headers, timeout=15)
        if res.status_code == 200 and "Human Verification" not in res.text:
            print("✅ Données récupérées depuis Minkabu PTS.")
            found = re.findall(r'/stock/(\d{4})', res.text) or re.findall(r'\b([1-9]\d{3})\b', res.text)
            for code in found:
                if code not in {'2024', '2025', '2026', '2027'} and code not in tickers:
                    tickers.append(code)
    except Exception as e:
        print(f"Échec Minkabu : {e}")

    # Fallback via Yahoo Finance JP
    if not tickers:
        try:
            print("Tentative de secours via Yahoo Finance JP...")
            res = requests.get(url_yahoo_jp, headers=headers, timeout=15)
            if res.status_code == 200 and "Human Verification" not in res.text:
                found = re.findall(r'/quote/(\d{4})', res.text) or re.findall(r'\b([1-9]\d{3})\b', res.text)
                for code in found:
                    if code not in {'2024', '2025', '2026', '2027'} and code not in tickers:
                        tickers.append(code)
        except Exception as e:
            print(f"Échec Yahoo Finance JP : {e}")

    print(f"✅ {len(tickers)} tickers bruts extraits du PTS.")
    return tickers[:30]

# 2. Filtrer selon tes critères stricts (Yahoo Finance)
def filter_tickers(tickers):
    print("\nÉtape 2: Application de tes filtres (Prix, Mkt Cap, Volume)...")
    valid_stocks = []
    
    for code in tickers:
        try:
            ticker_yf = yf.Ticker(f"{code}.T")
            info = ticker_yf.info
            
            price = info.get('regularMarketPrice') or info.get('currentPrice', 0)
            mkt_cap = info.get('marketCap', 0)
            avg_vol = info.get('averageVolume10days', 0)
            
            # Filtres : Prix 150-2300 JPY | Mkt Cap <= 100B JPY | Vol 10j >= 100k
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
            
    print(f"📊 {len(valid_stocks)} / {len(tickers)} actions correspondent à tes critères.")
    return valid_stocks

# 3. Analyser le catalyseur avec Gemini API
def analyze_catalyst(valid_stocks):
    print("\nÉtape 3: Analyse IA des catalyseurs...")
    if not client:
        print("Erreur: Clé API Gemini non disponible.")
        return

    for stock in valid_stocks:
        code = stock['code']
        ticker_yf = yf.Ticker(f"{code}.T")
        
        try:
            news_list = ticker_yf.news
        except Exception:
            news_list = []
        
        news_text = " | ".join([n.get('title', '') for n in news_list[:3]]) if news_list else "Pas de news récente."
        
        prompt = f"""
        Tu es un analyste financier expert du marché japonais.
        Voici les dernières actualités pour le titre {code} (Tokyo) : "{news_text}".
        1. Identifie la raison de la hausse (résultats, rachat, contrat, etc.).
        2. Donne-lui un score d'impact de 1 à 10.
        3. Fais un résumé d'une seule phrase en français.
        Réponds uniquement sous le format :
        Catalyseur: [Type] | Score: [X]/10 | Résumé: [Ta phrase]
        """
        
        try:
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=prompt
            )
            print(f"\n🚀 ACTION SÉLECTIONNÉE : {code} ({stock['price']} ¥)")
            print(f"Mkt Cap: {stock['mkt_cap']/1_000_000_000:.2f} B¥ | Vol 10j: {stock['avg_vol']}")
            print(response.text.strip())
        except Exception as e:
            print(f"[{code}] - Erreur Gemini : {e}")

if __name__ == "__main__":
    if not GEMINI_API_KEY:
        print("Erreur: Clé API Gemini manquante dans GitHub Secrets.")
        exit(1)
        
    tickers = get_pts_tickers()
    if tickers:
        filtered = filter_tickers(tickers)
        if filtered:
            analyze_catalyst(filtered)
        else:
            print("ℹ️ Aucun ticker ne respecte tes filtres de prix / capitalisation / volume aujourd'hui.")
    else:
        print("⚠️ Problème à l'étape 1 : Impossible de récupérer le classement PTS.")
