# Telegram bot (aiogram 3.x)

## Lokal ishga tushirish

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

`.env` faylida `BOT_TOKEN` va `ADMIN_ID` bo'lishi kerak. Telegram ID ni `@userinfobot` orqali bilish mumkin. Gemini funksiyasi uchun Google AI Studio API key kerak:

```env
GEMINI_API_KEY=your_gemini_api_key
```

## GitHub'ga yuklash

1. GitHub'da yangi, bo'sh repository yarating.
2. PowerShell'da loyiha papkasida quyidagilarni bajaring:

```powershell
git init
git add main.py requirements.txt Dockerfile render.yaml README.md .gitignore
git commit -m "Prepare bot for deployment"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
git push -u origin main
```

`.env`, `.venv` va `bot.db` `.gitignore` orqali GitHub'ga yuborilmaydi. Tokenlarni hech qachon repository'ga commit qilmang.

## Render.com orqali deploy

1. [render.com](https://render.com) saytiga GitHub orqali kiring.
2. `New` -> `Blueprint` ni tanlang va bot repository'sini ulang.
3. Render `render.yaml` faylini avtomatik topadi. `Apply` ni bosing.
4. `BOT_TOKEN`, `ADMIN_ID` va `GEMINI_API_KEY` uchun secret qiymatlarni Render dashboard'dagi `Environment` bo'limida kiriting.
5. `Manual Deploy` -> `Deploy latest commit` ni bosing.
6. `Logs` bo'limida `Bot ishga tushmoqda...` yozuvi chiqishini kuting.
7. Telegram'da botga `/start` yuboring.

Render free web service ishlashi uchun Docker image `PORT` qiymatidagi portda health endpoint ochadi. `render.yaml` dagi `/healthz` shu maqsadda ishlatiladi.

## Koyeb orqali deploy

1. [app.koyeb.com](https://app.koyeb.com) saytiga GitHub orqali kiring.
2. `Create App` -> `Web Service` -> `GitHub` ni tanlang va repository'ni ulang.
3. Build method sifatida `Dockerfile` ni tanlang.
4. Environment variables bo'limida quyidagilarni secret sifatida qo'shing: `BOT_TOKEN`, `ADMIN_ID`, `GEMINI_API_KEY`, `GEMINI_MODEL`.
5. Service'ni deploy qiling va deployment loglarida bot ishga tushganini tekshiring.

## Muhim bepul tarif cheklovi

Render free service uzoq vaqt HTTP trafik bo'lmasa sleep rejimiga o'tishi mumkin. Shu sababli Render free tarifida Telegram polling bot uchun haqiqiy kafolatlangan 24/7 ishlash mavjud emas. Koyeb free tarifining joriy limitlarini ham deploydan oldin tekshiring. Kafolatlangan to'xtovsiz ishlash uchun doimiy VPS yoki pullik worker/service kerak bo'ladi.

SQLite (`bot.db`) container ichida saqlanadi va bepul server qayta deploy/restart bo'lganda yo'qolishi mumkin. Doimiy ma'lumotlar uchun PostgreSQL yoki persistent disk ishlating.

## Funksiyalar

- `/start` foydalanuvchini SQLite bazasiga saqlaydi.
- `Portfolio`, `Xizmatlar`, `Aloqa` menyulari mavjud.
- `/admin` faqat `ADMIN_ID` uchun ochiladi.
- Admin panelida statistika, broadcast va kontent tahriri mavjud.
- `Gemini bilan suhbat` tugmasi orqali Gemini bilan suhbatlashish mumkin.
