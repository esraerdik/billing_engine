"""
constants.py
------------
Yönetmelikte tanımlı paylaşım oranları ve sistem genelinde kullanılan
sabit değerler burada tutulur. Oranlar tek noktadan yönetildiği için
ileride mevzuat değişse bile tek dosya güncellenir.
"""

from typing import Final

# 20.06.2008 tarihli "Merkezî Isıtma ve Sıhhî Sıcak Su Sistemlerinde Isınma ve
# Sıhhî Sıcak Su Giderlerinin Paylaştırılmasına İlişkin Yönetmelik" madde 3/4:
# Isınma gideri; %70 oranında ısı ölçer (kalorimetre) endeksine göre,
# %30 oranında ise bağımsız bölüm kullanım alanına (m²) göre paylaştırılır.
CONSUMPTION_SHARE_RATIO: Final[float] = 0.70
FIXED_SHARE_RATIO: Final[float] = 0.30

# Ortak gider oranlarının toplamı her zaman 1.0 olmalıdır; bu kontrol
# calculator katmanında da tekrar doğrulanır ama sabitler burada
# tanımlandığı için ilk doğrulama noktası burasıdır.
assert abs((CONSUMPTION_SHARE_RATIO + FIXED_SHARE_RATIO) - 1.0) < 1e-9, (
    "CONSUMPTION_SHARE_RATIO + FIXED_SHARE_RATIO toplamı 1.0 olmalıdır."
)

# Parasal tutarların yuvarlanacağı ondalık basamak sayısı (kuruş hassasiyeti).
CURRENCY_DECIMAL_PLACES: Final[int] = 2

# Oran (yüzde) değerlerinin raporlama amaçlı yuvarlanacağı basamak sayısı.
RATIO_DECIMAL_PLACES: Final[int] = 6

# Bir dönem (ay) için, admin onayı gerekmeden yapılabilecek ücretsiz
# faturalandırma çalıştırma sayısı. Bu değer aşıldığında her ek
# çalıştırma için admin onayı gerekir (bkz. authorization.py).
FREE_RUNS_PER_MONTH: Final[int] = 1
