import os
import re
import json
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
        res = requests.get(url_minkabu, headers=HEADERS, timeout=15)
        if res.status_code == 200:
            print("✅ Données récupérées depuis Minkabu PTS.")
            found = re.findall(r'/stock/(\d{4})', res.text) or re.findall(r'\b([1-9]\d{3})\b', res.text)
            for code in found:
                if code not in {'2024', '2025', '2026', '2027'} and code not in tickers:
                    tickers.append(code)
    except Exception as e:
        print(f"❌ Échec Minkabu : {e}")

    print(f"✅ {len(tickers)} tickers bruts extraits du PTS.")
    return tickers[:30]

# 2. Filtrer selon tes critères stricts (Prix, Mkt Cap, Volume)
def filter_tickers(tickers):
    print("\nÉtape 2: Application des filtres (Prix, Mkt Cap, Volume)...")
    valid_stocks = []
    
    for code in tickers:
        try:
            ticker_yf = yf.Ticker(f"{code}.T")
            info = ticker_yf.info
            
            price = info.get('regularMarketPrice') or info.get('currentPrice', 0)
            mkt_cap = info.get('marketCap', 0)
            avg_vol = info.get('averageVolume10days', 0)
            
            # Filtres : Prix 150-2300 JPY | Mkt Cap <= 100B JPY | Vol 10j >= 100k
            if (150 <= price <= 2300) and (mkt_cap <= 100_000_000_000) and (avg_vol >= 100_000):
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

# Récupérer les actualités en japonais depuis Minkabu News
def fetch_jp_news(code):
    try:
        url = f"https://r.jina.ai/https://minkabu.jp/stock/{code}/news"
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            lines = [line.strip() for line in res.text.split('\n') if len(line.strip()) > 15]
            # Extraire le cœur de la page news
            clean_text = " | ".join(lines[3:25])
            return clean_text[:1500] if clean_text else "Pas d'actualité texte disponible."
    except Exception:
        pass
    return "Pas d'actualité récente disponible."

# 3. Analyse BATCH globale avec Gemini (1 seul appel API)
def analyze_all_catalysts(valid_stocks):
    print("\nÉtape 3: Collecte des news JP et Analyse IA Globale (1 seul appel Gemini)...")
    if not client:
        print("Erreur: Clé API Gemini non disponible.")
        return

    # Préparation du tableau de données à envoyer à Gemini
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
    Voici la liste des actions ayant fort volume/hausse en PTS avec leurs actualités/communiqués récents :

    {json.dumps(payload, ensure_ascii=False, indent=2)}

    TÂCHE :
    Pour CHAQUE action présente dans la liste ci-dessus :
    1. Analyse le texte 'news_text' pour détecter une vraie annonce d'entreprise (Résultats financiers, Révision à la hausse, Rachat d'actions, Partenariat, M&A, TDNet release).
    2. Si le texte ne contient aucune annonce fondamentale claire, évalue si le mouvement est d'ordre spéculatif/technique.
    3. Assigne un score d'impact court terme de 1 à 10 pour un trade intraday.
    4. Rédige un résumé synthétique d'une phrase en français.

    FORMAT DE RÉPONSE OBLIGATOIRE :
    Tu dois répondre STRICTEMENT sous la forme d'un objet JSON valide sans aucun texte additionnel avant ou après.
    Format JSON attendu :
    {{
      "CODE_TICKER": {{
        "catalyseur": "Type de catalyseur exact ou Spéculation PTS",
        "score": 8,
        "resume": "Résumé d'une phrase en français."
      }}
    }}
    """

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=prompt
            )
            
            # Extraction propre du JSON de la réponse Gemini
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
                    cat = res.get('catalyseur', 'Non évalué')
                    score = res.get('score', 1)
                    resume = res.get('resume', 'Aucune analyse disponible.')
                    
                    print(f"\n🚀 ACTION SÉLECTIONNÉE : {code} ({stock['price']} ¥)")
                    print(f"Mkt Cap: {stock['mkt_cap']/1_000_000_000:.2f} B¥ | Vol 10j: {stock['avg_vol']}")
                    print(f"Catalyseur: {cat} | Score: {score}/10 | Résumé: {resume}")
                break
            else:
                print("⚠️ Erreur de formatage JSON dans la réponse Gemini.")
                break

        except Exception as e:
            if "429" in str(e) or "503" in str(e) or "quota" in str(e).lower():
                print(f"⚠️ Surcharge API Gemini, réessai dans 10s... (Essai {attempt+1}/3)")
                time.sleep(10)
            else:
                print(f"❌ Erreur API Gemini : {e}")
                break

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
