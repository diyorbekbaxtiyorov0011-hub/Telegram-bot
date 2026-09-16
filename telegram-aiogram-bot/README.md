# Telegram bot (aiogram 3.x)

## Ishga tushirish

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

`.env` faylidagi `ADMIN_ID` qiymatini o'zingizning Telegram ID raqamingizga almashtiring. Telegram ID ni `@userinfobot` orqali bilib olishingiz mumkin.

Gemini suhbatini yoqish uchun Google AI Studio'dan API key oling va `.env` fayliga yozing:

```env
GEMINI_API_KEY=your_gemini_api_key
```

## Funksiyalar

- `/start` foydalanuvchini SQLite bazasiga saqlaydi.
- `Portfolio`, `Xizmatlar`, `Aloqa` menyulari mavjud.
- `/admin` faqat `ADMIN_ID` uchun ochiladi.
- Admin panelida a'zolar statistikasi va broadcast mavjud.
- `Gemini bilan suhbat` tugmasi orqali Gemini bilan suhbatlashish mumkin.
