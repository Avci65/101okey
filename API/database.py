import psycopg2
import json
import os
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    # Railway'de DATABASE_URL kullanılır, PC'de senin verdiğin ayarlar
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url)
    return psycopg2.connect(
        dbname="okey_bot",
        user="postgres",
        password="1856",
        host="localhost",
        port="5432"
    )

def oyunu_baslat_db(chat_id, oyuncular, deste, gosterge, okey):
    conn = get_connection()
    cur = conn.cursor()
    players_data = {str(p['id']): p['hand'] for p in oyuncular}
    player_ids = [p['id'] for p in oyuncular]
    
    cur.execute("""
        INSERT INTO games (chat_id, players, current_turn_id, deck, gosterge, is_active)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (chat_id) DO UPDATE SET
        players = EXCLUDED.players, current_turn_id = EXCLUDED.current_turn_id,
        deck = EXCLUDED.deck, gosterge = EXCLUDED.gosterge, is_active = EXCLUDED.is_active;
    """, (chat_id, json.dumps(players_data), player_ids[0], json.dumps(deste), json.dumps(gosterge), True))
    conn.commit()
    cur.close()
    conn.close()

def oyuncu_eli_getir(chat_id, user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT players FROM games WHERE chat_id = %s", (chat_id,))
    res = cur.fetchone()
    cur.close()
    conn.close()
    if res:
        players_data = res[0]
        # PC'deki liste/sözlük hatasını önleyen kontrol
        if isinstance(players_data, list): return []
        return players_data.get(str(user_id), [])
    return []

def oyuncu_eli_guncelle(chat_id, user_id, yeni_el):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT players FROM games WHERE chat_id = %s", (chat_id,))
    players = cur.fetchone()[0]
    players[str(user_id)] = yeni_el
    cur.execute("UPDATE games SET players = %s WHERE chat_id = %s", (json.dumps(players), chat_id))
    conn.commit()
    cur.close()
    conn.close()

def tas_cek_db(chat_id, user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT deck, players FROM games WHERE chat_id = %s", (chat_id,))
    deck, players = cur.fetchone()
    if not deck: return None, None
    cekilen = deck.pop()
    players[str(user_id)].append(cekilen)
    cur.execute("UPDATE games SET deck = %s, players = %s WHERE chat_id = %s", 
                (json.dumps(deck), json.dumps(players), chat_id))
    conn.commit()
    cur.close()
    conn.close()
    return cekilen, players[str(user_id)]

def sira_kimde(chat_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT current_turn_id FROM games WHERE chat_id = %s", (chat_id,))
    res = cur.fetchone()
    cur.close()
    conn.close()
    return res[0] if res else None

def sirayi_degistir(chat_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT current_turn_id, players FROM games WHERE chat_id = %s", (chat_id,))
    current_id, players = cur.fetchone()
    p_ids = list(map(int, players.keys()))
    next_id = p_ids[(p_ids.index(current_id) + 1) % len(p_ids)]
    cur.execute("UPDATE games SET current_turn_id = %s WHERE chat_id = %s", (next_id, chat_id))
    conn.commit()
    cur.close()
    conn.close()

def okey_belirle(gosterge):
    if not gosterge: return None
    sayi = gosterge['sayi'] + 1 if gosterge['sayi'] < 13 else 1
    return {'renk': gosterge['renk'], 'sayi': sayi}

def el_analiz_et(el, okey):
    toplam = 0
    gecerli_grup = []
    for tas in el:
        if tas is None:
            if len(gecerli_grup) >= 3: toplam += sum(t['sayi'] for t in gecerli_grup)
            gecerli_grup = []
        else:
            gecerli_grup.append(tas)
    if len(gecerli_grup) >= 3: toplam += sum(t['sayi'] for t in gecerli_grup)
    return toplam

def oyun_verisi_getir(chat_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT players, deck, gosterge, okey, current_turn_id, is_active
        FROM games
        WHERE chat_id = %s
    """, (chat_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return None

    players, deck, gosterge, okey, current_turn_id, is_active = row

    return {
        "players": players,
        "deck": deck,
        "gosterge": gosterge,
        "okey": okey,
        "current_turn_id": current_turn_id,
        "is_active": is_active
    }
