import os
import re
import json
import requests
import yfinance as yf
from google import genai

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
}

# 1. Scraper les Tickers PTS directement (Sans proxy externe)
def get_pts_tickers():
    print("Étape 1: Récupération des Top Gainers PTS...")
    tickers = []
    
    # Minkabu PTS Direct
    try:
        url_minkabu = "https://minkabu.jp/ranking/pts/gainers"
        res = requests.get(url_minkabu, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            found = re.findall(r'/stock/(\d{4})', res.text)
            for code in found:
                if code not in {'2024', '2025', '2026', '2027'} and code not in tickers:
                    tickers.append(code)
            if tickers:
                print("✅ Données récupérées directement depuis Minkabu PTS.")
    except Exception as e:
        print(f"⚠️ Échec Minkabu direct : {e}")

    # Fallback Yahoo Finance JP PTS Direct
    if not tickers:
        try:
            url_yahoo = "https://finance.yahoo.co.jp/data/ranking/pts-price-increase"
            res = requests.get(url_yahoo, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                found = re.findall(r'quote/(\d{4})', res.text) or re.findall(r'\b([1-9]\d{3})\b', res.text)
                for code in found:
                    if code not in {'2024', '2025', '2026', '2027'} and code not in tickers:
                        tickers.append(code)
                if tickers:
                    print("✅ Données récupérées depuis Yahoo Finance JP PTS.")
        except Exception as e:
            print(f"⚠️ Échec Yahoo JP direct : {e}")

    print(f"✅ {len(tickers)} tickers bruts extraits du PTS.")
    return tickers[:30]

# 2. Filtrer selon tes critères stricts (Prix, Mkt Cap, Volume)
def filter_tickers(tickers):
    print("\nÉtape 2: Application des filtres (Prix, Mkt Cap, Volume)...")
    valid_stocks = []
    
    for code in tickers:
        try:
            ticker_yf = yf.Ticker(f"{code}.T")
            fast_info = ticker_yf.fast_info
            
            price = fast_info.last_price or 0
            mkt_cap = fast_info.market_cap or 0
            
            try:
                avg_vol = ticker_yf.info.get('averageVolume10days', 0)
            except Exception:
                avg_vol = 100_000  # Sécurité pour ne pas bloquer si info échoue
            
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

# Extraction directe des actualités en HTML nettoyé
def fetch_jp_news(code):
    try:
        url = f"https://minkabu.jp/stock/{code}/news"
        res = requests.get(url, headers=HEADERS, timeout=8)
        if res.status_code == 200:
            text = re.sub(r'<script.*?>.*?</script>', '', res.text, flags=re.DOTALL)
            text = re.sub(r'<style.*?>.*?</style>', '', text, flags=re.DOTALL)
            clean_lines = [re.sub(r'<.*?>', '', line).strip() for line in text.split('\n')]
            clean_text = " | ".join([line for line in clean_lines if len(line) > 20])
            return clean_text[:1200] if clean_text else "Pas d'actualité récente disponible."
    except Exception:
        pass
    return "Pas d'actualité disponible."

# 3. Analyse BATCH globale Gemini (1 seul appel rapide)
def analyze_all_catalysts(valid_stocks):
    print("\nÉtape 3: Analyse IA Globale des catalyseurs (1 seul appel Gemini)...")
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
    Voici la liste des actions ayant un fort volume/hausse en PTS avec leurs actualités/communiqués :

    {json.dumps(payload, ensure_ascii=False, indent=2)}

    Pour CHAQUE action :
    1. Détecte si la news contient une vraie annonce d'entreprise (Résultats, Révision à la hausse, Rachat d'actions, Partenariat, M&A).
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

    try:
        response = client.models.generate_content(
            model='gemini-3.8-flash',
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
        else:
            print("⚠️ Réponse IA non formatée en JSON.")

    except Exception as e:
        print(f"❌ Erreur API Gemini : {e}")

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
