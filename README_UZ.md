# TechMir POS — internet uchun web loyiha

## Nimalar bor
- Mavjud POS interfeysi saqlangan.
- Mahsulotlar, ombor qoldig‘i, sozlamalar va savdo tarixi serverdagi SQLite bazasida umumiy saqlanadi.
- Kirish paroli server tomonda tekshiriladi (`POS_PASSWORD`).
- Brauzerlar taxminan har 7 soniyada serverdagi o‘zgarishlarni tekshiradi.
- Mahsulot rasmi ixtiyoriy.

## Kompyuterda sinash (Windows)
1. Python 3.11+ o‘rnating.
2. Loyihaning shu papkasida CMD oching.
3. `python -m venv .venv`
4. `.venv\Scripts\activate`
5. `pip install -r requirements.txt`
6. `set COOKIE_SECURE=0`
7. `python app.py`
8. Brauzerda `http://localhost:8000` oching. Standart parol: `7484`.

## Internetga chiqarish (Render misoli)
1. Shu papkadagi fayllarni GitHub repository ga yuklang.
2. Render.com saytida **New + → Blueprint** tanlab repository ni ulang; `render.yaml` sozlamalarni yaratadi. Yoki Python web service yarating va build command `pip install -r requirements.txt`, start command `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4` kiriting.
3. Environment variables da `POS_PASSWORD` uchun kuchli parol belgilang. `SECRET_KEY` ham maxfiy va tasodifiy bo‘lishi kerak.
4. Persistent disk `/var/data` ulangan bo‘lishi shart; SQLite bazasi shu diskda saqlanadi.
5. Deploy tugagach, hosting bergan `https://...` manzil orqali kiring. HTTPS ishlating; ochiq internetda oddiy HTTP orqali parol yubormang.

## Muhim cheklovlar
- Bu bir do‘kon uchun sodda boshlang‘ich backend. Hamma kassirlar hozir bitta umumiy paroldan foydalanadi; alohida foydalanuvchi rollari va har kassir uchun login hali qo‘shilmagan.
- Hozirgi klient butun holatni saqlaydi. Ikki kassir bir vaqtda tahrir qilsa, birining so‘nggi saqlashi boshqasining o‘zgarishini bosib ketishi mumkin. Katta savdo uchun savdolar va mahsulot qoldig‘ini alohida atomik API amallariga o‘tkazish kerak.
- Hostingda doimiy disk bo‘lmasa, bepul hosting qayta ishga tushganda baza yo‘qolishi mumkin.
- Ma’lumotlar zaxira nusxasini muntazam oling.
