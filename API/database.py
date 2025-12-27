import psycopg2
import json
import os
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    # Railway DATABASE_URL önceliklidir
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url)
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )

def save_game(chat_id, game_data):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO games (chat_id, players, current_turn_id, deck, gosterge, is_active)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (chat_id) DO UPDATE SET
        players = EXCLUDED.players,
        current_turn_id = EXCLUDED.current_turn_id,
        deck = EXCLUDED.deck,
        gosterge = EXCLUDED.gosterge,
        is_active = EXCLUDED.is_active;
    """, (chat_id, json.dumps(game_data['players']), game_data['current_turn_id'], 
          json.dumps(game_data['deck']), json.dumps(game_data['gosterge']), game_data['is_active']))
    conn.commit()
    cur.close()
    conn.close()

def load_game(chat_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT players, current_turn_id, deck, gosterge, is_active FROM games WHERE chat_id = %s", (chat_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return {
            'players': row[0],
            'current_turn_id': row[1],
            'deck': row[2],
            'gosterge': row[3],
            'is_active': row[4]
        }
    return None

def el_analiz_et(el, okey_tasi):
    """Taşlar arasında boşluk (None) varsa sadece grupları toplar"""
    toplam_per = 0
    gecerli_grup = []
    
    for tas in el:
        if tas is None: # Boşluk gördüğünde mevcut grubu hesapla
            toplam_per += grup_puan_hesapla(gecerli_grup, okey_tasi)
            gecerli_grup = []
        else:
            gecerli_grup.append(tas)
    
    # Son grubu ekle
    toplam_per += grup_puan_hesapla(gecerli_grup, okey_tasi)
    return toplam_per

def grup_puan_hesapla(grup, okey):
    if len(grup) < 3: return 0
    # Basitçe sayıları toplar (Gelişmiş 101 kuralları buraya eklenebilir)
    return sum(t['sayi'] for t in grup)