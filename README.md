# Vinted Wakeboard Monitor

Каждые 5 минут проверяет новые объявления по слову `wakeboard` на Vinted.sk и Vinted.at.

## GitHub Secrets

Добавь в `Settings → Secrets and variables → Actions`:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID` со значением `@from78kg`

Бот должен быть администратором канала.

Первый запуск сохраняет текущие объявления как базу и не отправляет старые карточки.

> Плановые workflow запускаются из default branch `main`.
