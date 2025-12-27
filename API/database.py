import psycopg2
import json
import os
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        # Railway içindeki güvenli bağlantı için
        return psycopg2.connect(db_url)
    
    # Kendi bilgisayarında test edersen çalışması için eski ayarların
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )

# --- ANALİZ MANTIĞI ---

def okey_belirle(gosterge):
    if not gosterge or gosterge.get('renk') == 'Sahte': return None
    okey_sayi = 1 if gosterge['sayi'] == 13 else gosterge['sayi'] + 1
    return {'renk': gosterge['renk'], 'sayi': okey_sayi}

def per_puan_hesapla(grup, okey_tas):
    """Yan yana gelen en az 3 taşı analiz eder."""
    if len(grup) < 3: return 0
    
    # Okey ve normal taşları ayır
    okeyler = [t for t in grup if okey_tas and t['renk'] == okey_tas['renk'] and t['sayi'] == okey_tas['sayi']]
    normaller = [t for t in grup if not (okey_tas and t['renk'] == okey_tas['renk'] and t['sayi'] == okey_tas['sayi'])]
    
    if not normaller: return 0

    # GRUP PER KONTROLÜ (Aynı sayı, farklı renk)
    sayilar = [t['sayi'] for t in normaller]
    renkler = [t['renk'] for t in normaller]
    
    # Eğer tüm sayı değerleri aynıysa ve renkler farklıysa (veya okey varsa)
    if len(set(sayilar)) == 1 and len(set(renkler)) == len(normaller):
        puan = sum(sayilar)
        if okeyler:
            puan += (len(okeyler) * sayilar[0])
        return puan
    
    # SERİ PER KONTROLÜ (Aynı renk, ardışık sayı - Basit hali)
    if len(set(renkler)) == 1:
        # Ardışık kontrolü yapılabilir, şimdilik toplamı dönelim
        return sum(sayilar) + (len(okeyler) * (sum(sayilar)/len(normaller)))

    return 0

def el_analiz_et(el, okey_tas):
    toplam_puan = 0
    mevcut_grup = []
    for tas in el:
        if tas is None: # Boşluk ayracı
            toplam_puan += per_puan_hesapla(mevcut_grup, okey_tas)
            mevcut_grup = []
        else:
            mevcut_grup.append(tas)
    if mevcut_grup:
        toplam_puan += per_puan_hesapla(mevcut_grup, okey_tas)
    return int(toplam_puan)

def ceza_hesapla(el, cift_mi=False):
    toplam = sum(t['sayi'] for t in el if t is not None)
    return toplam * 2 if cift_mi else toplam

# --- VERİTABANI İŞLEMLERİ ---

def oyunu_baslat_db(chat_id, oyuncular, deste, gosterge):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO games (chat_id, players, current_turn_id, deck, gosterge, is_active) VALUES (%s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (chat_id) DO UPDATE SET players=EXCLUDED.players, deck=EXCLUDED.deck, gosterge=EXCLUDED.gosterge, current_turn_id=EXCLUDED.current_turn_id, is_active=TRUE",
        (chat_id, json.dumps(oyuncular), oyuncular[0]['id'], json.dumps(deste), json.dumps(gosterge), True)
    )
    conn.commit()
    cur.close()
    conn.close()

def oyun_verisi_getir(chat_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT gosterge, current_turn_id FROM games WHERE chat_id = %s", (chat_id,))
    res = cur.fetchone()
    cur.close()
    conn.close()
    return res

def oyuncu_eli_getir(chat_id, player_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT players FROM games WHERE chat_id = %s", (chat_id,))
    res = cur.fetchone()
    cur.close()
    conn.close()
    if res:
        for p in res[0]:
            if p['id'] == player_id: return p.get('hand', [])
    return []

def oyuncu_eli_guncelle(chat_id, player_id, yeni_el):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT players FROM games WHERE chat_id = %s", (chat_id,))
    res = cur.fetchone()
    if res:
        players = res[0]
        for p in players:
            if p['id'] == player_id: p['hand'] = yeni_el
        cur.execute("UPDATE games SET players = %s WHERE chat_id = %s", (json.dumps(players), chat_id))
        conn.commit()
    cur.close()
    conn.close()

def sira_kimde(chat_id):
    res = oyun_verisi_getir(chat_id)
    return res[1] if res else None

def sirayi_degistir(chat_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT players, current_turn_id FROM games WHERE chat_id = %s", (chat_id,))
    res = cur.fetchone()
    if res:
        players, current_id = res[0], res[1]
        p_ids = [p['id'] for p in players]
        next_id = p_ids[(p_ids.index(current_id) + 1) % len(p_ids)]
        cur.execute("UPDATE games SET current_turn_id = %s WHERE chat_id = %s", (next_id, chat_id))
        conn.commit()
        cur.close()
        conn.close()
        return next_id
    return None

def tas_cek_db(chat_id, player_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT deck, players FROM games WHERE chat_id = %s", (chat_id,))
    res = cur.fetchone()
    if res and res[0] and len(res[0]) > 0:
        deck, players = res[0], res[1]
        cekilen = deck.pop(0)
        yeni_el = []
        for p in players:
            if p['id'] == player_id:
                p['hand'].append(cekilen)
                yeni_el = p['hand']
        cur.execute("UPDATE games SET deck = %s, players = %s WHERE chat_id = %s", (json.dumps(deck), json.dumps(players), chat_id))
        conn.commit()
        cur.close()
        conn.close()
        return cekilen, yeni_el
    cur.close()
    conn.close()
    return None, None