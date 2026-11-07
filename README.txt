YASHIL MENYULI KINO TELEGRAM BOTI

Arxiv tarkibi:
- bot.py — barcha bot logikasi bitta Python faylida
- requirements.txt — kerakli kutubxona
- README.txt — ushbu qo'llanma

Token va owner Telegram UID arxivga kiritilmagan.

KERAKLI TALABLAR
- Python 3.10 yoki undan yangi versiya
- Telegram bot tokeni (BotFather'dan olinadi)
- Owner uchun raqamli Telegram UID

O'RNATISH
  python -m pip install -r requirements.txt

LINUX / VPS
  export BOT_TOKEN='BOTFATHER_TOKENINGIZ'
  export OWNER_IDS='OWNER_TELEGRAM_UID'
  python bot.py

Bir nechta owner bo'lsa, ID'larni vergul bilan ajrating:
  export OWNER_IDS='111111111,222222222'

WINDOWS POWERSHELL
  $env:BOT_TOKEN='BOTFATHER_TOKENINGIZ'
  $env:OWNER_IDS='OWNER_TELEGRAM_UID'
  python bot.py

PYDROID 3
1. Pydroid terminalida yuqoridagi pip buyrug'i bilan aiogram o'rnating.
2. Terminal yoki Pydroid muhit sozlamalarida BOT_TOKEN va OWNER_IDS ni bering.
3. Muhit o'zgaruvchilarini berish imkoni bo'lmasa, bot.py ichidagi BOT_TOKEN va
   OWNER_IDS_RAW qiymatlariga o'zingizning token va ID'ingizni kiriting.
   Ular bu arxivda bo'sh qoldirilgan.
4. bot.py faylini ishga tushiring.

BOT FUNKSIYALARI
- Yashil success-uslubidagi inline menyular (Telegram ilovasi rangli button styles'ni
  qo'llamasa, tugmalar odatiy rangda ko'rinishi mumkin).
- Foydalanuvchi /start yuborganda username bilan shaxsiy salom.
- Owner panelidan start salomini tahrirlash. Shablon o'zgaruvchilari:
  {username}, {first_name}, {user_id}.
- Owner uchun barcha foydalanuvchilarga matn yuborish va yuborishdan oldin tasdiqlash.
- Owner adminlarni qo'shishi/o'chirishi, foydalanuvchilar ro'yxatini va statistikani ko'rishi,
  SQLite bazasining zaxira nusxasini olishi mumkin.
- Adminlar kino qo'shishi, o'chirishi, tahrirlashi va ro'yxatni ko'rishi mumkin.
- Kinolar va foydalanuvchilar SQLite bazasida saqlanadi; bot.log fayliga log yoziladi.

MAJBURIY KANAL (IXTIYORIY)
  export REQUIRED_CHANNEL='@kanal_yoki_-100...'
  export SUBSCRIPTION_URL='https://t.me/kanal'
Kanal obunasini tekshirish uchun botni kanalda admin qiling.

Ishga tushganda kino_bot.sqlite3 bazasi avtomatik yaratiladi. Botni to'xtatish uchun
terminalda Ctrl+C bosing. Tokenni hech qachon ommaviy joyga yubormang.
