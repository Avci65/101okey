import os
import random
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from database import save_game, load_game, el_analiz_et

# Ayarlar
TOKEN = os.getenv("BOT_TOKEN")

def okey_olustur():
    renkler = ['Kırmızı', 'Mavi', 'Siyah', 'Sarı']
    setler = [{'renk': r, 'sayi': s} for r in renkler for s in range(1, 14)] * 2
    setler.append({'renk': 'Joker', 'sayi': 0})
    setler.append({'renk': 'Joker', 'sayi': 0})
    random.shuffle(setler)
    return setler

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🀄 101 Okey Botuna Hoşgeldiniz!\n/katil yazarak masaya oturun.")

async def katil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    game = load_game(chat_id) or {'players': {}, 'current_turn_id': None, 'deck': [], 'gosterge': None, 'is_active': False}
    
    if str(user.id) not in game['players']:
        game['players'][str(user.id)] = []
        save_game(chat_id, game)
        await update.message.reply_text(f"✅ {user.first_name} masaya oturdu. (Oyuncu: {len(game['players'])})")
    
    if len(game['players']) == 1 and not game['is_active']:
        await update.message.reply_text("Oyunun başlaması için /baslat yazın.")

async def baslat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = load_game(chat_id)
    if not game or len(game['players']) < 1: return

    deck = okey_olustur()
    game['gosterge'] = deck.pop()
    
    for uid in game['players']:
        game['players'][uid] = [deck.pop() for _ in range(21)]
    
    game['current_turn_id'] = int(list(game['players'].keys())[0])
    game['deck'] = deck
    game['is_active'] = True
    
    save_game(chat_id, game)
    await update.message.reply_text("🀄 Oyun başladı! Oyunculara elleri özelden gönderildi.")

async def el_goster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    game = load_game(chat_id)
    
    if not game or str(user_id) not in game['players']: return
    
    markup, text = arayuz_olustur(game, user_id)
    await update.message.reply_text(text, reply_markup=markup)

def arayuz_olustur(game, user_id):
    el = game['players'][str(user_id)]
    per_puan = el_analiz_et(el, game['gosterge'])
    ceza = sum(t['sayi'] for t in el if t)
    
    keyboard = []
    # Taş butonları (Örnek: 5'erli satırlar)
    row = []
    for i, tas in enumerate(el):
        label = f"{tas['renk'][0]}{tas['sayi']}" if tas else "▫️"
        row.append(InlineKeyboardButton(label, callback_data=f"sec_{i}"))
        if len(row) == 5:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    
    # Kontrol Butonları
    keyboard.append([
        InlineKeyboardButton("🃏 Taş Çek", callback_data="cek"),
        InlineKeyboardButton("📤 Taş At", callback_data="at")
    ])
    keyboard.append([InlineKeyboardButton("▫️ Boşluk Ekle", callback_data="bosluk")])
    
    status = "🔴 SIRA SENDE DEĞİL"
    if game['current_turn_id'] == user_id:
        status = "🟢 SIRA SENDE!"

    text = f"{status}\n💠 Per: {per_puan} | ⚠️ Ceza: {ceza}\n🃏 Gösterge: {game['gosterge']['renk']} {game['gosterge']['sayi']}"
    return InlineKeyboardMarkup(keyboard), text

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    game = load_game(chat_id)
    
    if query.data == "cek":
        # 1. Sıra Kontrolü
        if game['current_turn_id'] != user_id:
            await query.answer("Sıra sende değil!", show_alert=True)
            return
        
        # 2. Taş Sınırı Kontrolü
        el = game['players'][str(user_id)]
        mevcut_tas = len([t for t in el if t is not None])
        if mevcut_tas >= 22:
            await query.answer("Elin dolu (22 taş)! Önce taş atmalısın.", show_alert=True)
            return
            
        yeni_tas = game['deck'].pop()
        game['players'][str(user_id)].append(yeni_tas)
        save_game(chat_id, game)
        
    elif query.data == "at":
        if game['current_turn_id'] != user_id:
            await query.answer("Sıra sende değil!", show_alert=True)
            return
            
        # Basitçe son taşı atma ve sırayı geçirme mantığı
        game['players'][str(user_id)].pop() # Örnek: Son taşı atar
        p_ids = list(game['players'].keys())
        idx = (p_ids.index(str(user_id)) + 1) % len(p_ids)
        game['current_turn_id'] = int(p_ids[idx])
        save_game(chat_id, game)
        await query.message.edit_text("Taş attın, sıra geçti!")
        return

    # Arayüzü tazele
    markup, text = arayuz_olustur(game, user_id)
    await query.edit_message_text(text, reply_markup=markup)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("katil", katil))
    app.add_handler(CommandHandler("baslat", baslat))
    app.add_handler(CommandHandler("el", el_goster))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()