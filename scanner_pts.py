import os
import re
import requests
import yfinance as yf
from google import genai

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# 1. Scraper les Tickers PTS avec logs de débogage
def get_pts_tickers():
    print("Étape 1: Récupération des Top Gainers PTS...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    url_jina = "https://r.jina.ai/https://kabutan.jp/pts/"
    
    try:
        response = requests.get(url_jina, headers=headers, timeout=20)
        print(f"Statut HTTP : {response.status_code}")
        
        if response.status_code != 200:
            print("❌ Erreur d'accès à la page PTS.")
            return []

        raw_text = response.text
        print(f"🔍 Débogage : {len(raw_text)} caractères récupérés.")
        print("--- Début de la page reçue par Jina ---")
        print(raw_text[:400])  # Affiche les 400 premiers caractères dans la console GitHub
        print("---------------------------------------")

        # Recherche des codes à 4 chiffres (ex: 7203, 9984) dans les tableaux/liens Markdown
        found_codes = re.findall(r'code=(\d{4})', raw_text)
        if not found_codes:
            # Capture les codes situés dans des cellules de tableau Markdown | 1234 | ou liens [1234]
            found_codes = re.findall(r'\[(\d{4})\]|\|\s*(\d{4})\s*\|', raw_text)
            # Aplatir le tuple renvoyé par le regex multi-groupes
            found_codes = [code for group in found_codes for code in group if code]

        tickers = []
        excluded_numbers = {'2024', '2025', '2026', '2027'}
        for code in found_codes:
            if code not in excluded_numbers and code not in tickers:
                tickers.append(code)

        print(f"✅ {len(tickers)} tickers bruts extraits de Kabutan.")
        return tickers[:30]

    except Exception as e:
        print(f"❌ Erreur lors du scraping : {e}")
        return []

# 2. Filtrer selon tes critères stricts
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
            
            # Filtres stricts : Prix 150-2300 JPY, Market Cap <= 100B JPY, Vol 10j >= 100k
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
            
    print(f"📊 {len(valid_stocks)} / {len(tickers)} actions passent tes critères.")
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
                model='gemini-2.5-flash',
                contents=prompt
            )
            print(f"\n🚀 ACTION SELECTIONNÉE : {code} ({stock['price']} ¥)")
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
            print("ℹ️ Résultat vide légitime : des tickers ont été trouvés sur le PTS, mais aucun ne correspond à tes filtres (prix/capitalisation/volume).")
    else:
        print("⚠️ Problème à l'étape 1 : Aucun ticker n'a été extrait du HTML de Kabutan.")
