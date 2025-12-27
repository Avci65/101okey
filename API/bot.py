import os
import random
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
from database import *

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

def deste_olustur():
    renkler = ['Kırmızı', 'Mavi', 'Siyah', 'Sarı']
    deste = [{'renk': r, 'sayi': s} for r in renkler for s in range(1, 14)] * 2
    deste.extend([{'renk': 'Sahte', 'sayi': 0}] * 2)
    random.shuffle(deste)
    return deste

def el_arayuzu(el, chat_id, kaynak_idx=None):
    db_verisi = oyun_verisi_getir(chat_id)
    if not db_verisi: return None, "Oyun bulunamadı."
    
    gosterge = db_verisi[0]
    okey = okey_belirle(gosterge)
    
    emojiler = {"Kırmızı": "🟥", "Mavi": "🟦", "Siyah": "⬛", "Sarı": "🟨", "Sahte": "🃏", "Boş": "▫️"}
    keyboard = []
    row = []
    
    for i, tas in enumerate(el):
        if tas is None:
            label = "✨" if i == kaynak_idx else emojiler["Boş"]
        else:
            is_okey = okey and tas['renk'] == okey['renk'] and tas['sayi'] == okey['sayi']
            prefix = "⭐" if is_okey else emojiler.get(tas['renk'], '⚪')
            if i == kaynak_idx: prefix = "🎯"
            label = f"{prefix}{tas['sayi'] if tas['sayi'] != 0 else ''}"
        
        row.append(InlineKeyboardButton(label, callback_data=f"sec_{i}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)

    keyboard.append([InlineKeyboardButton("▫️ Boşluk", callback_data="bosluk"), InlineKeyboardButton("❌ Temizle", callback_data="temizle")])
    keyboard.append([InlineKeyboardButton("🃏 Taş Çek", callback_data="cek"), InlineKeyboardButton("📤 Taş At", callback_data="at")])
    
    per_puan = el_analiz_et(el, okey)
    ceza = ceza_hesapla(el)
    txt = f"📍 Okey: {okey['renk']} {okey['sayi']}\n💠 **Per Toplamı:** {per_puan}\n⚠️ **Ceza Puanı:** {ceza}"
    if per_puan >= 101: txt += "\n✅ **ELİN AÇIYOR!**"
    
    return InlineKeyboardMarkup(keyboard), txt

async def katil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # Test için tek kişiyle oyunu başlatıyoruz
    deste = deste_olustur()
    gosterge = deste.pop()
    oyuncular = [{'id': user.id, 'name': user.first_name, 'hand': [deste.pop() for _ in range(21)]}]
    
    oyunu_baslat_db(chat_id, oyuncular, deste, gosterge)
    markup, txt = el_arayuzu(oyuncular[0]['hand'], chat_id)
    await update.message.reply_text(f"🚀 Oyun Başladı!\n{txt}", reply_markup=markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    cid = query.message.chat_id
    
    el = oyuncu_eli_getir(cid, uid)
    sira = sira_kimde(cid)

    # --- TAŞ SEÇME VE DÜZENLEME ---
    if query.data.startswith("sec_"):
        idx = int(query.data.split("_")[1])
        k_idx = context.user_data.get('k_idx')
        if k_idx is None:
            context.user_data['k_idx'] = idx
        else:
            el[k_idx], el[idx] = el[idx], el[k_idx]
            oyuncu_eli_guncelle(cid, uid, el)
            context.user_data['k_idx'] = None

    elif query.data == "bosluk":
        el.append(None)
        oyuncu_eli_guncelle(cid, uid, el)

    elif query.data == "temizle":
        el = [t for t in el if t is not None]
        oyuncu_eli_guncelle(cid, uid, el)

    # --- SIRA GEREKTİREN İŞLEMLER ---
    elif query.data == "cek":
        if sira != uid:
            await context.bot.send_message(cid, "⚠️ Sıra sende değil!")
            return
        if len(el) >= 22:
            await context.bot.send_message(cid, "⚠️ Zaten çektin veya 22 taşın var!")
            return
        cekilen, yeni_el = tas_cek_db(cid, uid)
        if cekilen:
            el = yeni_el

    elif query.data == "at":
        if sira != uid:
            await context.bot.send_message(cid, "⚠️ Sıra sende değil!")
            return
        k_idx = context.user_data.get('k_idx')
        if k_idx is None or k_idx >= len(el) or el[k_idx] is None:
            await context.bot.send_message(cid, "⚠️ Önce bir taş seç (🎯)!")
            return
        
        el.pop(k_idx)
        temiz_el = [t for t in el if t is not None]
        oyuncu_eli_guncelle(cid, uid, temiz_el)
        context.user_data['k_idx'] = None
        sirayi_degistir(cid)

    # Arayüzü Güncelle
    markup, txt = el_arayuzu(oyuncu_eli_getir(cid, uid), cid, context.user_data.get('k_idx'))
    await query.edit_message_text(text=txt, reply_markup=markup)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("katil", katil))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("Bot çalışıyor...")
    app.run_polling()