# 🚀 Universal Media, Story (@username), Shazam & 2GB Bot Pro (v6)

## 🆕 v6 versiyada nimalar tuzatildi va qo'shildi?
1. **🛠 `Can't find end tag corresponding to start tag "b"` xatoligi 100% bartaraf etildi:**
   - Foydalanuvchi ismidagi yoki video sarlavhasidagi maxsus belgilar (`<`, `>`, `&`) avtomatik HTML-xavfsiz ko'rinishga (`html.escape`) o'tkaziladi.
   - Agar admin matn tahrirlashda HTML tegni yopishni unutib qo'ysa ham, `color_safe_request_middleware` xatolik bermasdan matnni avtomatik tozalab yuboradi!
2. **📝 Admin Paneldan Barcha Bot Matnlarini Tahrirlash (`👑 Admin Panel` -> `📝 Bot matnlarini tahrirlash`):**
   - Bot foydalanuvchiga yuboradigan **25 ta barcha xabar matnlarini** (`/start` matni, Majburiy obuna, Story bo'limi, Kabinet, Sozlamalar, Tarix, Saqlanganlar, Yordam, Shazam, Xatoliklar, Watermark va h.k.) kodga kirmasdan, to'g'ridan-to'g'ri Admin paneldan o'zgartirish va 1 tugma bilan standart holatiga qaytarish mumkin!
