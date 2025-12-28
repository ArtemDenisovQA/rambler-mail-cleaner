# rambler-mail-cleaner

Утилита на Python для массовой чистки почтового ящика **Rambler.ru** через **IMAP**: считает и (опционально) удаляет письма по правилам отправителя.

Главная идея текущей версии: **не полагаться на IMAP SEARCH**, а пройтись по всем письмам в папке и определить отправителя через `ENVELOPE.From`, а если ENVELOPE недоступен — через заголовок `From:`. Это надёжно и добивает случаи вроде `news@news.ozon.ru`.

⚠️ По умолчанию — **DRY-RUN** (ничего не удаляет). Удаление включается только флагом `--delete`.

---

## Возможности

- Подсчёт и удаление писем по правилам отправителя
- Поддержка:
  - обычных доменов: `ozon.ru` (совпадёт и `news.ozon.ru`, `sender.ozon.ru`)
  - масок по домену/хосту: `*mvideo.ru`
  - масок по полному адресу отправителя (нужно для Apple Hide My Email):  
    `noreply_at_redditmail_com_*@privaterelay.appleid.com`
- Обработка одной папки или нескольких, либо всех (`--folders "*"`)
- Работа большими пачками (`--batch`) для крупных ящиков

---

## Требования

- Python 3.10+
- Доступ для почтовых клиентов/IMAP включён в настройках Rambler

---

## Установка

```bash
git clone https://github.com/<your-username>/rambler-mail-cleaner.git
cd rambler-mail-cleaner

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt


## Настройка доступа (рекомендуется через .env)

Создай файл .env рядом с rambler_cleanup.py:
RAMBLER_USER=user@rambler.ru
RAMBLER_PASS=пароль_или_пароль_приложения

## Параметры

--folders — папки через запятую ("INBOX,Spam") или "*" для всех

--skip-folders — папки, которые пропустить (например "Sent Messages")

--rules — правила (домены/маски), через запятую

домен без wildcard: ozon.ru → матчится ozon.ru и *.ozon.ru

маска хоста: *mvideo.ru

маска полного email: noreply_at_redditmail_com_*@privaterelay.appleid.com

--batch — размер пачки UID для fetch/delete (по умолчанию 500)

--delete — реально удалять письма (без него — dry-run)
