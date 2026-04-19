# RELEASE_CHECKLIST.md

## Назначение

Короткий чек-лист перед каждым релизом в PROD.

Используется каждый раз. Без исключений.

---

## 1. DEV проверка

### Среда
[ ] `./scripts/dev.sh smoke` → OK  
[ ] env корректный  
[ ] БД доступна  

---

### FREE сценарий

[ ] `/reset_profile`  
[ ] `/dev_free`  
[ ] `/dev_key`  

Проверить:
[ ] `access_type=free`  
[ ] `device_limit=1`  
[ ] `used_devices=1`  
[ ] ключ создаётся  

---

### PAID сценарий

[ ] `/reset_profile`  
[ ] `/dev_paid`  
[ ] `/dev_key`  
[ ] `/dev_key_2`  

Проверить:
[ ] `access_type=paid`  
[ ] `device_limit=2`  
[ ] `used_devices=2`  
[ ] 2 ключа создаются  

---

### Очистка

[ ] `/dev_key_clear`  
[ ] `used_devices=0`  
[ ] ключей нет  

---

## 2. Код

[ ] изменения работают в DEV  
[ ] нет лишнего debug-кода  
[ ] нет хардкодов  
[ ] нет временных костылей  

---

## 3. БД / миграции

Если были изменения моделей:

[ ] создана миграция  
[ ] `alembic upgrade head` прошёл  
[ ] структура БД корректна  

---

## 4. Git

```bash
git add .
git commit -m "release: <что сделали>"
git push
