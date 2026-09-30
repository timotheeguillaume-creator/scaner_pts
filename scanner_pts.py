import os
import re
import time
import requests
import yfinance as yf
from google import genai

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

# 1. Scraper les Tickers PTS depuis Minkabu
def get_pts_tickers():
    print("Étape 1: Récupération des Top Gainers PTS...")
    url_minkabu = "https://r.jina.ai/https://minkabu.jp/ranking/pts/gainers"
    tickers = []
    
    try:
        res = requests.get(url_minkabu, headers=HEADERS, timeout=20)
        if res.status_code == 200:
            print("✅ Données récupérées depuis Minkabu PTS.")
            found = re.findall(r'/stock/(\d{4})', res.text) or re.findall(r'\b([1-9]\d{3})\b', res.text)
            for code in found:
                if code not in {'2024', '2025', '2026', '2027'} and code not in tickers:
                    tickers.append(code)
    except Exception as e:
        print(f"Échec Minkabu : {e}")

    print(f"✅ {len(tickers)} tickers bruts extraits du PTS.")
    return tickers[:30]

# 2. Filtrer selon tes critères stricts (Prix, Mkt Cap, Volume)
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

# Récupérer les vraies actualités en japonais depuis Minkabu News
def fetch_jp_news(code):
    try:
        url = f"https://r.jina.ai/https://minkabu.jp/stock/{code}/news"
        res = requests.get(url, headers=HEADERS, timeout=15)
        if res.status_code == 200:
            # Filtrer les lignes vides ou trop courtes (souvent le menu de navigation)
            lines = [line.strip() for line in res.text.split('\n') if len(line.strip()) > 20]
            # On ignore les 5 premières lignes et on garde les 15 suivantes (cœur de l'article)
            clean_text = " | ".join(lines[5:20])
            return clean_text[:1500]
    except Exception:
        pass
    return "Pas d'actualité récente disponible."

# 3. Analyser le catalyseur avec Gemini API
def analyze_catalyst(valid_stocks):
    print("\nÉtape 3: Analyse IA des catalyseurs (News Minkabu en direct)...")
    if not client:
        print("Erreur: Clé API Gemini non disponible.")
        return

    for stock in valid_stocks:
        code = stock['code']
        news_jp = fetch_jp_news(code)
        
        prompt = f"""
        Tu es un analyste financier expert du marché japonais (Tokyo Stock Exchange).
        Voici le contenu récent extrait des actualités pour l'action {code} :
        "{news_jp}"

        Tâche :
        1. Analyse le contenu pour détecter une vraie annonce d'entreprise (Résultats financiers, Révision, Rachat d'actions, Partenariat, Nouveau produit).
        2. Si aucune annonce claire n'est visible, indique si le mouvement est spéculatif.
        3. Assigne un score d'impact réel de 1 à 10 pour un trade intraday.
        4. Fais un résumé synthétique d'une phrase en français.

        Réponds STRICTEMENT sous ce format :
        Catalyseur: [Type] | Score: [X]/10 | Résumé: [Phrase synthétique]
        """
        
        # 4 tentatives avec un long temps d'arrêt pour éviter les 429 Resource Exhausted
        for attempt in range(4):
            try:
                response = client.models.generate_content(
                    model='gemini-3.8-flash',
                    contents=prompt
                )
                print(f"\n🚀 ACTION SÉLECTIONNÉE : {code} ({stock['price']} ¥)")
                print(f"Mkt Cap: {stock['mkt_cap']/1_000_000_000:.2f} B¥ | Vol 10j: {stock['avg_vol']}")
                print(response.text.strip())
                
                # PAUSE DE SÉCURITÉ ABSOLUE : 25 SECONDES
                time.sleep(25) 
                break
            except Exception as e:
                if "429" in str(e) or "503" in str(e) or "quota" in str(e).lower():
                    print(f"[{code}] Quota ou charge serveur (Essai {attempt+1}/4), pause de 30s...")
                    time.sleep(30)
                else:
                    print(f"[{code}] Erreur API Gemini : {e}")
                    break

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
            print("ℹ️ Aucun ticker ne respecte tes filtres de prix / capitalisation / volume aujourd'hui.")
    else:
        print("⚠️ Problème à l'étape 1 : Impossible de récupérer le classement PTS.")
