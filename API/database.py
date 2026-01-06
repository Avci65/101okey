import psycopg2
import json
import os
from dotenv import load_dotenv
import random 

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

    # oyuncular = [{id, name, hand}]
    players_data = {str(p["id"]): p["hand"] for p in oyuncular}
    player_ids = [p["id"] for p in oyuncular]

    cur.execute("""
        INSERT INTO games (
            chat_id,
            players,
            current_turn_id,
            deck,
            gosterge,
            okey,
            discard,
            is_active
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (chat_id) DO UPDATE SET
            players = EXCLUDED.players,
            current_turn_id = EXCLUDED.current_turn_id,
            deck = EXCLUDED.deck,
            gosterge = EXCLUDED.gosterge,
            okey = EXCLUDED.okey,
            discard = EXCLUDED.discard,
            is_active = EXCLUDED.is_active;
    """, (
        chat_id,
        json.dumps(players_data),
        player_ids[0],                 # ilk oyuncu başlar
        json.dumps(deste),
        json.dumps(gosterge),
        json.dumps(okey),
        None,                           # discard başlangıçta boş
        True
    ))

    conn.commit()
    cur.close()
    conn.close()
def deste_olustur(okey):
    deste = []

    for renk in ["kirmizi", "mavi", "sari", "siyah"]:
        for sayi in range(1, 14):
            deste.append({"renk": renk, "sayi": sayi})
            deste.append({"renk": renk, "sayi": sayi})

    # 2 adet sahte okey
    deste.append({
        "renk": okey["renk"],
        "sayi": okey["sayi"],
        "sahte": True
    })
    deste.append({
        "renk": okey["renk"],
        "sayi": okey["sayi"],
        "sahte": True
    })

    random.shuffle(deste)
    return deste



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
    if not gosterge:
        return None

    sayi = gosterge['sayi'] + 1 if gosterge['sayi'] < 13 else 1
    return {
        "renk": gosterge["renk"],
        "sayi": sayi,
        "type": "real_okey"
    }

def el_analiz_et(el, okey):
    toplam = 0
    grup = []

    def grup_puani(grup):
        if not per_gecerli_mi(grup, okey):
            return 0

        normal = [t for t in grup if t != okey]
        okeyler = [t for t in grup if t == okey]

        if len(normal) < 2:
            return 0

        # seri per
        if all(t["renk"] == normal[0]["renk"] for t in normal):
            sayilar = sorted(t["sayi"] for t in normal)
            puan = sum(sayilar)

            for i in range(len(sayilar)-1):
                if sayilar[i+1] - sayilar[i] == 2 and okeyler:
                    puan += sayilar[i] + 1

            return puan

        # grup per
        sayi = normal[0]["sayi"]
        return sayi * (len(normal) + len(okeyler))

    for tas in el:
        if tas:
            grup.append(tas)
        else:
            toplam += grup_puani(grup)
            grup = []

    toplam += grup_puani(grup)
    return toplam



def oyun_verisi_getir(chat_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT players, gosterge, okey, discard
        FROM games
        WHERE chat_id = %s
    """, (chat_id,))

    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return None

    players, gosterge, okey, discard = row

    return {
        "players": players,
        "gosterge": gosterge,
        "okey": okey,
        "discard": discard
    }


def tas_at_db(chat_id, user_id, index):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT players FROM games WHERE chat_id = %s", (chat_id,))
    players = cur.fetchone()[0]

    tas = players[str(user_id)][index]
    players[str(user_id)][index] = None

    cur.execute("""
        UPDATE games
        SET players = %s, discard = %s
        WHERE chat_id = %s
    """, (
        json.dumps(players),
        json.dumps(tas),
        chat_id
    ))

    conn.commit()
    cur.close()
    conn.close()

    return tas
def per_gecerli_mi(grup, okey):
    if len(grup) < 3:
        return False

    okeyler = [t for t in grup if t["renk"] == okey["renk"] and t["sayi"] == okey["sayi"]]
    normal = [t for t in grup if t not in okeyler]

    if len(normal) < 2:
        return False

    # SERİ PER
    renk = normal[0]["renk"]
    if all(t["renk"] == renk for t in normal):
        sayilar = sorted(t["sayi"] for t in normal)
        gereken = 0
        for i in range(1, len(sayilar)):
            fark = sayilar[i] - sayilar[i-1]
            if fark == 1:
                continue
            elif fark == 2:
                gereken += 1
            else:
                return False
        return gereken <= len(okeyler)

    # GRUP PER
    sayi = normal[0]["sayi"]
    if not all(t["sayi"] == sayi for t in normal):
        return False

    renkler = {t["renk"] for t in normal}
    return len(renkler) == len(normal)

def ortaya_atilan_tasi_getir(chat_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT discard
        FROM games
        WHERE chat_id = %s
    """, (chat_id,))

    res = cur.fetchone()
    cur.close()
    conn.close()

    return res[0] if res else None

