import os
import re
import json
import time
import logging
import requests
import yfinance as yf
from google import genai

# Masquer les warnings / logs d'erreur parasites de yfinance
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

# 1. Scraper les Tickers PTS avec Multi-sources
def get_pts_tickers():
    print("Étape 1: Récupération des Top Gainers PTS...")
    
    sources = [
        ("Minkabu Jina", "https://r.jina.ai/https://minkabu.jp/ranking/pts/gainers"),
        ("Kabutan Jina", "https://r.jina.ai/https://kabutan.jp/pts/"),
        ("Yahoo JP Jina", "https://r.jina.ai/https://finance.yahoo.co.jp/data/ranking/pts-price-increase")
    ]
    
    tickers = []

    for name, url in sources:
        try:
            res = requests.get(url, headers=HEADERS, timeout=25)
            if res.status_code == 200:
                found = re.findall(r'\b([1-9]\d{3})\b', res.text)
                for code in found:
                    if code not in {'2024', '2025', '2026', '2027', '2028', '1000', '2000'} and code not in tickers:
                        tickers.append(code)
                
                if len(tickers) >= 5:
                    print(f"✅ Données récupérées avec succès via {name}.")
                    break
        except Exception as e:
            print(f"⚠️️ {name} indisponible : {e}")

    if not tickers:
        try:
            res = requests.get("https://kabutan.jp/pts/", headers=HEADERS, timeout=10)
            found = re.findall(r'code=(\d{4})', res.text) or re.findall(r'/stock/(\d{4})', res.text)
            for code in found:
                if code not in tickers:
                    tickers.append(code)
            if tickers:
                print("✅ Données récupérées via Kabutan direct.")
        except Exception as e:
            print(f"⚠️ Échec secours Kabutan : {e}")

    print(f"✅ {len(tickers)} tickers bruts extraits du PTS.")
    return tickers[:30]

# 2. Filtrer selon les critères (Prix, Mkt Cap, Volume)
def filter_tickers(tickers):
    print("\nÉtape 2: Application des filtres (Prix, Mkt Cap, Volume)...")
    valid_stocks = []
    
    for code in tickers:
        try:
            ticker_yf = yf.Ticker(f"{code}.T")
            info = ticker_yf.info
            
            price = info.get('regularMarketPrice') or info.get('currentPrice') or getattr(ticker_yf.fast_info, 'last_price', 0)
            mkt_cap = info.get('marketCap') or getattr(ticker_yf.fast_info, 'market_cap', 0)
            avg_vol = info.get('averageVolume10days', 0) or info.get('volume', 0)
            
            if not price or not mkt_cap:
                continue

            # Filtres : Prix 150-2300 JPY | Mkt Cap <= 100B JPY | Vol 10j >= 100k
            if (150 <= price <= 2300) and (mkt_cap <= 100_000_000_000) and (avg_vol >= 100_000):
                valid_stocks.append({
                    'code': code,
                    'price': round(price, 1),
                    'mkt_cap': mkt_cap,
                    'avg_vol': avg_vol
                })
        except Exception:
            continue
            
    print(f"📊 {len(valid_stocks)} / {len(tickers)} actions correspondent à tes critères.")
    return valid_stocks

# Récupérer les actualités en japonais
def fetch_jp_news(code):
    try:
        url = f"https://r.jina.ai/https://minkabu.jp/stock/{code}/news"
        res = requests.get(url, headers=HEADERS, timeout=8)
        if res.status_code == 200:
            lines = [line.strip() for line in res.text.split('\n') if len(line.strip()) > 15]
            clean_text = " | ".join(lines[3:20])
            return clean_text[:1200] if clean_text else "Pas d'actualité récente disponible."
    except Exception:
        pass
    return "Pas d'actualité récente."

# 3. Analyse BATCH globale Gemini (avec Retry automatique en cas de 503)
def analyze_all_catalysts(valid_stocks):
    print("\nÉtape 3: Collecte des news JP et Analyse IA Globale...")
    if not client:
        print("Erreur: Clé API Gemini non disponible.")
        return

    payload = []
    for stock in valid_stocks:
        code = stock['code']
        news_jp = fetch_jp_news(code)
        payload.append({
            "code": code,
            "price": stock['price'],
            "mkt_cap_B_JPY": round(stock['mkt_cap'] / 1_000_000_000, 2),
            "avg_vol_10d": stock['avg_vol'],
            "news_text": news_jp
        })

    prompt = f"""
    Tu es un analyste financier expert du marché japonais (Tokyo Stock Exchange / PTS).
    Voici la liste des actions PTS avec leurs actualités récentes :

    {json.dumps(payload, ensure_ascii=False, indent=2)}

    Pour CHAQUE action :
    1. Détecte si la news contient une vraie annonce d'entreprise (Résultats, Révision à la hausse, Rachat d'actions, Partenariat, M&A, TDNet).
    2. Sinon, indique "Spéculation PTS / Flux technique".
    3. Assigne un score d'impact de 1 à 10 pour un trade intraday.
    4. Rédige un résumé synthétique d'une phrase en français.

    Réponds STRICTEMENT sous ce format JSON valide :
    {{
      "CODE_TICKER": {{
        "catalyseur": "Type de catalyseur exact ou Spéculation PTS",
        "score": 8,
        "resume": "Résumé d'une phrase en français."
      }}
    }}
    """

    # Boucle de retry (3 tentatives) pour contourner les erreurs 503
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            raw_res = response.text.strip()
            json_match = re.search(r'\{.*\}', raw_res, re.DOTALL)
            
            if json_match:
                results = json.loads(json_match.group(0))
                print("\n" + "="*50)
                print("⚡ RÉSULTATS DU SCANNER PTS")
                print("="*50)
                
                for stock in valid_stocks:
                    code = stock['code']
                    res = results.get(code, {})
                    cat = res.get('catalyseur', 'Spéculation PTS')
                    score = res.get('score', 1)
                    resume = res.get('resume', 'Aucune annonce majeure identifiée.')
                    
                    print(f"\n🚀 ACTION SÉLECTIONNÉE : {code} ({stock['price']} ¥)")
                    print(f"Mkt Cap: {stock['mkt_cap']/1_000_000_000:.2f} B¥ | Vol 10j: {stock['avg_vol']}")
                    print(f"Catalyseur: {cat} | Score: {score}/10 | Résumé: {resume}")
                break
            else:
                print("⚠️ Réponse IA non formatée en JSON.")
                break

        except Exception as e:
            print(f"⚠️ Erreur API Gemini (tentative {attempt}/{max_retries}) : {e}")
            if attempt < max_retries:
                sleep_time = attempt * 3
                print(f"⏳ Attente de {sleep_time}s avant réessai...")
                time.sleep(sleep_time)
            else:
                print("❌ Impossible de contacter Gemini après plusieurs essais.")

if __name__ == "__main__":
    if not GEMINI_API_KEY:
        print("Erreur: Clé API Gemini manquante.")
        exit(1)
        
    tickers = get_pts_tickers()
    if tickers:
        filtered = filter_tickers(tickers)
        if filtered:
            analyze_all_catalysts(filtered)
        else:
            print("ℹ️ Aucun ticker ne respecte tes filtres de prix / capitalisation / volume aujourd'hui.")
    else:
        print("⚠️ Problème à l'étape 1 : Impossible de récupérer le classement PTS.")
