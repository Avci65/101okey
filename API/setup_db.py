import psycopg2

# Railway Variables kısmından kopyaladığın PUBLIC_URL'i buraya yapıştır
# Örnek format: "postgresql://postgres:sifre@host:port/railway"
DATABASE_URL = "postgresql://postgres:NCUuguqXeGJoCTmpgfFgXBqyvwrJQkUC@shinkansen.proxy.rlwy.net:34772/railway"

def database_kur():
    try:
        # Bağlantı kuruluyor
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        sql_komutlari = """
        CREATE TABLE IF NOT EXISTS games (
            chat_id BIGINT PRIMARY KEY,
            players JSONB,
            current_turn_id BIGINT,
            deck JSONB,
            gosterge JSONB,
            is_active BOOLEAN DEFAULT TRUE
        );

        CREATE TABLE IF NOT EXISTS scores (
            chat_id BIGINT,
            player_id BIGINT,
            player_name TEXT,
            total_score INT DEFAULT 0,
            PRIMARY KEY (chat_id, player_id)
        );
        """
        
        print("Bağlantı doğrulandı. Tablolar kuruluyor...")
        cur.execute(sql_komutlari)
        conn.commit()
        
        print("✅ BAŞARILI: Railway üzerinde tablolar hazır!")
        
        cur.close()
        conn.close()
    except Exception as e:
        # Şifre hatası devam ederse burası detaylı hata verir
        print(f"❌ BAĞLANTI HATASI: {e}")

if __name__ == "__main__":
    database_kur()