"use strict";
// Russian source messages are stable gettext-style keys. Keep placeholders identical.
globalThis.radioMessages = {
  "Наблюдались служебные пакеты DMR": {"en": "DMR service packets observed", "uk": "Спостерігалися службові пакети DMR"},
  "Ошибки кадров: {0}": {"en": "Frame errors: {0}", "uk": "Помилки кадрів: {0}"},
  "Голосовые пакеты DMR: {0}": {"en": "DMR voice packets: {0}", "uk": "Голосові пакети DMR: {0}"},
  "Служебные пакеты DMR: {0}": {"en": "DMR service packets: {0}", "uk": "Службові пакети DMR: {0}"},
  "Заголовок защиты DMR не разобран": {"en": "DMR privacy header unresolved", "uk": "Заголовок захисту DMR не розібрано"},

  "Приём при захвате: нет данных": {"en":"Signal at acquisition: no data","uk":"Приймання при захопленні: немає даних"},
  "Приём при захвате: {0} дБ над шумом": {"en":"Signal at acquisition: {0} dB above noise","uk":"Приймання при захопленні: {0} дБ над шумом"},
  "Превышение спектрального пика над оценкой фонового шума в момент захвата частоты. Больше — сигнал заметнее на фоне шума. Это не среднее за разговор и не оценка разборчивости речи.": {"en":"Spectral peak above the estimated noise floor when the channel was acquired. Higher means the signal stands out more from noise. This is neither a conversation average nor a measure of speech intelligibility.","uk":"Перевищення спектрального піка над оцінкою фонового шуму в момент захоплення частоти. Більше — сигнал помітніший на тлі шуму. Це не середнє за розмову й не оцінка розбірливості мовлення."},
  "Сканировать диапазон": {"en":"Scan this range","uk":"Сканувати діапазон"},
  "Включён": {"en":"Enabled","uk":"Увімкнено"},
  "Выключен": {"en":"Disabled","uk":"Вимкнено"},
  "Диапазоны выключены": {"en":"Scan ranges are disabled","uk":"Діапазони вимкнено"},
  "Включите диапазон в настройках, чтобы начать приём.": {"en":"Enable a range in settings to start reception.","uk":"Увімкніть діапазон у налаштуваннях, щоб почати приймання."},
  "Все записи": {
    "en": "All recordings",
    "uk": "Усі записи"
  },
  "Сохранить": {
    "en": "Save",
    "uk": "Зберегти"
  },
  "Отмена": {
    "en": "Cancel",
    "uk": "Скасувати"
  },
  "Связь прервалась. Результат действия неизвестен — после восстановления проверьте, применилось ли оно.": {
    "en": "Connection lost. The result is unknown — check whether the action completed once reconnected.",
    "uk": "Зв’язок перервано. Результат дії невідомий — після відновлення перевірте, чи її виконано."
  },
  "Нет связи с сервером. Повторяем подключение…": {
    "en": "Server unavailable. Reconnecting…",
    "uk": "Немає зв’язку із сервером. Повторюємо підключення…"
  },
  "Состояние приёмника неизвестно": {
    "en": "Receiver status unknown",
    "uk": "Стан приймача невідомий"
  },
  "Ждём ответ сервера. На экране последние полученные данные.": {
    "en": "Waiting for the server. Showing the last received data.",
    "uk": "Чекаємо на відповідь сервера. На екрані останні отримані дані."
  },
  "Не удалось выполнить действие ({0})": {
    "en": "Action failed ({0})",
    "uk": "Не вдалося виконати дію ({0})"
  },
  "Удалить группу {0} МГц?": {
    "en": "Delete the {0} MHz group?",
    "uk": "Видалити групу {0} МГц?"
  },
  "Удалить запись?": {
    "en": "Delete recording?",
    "uk": "Видалити запис?"
  },
  "Будет удалено разговоров: {0}, включая все их части, оригиналы и очищенные копии. ": {
    "en": "Conversations to delete: {0}, including every part, original and cleaned copy. ",
    "uk": "Буде видалено розмов: {0}, включно з усіма частинами, оригіналами й очищеними копіями. "
  },
  "Это все записи частоты за все даты, включая скрытые фильтрами. ": {
    "en": "This includes all recordings on this frequency across all dates, even those hidden by filters. ",
    "uk": "Це всі записи частоти за всі дати, зокрема приховані фільтрами. "
  },
  "Восстановить их нельзя. Настройки приёма частоты сохранятся.": {
    "en": "This cannot be undone. Reception settings for this frequency will be kept.",
    "uk": "Відновити їх неможливо. Налаштування приймання частоти буде збережено."
  },
  "Записи убраны из архива. Некоторые файлы заняты; очистка диска повторится при следующем запуске.": {
    "en": "Recordings removed from the archive. Some files are in use; disk cleanup will retry at the next launch.",
    "uk": "Записи прибрано з архіву. Деякі файли зайняті; очищення диска повториться під час наступного запуску."
  },
  "Записи удалены. Настройки приёма сохранены.": {
    "en": "Recordings deleted. Reception settings kept.",
    "uk": "Записи видалено. Налаштування приймання збережено."
  },
  " Закройте окно и повторите удаление.": {
    "en": " Close the dialog and try deleting again.",
    "uk": " Закрийте вікно та повторіть видалення."
  },
  " МГц · от старых к новым": {
    "en": " MHz · oldest first",
    "uk": " МГц · від старих до нових"
  },
  "Частот: {0} · записей: {1} · {2} для прослушивания": {
    "en": "Frequencies: {0} · recordings: {1} · {2} to listen to",
    "uk": "Частот: {0} · записів: {1} · {2} для прослуховування"
  },
  "Готовые записи появятся здесь": {
    "en": "Completed recordings will appear here",
    "uk": "Готові записи з’являться тут"
  },
  "Показаны загруженные записи с учётом фильтров. Загрузите ещё, чтобы увидеть более ранние записи и частоты.": {
    "en": "Showing loaded recordings matching your filters. Load more to see earlier recordings and frequencies.",
    "uk": "Показано завантажені записи з урахуванням фільтрів. Завантажте ще, щоб побачити попередні записи та частоти."
  },
  "С учётом выбранных фильтров · новые записи появляются автоматически": {
    "en": "Matching your filters · new recordings appear automatically",
    "uk": "З урахуванням вибраних фільтрів · нові записи з’являються автоматично"
  },
  "Записей не найдено": {
    "en": "No recordings found",
    "uk": "Записів не знайдено"
  },
  "Архив пока пуст": {
    "en": "The archive is empty",
    "uk": "Архів поки порожній"
  },
  "Попробуйте другую дату, фильтр или очистите поиск.": {
    "en": "Try another date or filter, or clear the search.",
    "uk": "Спробуйте іншу дату, фільтр або очистьте пошук."
  },
  "Когда приёмник найдёт речь, здесь появится запись. Её можно будет прослушать и перейти к следующей.": {
    "en": "When the receiver detects speech, a recording will appear here. Listen to it and move to the next one.",
    "uk": "Коли приймач виявить мовлення, тут з’явиться запис. Його можна буде прослухати й перейти до наступного."
  },
  " МГц": {
    "en": " MHz",
    "uk": " МГц"
  },
  "Записей: {0} · {1} для прослушивания": {
    "en": "Recordings: {0} · {1} to listen to",
    "uk": "Записів: {0} · {1} для прослуховування"
  },
  "Записи частоты {0} МГц": {
    "en": "Recordings on {0} MHz",
    "uk": "Записи частоти {0} МГц"
  },
  "В чёрном списке": {
    "en": "Blacklisted",
    "uk": "У чорному списку"
  },
  "Не прослушано: {0}": {
    "en": "Unplayed: {0}",
    "uk": "Не прослухано: {0}"
  },
  "Всё прослушано": {
    "en": "All played",
    "uk": "Усе прослухано"
  },
  "● Записывается": {
    "en": "● Recording",
    "uk": "● Записується"
  },
  "В плеере": {
    "en": "In player",
    "uk": "У плеєрі"
  },
  "Сейчас слушаете": {
    "en": "Now playing",
    "uk": "Зараз слухаєте"
  },
  "▶ Слушать частоту": {
    "en": "▶ Play frequency",
    "uk": "▶ Слухати частоту"
  },
  "Слушать частоту {0} МГц": {
    "en": "Play frequency {0} MHz",
    "uk": "Слухати частоту {0} МГц"
  },
  "Загруженные записи этой частоты от старых к новым, с учётом фильтров": {
    "en": "Loaded recordings on this frequency, oldest first, matching your filters",
    "uk": "Завантажені записи цієї частоти від старих до нових, з урахуванням фільтрів"
  },
  "Последняя запись: {0} · {1}": {
    "en": "Latest recording: {0} · {1}",
    "uk": "Останній запис: {0} · {1}"
  },
  "Слушать {0} МГц, {1}": {
    "en": "Play {0} MHz, {1}",
    "uk": "Слухати {0} МГц, {1}"
  },
  "Запись эфира": {
    "en": "Radio recording",
    "uk": "Запис ефіру"
  },
  " · Тестовая запись": {
    "en": " · Test recording",
    "uk": " · Тестовий запис"
  },
  "Не прослушано": {
    "en": "Unplayed",
    "uk": "Не прослухано"
  },
  "Убрать из избранного": {
    "en": "Remove from favorites",
    "uk": "Прибрати з обраного"
  },
  "В избранное": {
    "en": "Add to favorites",
    "uk": "До обраного"
  },
  "Запись с разрывом": {
    "en": "Recording has a gap",
    "uk": "Запис із розривом"
  },
  "Действия с записью": {
    "en": "Recording actions",
    "uk": "Дії із записом"
  },
  "Назвать запись": {
    "en": "Rename recording",
    "uk": "Назвати запис"
  },
  "Название записи": {
    "en": "Recording name",
    "uk": "Назва запису"
  },
  "Отметить непрослушанным": {
    "en": "Mark as unplayed",
    "uk": "Позначити непрослуханим"
  },
  "Отметить прослушанным": {
    "en": "Mark as played",
    "uk": "Позначити прослуханим"
  },
  "Удалить запись": {
    "en": "Delete recording",
    "uk": "Видалити запис"
  },
  "Идёт запись": {
    "en": "Recording",
    "uk": "Триває запис"
  },
  "Все записи · от новых к старым": {
    "en": "All recordings · newest first",
    "uk": "Усі записи · від нових до старих"
  },
  "Очищается…": {
    "en": "Cleaning…",
    "uk": "Очищується…"
  },
  "Повторить очистку": {
    "en": "Retry cleanup",
    "uk": "Повторити очищення"
  },
  "Улучшить очистку": {
    "en": "Improve cleanup",
    "uk": "Поліпшити очищення"
  },
  "Очистить звук": {
    "en": "Clean audio",
    "uk": "Очистити звук"
  },
  "{0} МГц исключена из записи": {
    "en": "{0} MHz excluded from recording",
    "uk": "{0} МГц виключено із запису"
  },
  "Настройка частоты сохранена": {
    "en": "Frequency setting saved",
    "uk": "Налаштування частоти збережено"
  },
  "Убрать частоту из избранного": {
    "en": "Remove frequency from favorites",
    "uk": "Прибрати частоту з обраного"
  },
  "В избранные частоты": {
    "en": "Add to favorite frequencies",
    "uk": "До обраних частот"
  },
  "{0} {1} МГц": {
    "en": "{0} {1} MHz",
    "uk": "{0} {1} МГц"
  },
  "Действия с частотой {0} МГц": {
    "en": "Actions for {0} MHz",
    "uk": "Дії з частотою {0} МГц"
  },
  "Назвать частоту": {
    "en": "Name frequency",
    "uk": "Назвати частоту"
  },
  "Название частоты": {
    "en": "Frequency name",
    "uk": "Назва частоти"
  },
  "Убрать из чёрного списка": {
    "en": "Remove from blacklist",
    "uk": "Прибрати з чорного списку"
  },
  "Добавить в чёрный список": {
    "en": "Add to blacklist",
    "uk": "Додати до чорного списку"
  },
  "Убрать приоритет сканирования": {
    "en": "Remove scan priority",
    "uk": "Прибрати пріоритет сканування"
  },
  "Чаще проверять эту частоту": {
    "en": "Check this frequency more often",
    "uk": "Частіше перевіряти цю частоту"
  },
  "Удалить записи частоты": {
    "en": "Delete frequency recordings",
    "uk": "Видалити записи частоти"
  },
  "Здесь появятся важные частоты и исключения.": {
    "en": "Important frequencies and exclusions will appear here.",
    "uk": "Тут з’являться важливі частоти та виключення."
  },
  " МГц · ": {
    "en": " MHz · ",
    "uk": " МГц · "
  },
  "Приоритет сканирования": {
    "en": "Scan priority",
    "uk": "Пріоритет сканування"
  },
  "Повторная проверка через {0} мин": {
    "en": "Check again in {0} min",
    "uk": "Повторна перевірка через {0} хв"
  },
  "Участвует в поиске в выбранных диапазонах": {
    "en": "Included in scanning within selected ranges",
    "uk": "Бере участь у пошуку у вибраних діапазонах"
  },
  "Есть несохранённые изменения": {
    "en": "You have unsaved changes",
    "uk": "Є незбережені зміни"
  },
  "От, МГц": {
    "en": "From, MHz",
    "uk": "Від, МГц"
  },
  "До, МГц": {
    "en": "To, MHz",
    "uk": "До, МГц"
  },
  "Убрать": {
    "en": "Remove",
    "uk": "Прибрати"
  },
  "Убрать диапазон": {
    "en": "Remove range",
    "uk": "Прибрати діапазон"
  },
  "Найти автоматически": {
    "en": "Detect automatically",
    "uk": "Знайти автоматично"
  },
  "HackRF {0} · сейчас не найден": {
    "en": "HackRF {0} · not found now",
    "uk": "HackRF {0} · зараз не знайдено"
  },
  "Найдено устройств: {0}": {
    "en": "Devices found: {0}",
    "uk": "Знайдено пристроїв: {0}"
  },
  "Разрешённые границы профиля: ": {
    "en": "Allowed profile ranges: ",
    "uk": "Дозволені межі профілю: "
  },
  "{0}–{1} МГц": {
    "en": "{0}–{1} MHz",
    "uk": "{0}–{1} МГц"
  },
  "Сохранено. Применим после текущего разговора.": {
    "en": "Saved. Will apply after the current conversation.",
    "uk": "Збережено. Застосуємо після поточної розмови."
  },
  "Настройки применены": {
    "en": "Settings applied",
    "uk": "Налаштування застосовано"
  },
  "Добавьте хотя бы один диапазон": {
    "en": "Add at least one range",
    "uk": "Додайте хоча б один діапазон"
  },
  "Предыдущие изменения сохранены. Новые изменения ещё не сохранены.": {
    "en": "Previous changes saved. Your newer changes are still unsaved.",
    "uk": "Попередні зміни збережено. Нові зміни ще не збережено."
  },
  "Приём остановлен": {
    "en": "Reception stopped",
    "uk": "Приймання зупинено"
  },
  "Обзор эфира · запись выключена": {
    "en": "Spectrum preview · recording off",
    "uk": "Огляд ефіру · запис вимкнено"
  },
  "Ищем разговоры": {
    "en": "Scanning for conversations",
    "uk": "Шукаємо розмови"
  },
  "Проверяем сигнал": {
    "en": "Checking signal",
    "uk": "Перевіряємо сигнал"
  },
  "Записываем разговор": {
    "en": "Recording conversation",
    "uk": "Записуємо розмову"
  },
  "Ждём ответ": {
    "en": "Waiting for a reply",
    "uk": "Чекаємо на відповідь"
  },
  "{0} МГц{1}": {
    "en": "{0} MHz{1}",
    "uk": "{0} МГц{1}"
  },
  "Сканируем выбранные диапазоны · записи сохраняются на этом ПК": {
    "en": "Scanning selected ranges · recordings stay on this PC",
    "uk": "Скануємо вибрані діапазони · записи зберігаються на цьому ПК"
  },
  "Остановить приём": {
    "en": "Stop reception",
    "uk": "Зупинити приймання"
  },
  "Начать приём": {
    "en": "Start reception",
    "uk": "Почати приймання"
  },
  "Восстанавливаем связь с приёмником…": {
    "en": "Reconnecting to receiver…",
    "uk": "Відновлюємо зв’язок із приймачем…"
  },
  "Приём остановлен: ": {
    "en": "Reception stopped: ",
    "uk": "Приймання зупинено: "
  },
  "Журнал диагностики заполнен. Запись разговоров продолжается; старые данные сохранены.": {
    "en": "Diagnostic log full. Conversations are still being recorded; existing data is preserved.",
    "uk": "Журнал діагностики заповнено. Запис розмов триває; старі дані збережено."
  },
  "Тестовый источник: это не эфир с HackRF.": {
    "en": "Test source: this is not live HackRF reception.",
    "uk": "Тестове джерело: це не ефір із HackRF."
  },
  "Восстанавливаем связь": {
    "en": "Reconnecting",
    "uk": "Відновлюємо зв’язок"
  },
  "Приём остановлен:": {
    "en": "Reception stopped:",
    "uk": "Приймання зупинено:"
  },
  "Синтетический IQ": {
    "en": "Synthetic IQ",
    "uk": "Синтетичний IQ"
  },
  "CPU {0}% · {1} МБ": {
    "en": "CPU {0}% · {1} MB",
    "uk": "CPU {0}% · {1} МБ"
  },
  "Потери приложения: {0} отсчётов · USB: неизвестно": {
    "en": "Application loss: {0} samples · USB: unknown",
    "uk": "Втрати застосунку: {0} відліків · USB: невідомо"
  },
  "Пик АЦП {0} дБFS · крайние значения {1}% выборки": {
    "en": "ADC peak {0} dBFS · rail values {1}% of sample",
    "uk": "Пік АЦП {0} дБFS · крайні значення {1}% вибірки"
  },
  "Уровень приёмника: ждём измерение": {
    "en": "Receiver level: awaiting measurement",
    "uk": "Рівень приймача: чекаємо на вимірювання"
  },
  "Архив: {0} / {1} МБ · свободно {2} ГиБ": {
    "en": "Archive: {0} / {1} MB · {2} GiB free",
    "uk": "Архів: {0} / {1} МБ · вільно {2} ГіБ"
  },
  "Есть признак шифрования": {
    "en": "Encryption indication detected",
    "uk": "Є ознака шифрування"
  },
  "Выбрана аналоговая речь": {
    "en": "Analog speech selected",
    "uk": "Вибрано аналогове мовлення"
  },
  "Получен звук · речь не подтверждена": {
    "en": "Audio received · speech unconfirmed",
    "uk": "Отримано звук · мовлення не підтверджено"
  },
  "Есть синхронизация · звука нет": {
    "en": "Sync detected · no audio",
    "uk": "Є синхронізація · звуку немає"
  },
  "Речь и цифровой формат не подтверждены": {
    "en": "Speech and digital format unconfirmed",
    "uk": "Мовлення та цифровий формат не підтверджено"
  },
  "Аналоговая FM": {
    "en": "Analog FM",
    "uk": "Аналогова FM"
  },
  "Возможный формат: ": {
    "en": "Possible format: ",
    "uk": "Можливий формат: "
  },
  "Неизвестный сигнал": {
    "en": "Unknown signal",
    "uk": "Невідомий сигнал"
  },
  "{0} · {1} МГц · {2} · {3}{4}": {
    "en": "{0} · {1} MHz · {2} · {3}{4}",
    "uk": "{0} · {1} МГц · {2} · {3}{4}"
  },
  "Проверок сигналов пока нет.": {
    "en": "No signal checks yet.",
    "uk": "Перевірок сигналів поки немає."
  },
  "приём": {
    "en": "receiving",
    "uk": "приймання"
  },
  "ожидание": {
    "en": "waiting",
    "uk": "очікування"
  },
  " с назад": {
    "en": " s ago",
    "uk": " с тому"
  },
  "{0}: {1}–{2} МГц · {3}": {
    "en": "{0}: {1}–{2} MHz · {3}",
    "uk": "{0}: {1}–{2} МГц · {3}"
  },
  "Ошибка декодера": {
    "en": "Decoder error",
    "uk": "Помилка декодера"
  },
  "Сигнал исчез к концу проверки": {
    "en": "Signal disappeared by the end of the check",
    "uk": "Сигнал зник до кінця перевірки"
  },
  "Сигнал отсутствует или ниже порога приёма": {
    "en": "Signal absent or below reception threshold",
    "uk": "Сигнал відсутній або нижче порога приймання"
  },
  "Декодер сообщил ошибки кадров": {
    "en": "Decoder reported frame errors",
    "uk": "Декодер повідомив про помилки кадрів"
  },
  "Цифровая синхронизация не найдена": {
    "en": "No digital sync found",
    "uk": "Цифрову синхронізацію не знайдено"
  },
  "Недостаточно совпадений синхронизации": {
    "en": "Insufficient sync matches",
    "uk": "Недостатньо збігів синхронізації"
  },
  "Настройка уточнена на {0} кГц": {
    "en": "Tuning adjusted by {0} kHz",
    "uk": "Налаштування уточнено на {0} кГц"
  },
  "Сигнал выше порога {0}% времени": {
    "en": "Signal above threshold {0}% of the time",
    "uk": "Сигнал вище порога {0}% часу"
  },
  "Звук выключен": {
    "en": "Audio off",
    "uk": "Звук вимкнено"
  },
  "Ждём разговор": {
    "en": "Waiting for a conversation",
    "uk": "Чекаємо на розмову"
  },
  "Цифровая запись — после завершения": {
    "en": "Digital audio available after recording",
    "uk": "Цифровий запис — після завершення"
  },
  "Слушаем разговор": {
    "en": "Listening to conversation",
    "uk": "Слухаємо розмову"
  },
  "Восстанавливаем звук…": {
    "en": "Reconnecting audio…",
    "uk": "Відновлюємо звук…"
  },
  "Подключаем звук…": {
    "en": "Connecting audio…",
    "uk": "Підключаємо звук…"
  },
  "Не удалось включить звук. Попробуйте ещё раз.": {
    "en": "Could not enable audio. Please try again.",
    "uk": "Не вдалося ввімкнути звук. Спробуйте ще раз."
  },
  "RadioMind · Записи эфира": {
    "en": "RadioMind · Radio recordings",
    "uk": "RadioMind · Записи ефіру"
  },
  "RadioMind — записи эфира": {
    "en": "RadioMind — radio recordings",
    "uk": "RadioMind — записи ефіру"
  },
  "Запись и архив эфира": {
    "en": "Radio recording & archive",
    "uk": "Запис та архів ефіру"
  },
  "Разделы": {
    "en": "Sections",
    "uk": "Розділи"
  },
  "Записи": {
    "en": "Recordings",
    "uk": "Записи"
  },
  "Частоты": {
    "en": "Frequencies",
    "uk": "Частоти"
  },
  "Настройки": {
    "en": "Settings",
    "uk": "Налаштування"
  },
  "Диагностика": {
    "en": "Diagnostics",
    "uk": "Діагностика"
  },
  "Управление приёмником": {
    "en": "Receiver controls",
    "uk": "Керування приймачем"
  },
  "Приёмник": {
    "en": "Receiver",
    "uk": "Приймач"
  },
  "Подключаемся к приёмнику": {
    "en": "Connecting to receiver",
    "uk": "Підключаємося до приймача"
  },
  "Запись речи и удобное прослушивание": {
    "en": "Record speech and listen at your convenience",
    "uk": "Запис мовлення та зручне прослуховування"
  },
  "Слушать эфир": {
    "en": "Listen live",
    "uk": "Слухати ефір"
  },
  "Записи эфира": {
    "en": "Radio recordings",
    "uk": "Записи ефіру"
  },
  "▶ Слушать подряд": {
    "en": "▶ Play all",
    "uk": "▶ Слухати поспіль"
  },
  "Поиск по частоте или названию": {
    "en": "Search by frequency or name",
    "uk": "Пошук за частотою або назвою"
  },
  "Найти частоту или название": {
    "en": "Find a frequency or name",
    "uk": "Знайти частоту або назву"
  },
  "Дата": {
    "en": "Date",
    "uk": "Дата"
  },
  "Дата записей": {
    "en": "Recording date",
    "uk": "Дата записів"
  },
  "Фильтр записей": {
    "en": "Recording filter",
    "uk": "Фільтр записів"
  },
  "Непрослушанные": {
    "en": "Unplayed",
    "uk": "Непрослухані"
  },
  "Избранные записи": {
    "en": "Favorite recordings",
    "uk": "Обрані записи"
  },
  "Избранные частоты": {
    "en": "Favorite frequencies",
    "uk": "Обрані частоти"
  },
  "Группировка": {
    "en": "Grouping",
    "uk": "Групування"
  },
  "По частотам": {
    "en": "By frequency",
    "uk": "За частотами"
  },
  "По дням": {
    "en": "By day",
    "uk": "За днями"
  },
  "Порядок частот": {
    "en": "Frequency order",
    "uk": "Порядок частот"
  },
  "Недавно активные": {
    "en": "Recently active",
    "uk": "Нещодавно активні"
  },
  "По возрастанию частоты": {
    "en": "Frequency ascending",
    "uk": "За зростанням частоти"
  },
  "Больше непрослушанных": {
    "en": "Most unplayed",
    "uk": "Більше непрослуханих"
  },
  "Развернуть все": {
    "en": "Expand all",
    "uk": "Розгорнути всі"
  },
  "Свернуть все": {
    "en": "Collapse all",
    "uk": "Згорнути всі"
  },
  "Когда приёмник найдёт речь, здесь появится запись.": {
    "en": "When the receiver detects speech, a recording will appear here.",
    "uk": "Коли приймач виявить мовлення, тут з’явиться запис."
  },
  "Вы сможете прослушать её и перейти к следующей.": {
    "en": "You can listen to it and move to the next one.",
    "uk": "Ви зможете прослухати його й перейти до наступного."
  },
  "Показать ещё записи": {
    "en": "Load more recordings",
    "uk": "Показати ще записи"
  },
  "Записываются фрагменты, похожие на речь. Шум иногда может пройти отбор; его частоту можно исключить.": {
    "en": "Speech-like segments are recorded. Noise may sometimes pass the filter; you can exclude its frequency.",
    "uk": "Записуються фрагменти, схожі на мовлення. Шум іноді може пройти відбір; його частоту можна виключити."
  },
  "Ваши частоты": {
    "en": "Your frequencies",
    "uk": "Ваші частоти"
  },
  "Исключайте помехи и отмечайте важные каналы.": {
    "en": "Exclude interference and mark important channels.",
    "uk": "Виключайте завади та позначайте важливі канали."
  },
  "Частота, МГц": {
    "en": "Frequency, MHz",
    "uk": "Частота, МГц"
  },
  "Действие с частотой": {
    "en": "Frequency action",
    "uk": "Дія з частотою"
  },
  "Не записывать": {
    "en": "Exclude from recording",
    "uk": "Не записувати"
  },
  "Приоритетная": {
    "en": "Priority",
    "uk": "Пріоритетна"
  },
  "Вернуть в поиск": {
    "en": "Include in scanning",
    "uk": "Повернути до пошуку"
  },
  "Применить": {
    "en": "Apply",
    "uk": "Застосувати"
  },
  "Если несколько проверок не подтверждают речь, канал получает временную паузу. Затем он проверяется снова. Ручные исключения действуют до отмены. Важные частоты проверяются чаще. Во время разговора приёмник остаётся на его частоте.": {
    "en": "After several checks without speech, a channel is temporarily paused, then checked again. Manual exclusions stay until removed. Priority frequencies are checked more often. During a conversation, the receiver stays on its frequency.",
    "uk": "Якщо кілька перевірок не підтверджують мовлення, канал отримує тимчасову паузу. Потім його перевіряють знову. Ручні виключення діють до скасування. Важливі частоти перевіряються частіше. Під час розмови приймач залишається на її частоті."
  },
  "Настройки приёма": {
    "en": "Reception settings",
    "uk": "Налаштування приймання"
  },
  "Устройство и диапазоны, в которых искать разговоры.": {
    "en": "Choose a device and ranges to scan for conversations.",
    "uk": "Пристрій і діапазони, у яких шукати розмови."
  },
  "USB-подключение на этом компьютере. Автоопределение выбирает первый найденный HackRF.": {
    "en": "USB connection on this computer. Auto-detection selects the first HackRF found.",
    "uk": "USB-підключення на цьому комп’ютері. Автовизначення вибирає перший знайдений HackRF."
  },
  "Устройство": {
    "en": "Device",
    "uk": "Пристрій"
  },
  "Устройство HackRF": {
    "en": "HackRF device",
    "uk": "Пристрій HackRF"
  },
  "Обновить список": {
    "en": "Refresh list",
    "uk": "Оновити список"
  },
  "Усиление приёма": {
    "en": "Receiver gain",
    "uk": "Підсилення приймання"
  },
  "Уровень усиления": {
    "en": "Gain level",
    "uk": "Рівень підсилення"
  },
  "Пониженное": {
    "en": "Low",
    "uk": "Знижене"
  },
  "Обычное": {
    "en": "Normal",
    "uk": "Звичайне"
  },
  "Повышенное": {
    "en": "High",
    "uk": "Підвищене"
  },
  "Повышенное усиление может помочь слабым сигналам. Если помех становится больше, верните обычное или пониженное. Изменение применится после разговора.": {
    "en": "Higher gain may help weak signals. If interference increases, return to normal or low gain. Changes apply after the conversation.",
    "uk": "Підвищене підсилення може допомогти слабким сигналам. Якщо завад стає більше, поверніть звичайне або знижене. Зміна застосовується після розмови."
  },
  "Диапазоны сканирования": {
    "en": "Scan ranges",
    "uk": "Діапазони сканування"
  },
  "Укажите начало и конец в МГц. Можно добавить несколько диапазонов.": {
    "en": "Enter start and end frequencies in MHz. You can add multiple ranges.",
    "uk": "Укажіть початок і кінець у МГц. Можна додати кілька діапазонів."
  },
  "+ Добавить диапазон": {
    "en": "+ Add range",
    "uk": "+ Додати діапазон"
  },
  "Сохранить настройки": {
    "en": "Save settings",
    "uk": "Зберегти налаштування"
  },
  "Отменить изменения": {
    "en": "Discard changes",
    "uk": "Скасувати зміни"
  },
  "Текущий разговор будет дописан. Затем приём кратко переподключится с новыми настройками.": {
    "en": "The current conversation will finish recording. Reception will then reconnect briefly with the new settings.",
    "uk": "Поточну розмову буде дописано. Потім приймання короткочасно перепідключиться з новими налаштуваннями."
  },
  "Технические сведения для проверки приёма.": {
    "en": "Technical information for checking reception.",
    "uk": "Технічні відомості для перевірки приймання."
  },
  "Удерживать окно": {
    "en": "Hold window",
    "uk": "Утримувати вікно"
  },
  "Обходить диапазоны": {
    "en": "Scan ranges",
    "uk": "Обходити діапазони"
  },
  "Спектр": {
    "en": "Spectrum",
    "uk": "Спектр"
  },
  "Водопад": {
    "en": "Waterfall",
    "uk": "Водоспад"
  },
  "PSD: dBFS/Hz. Один приёмник наблюдает одно окно за раз. Точный центр имеет DC-слепую зону. Потери USB неизвестны.": {
    "en": "PSD: dBFS/Hz. One receiver observes one window at a time. The exact center has a DC blind spot. USB losses are unknown.",
    "uk": "PSD: dBFS/Hz. Один приймач спостерігає одне вікно за раз. Точний центр має сліпу зону DC. Втрати USB невідомі."
  },
  "Последние проверки сигналов": {
    "en": "Recent signal checks",
    "uk": "Останні перевірки сигналів"
  },
  "Здесь показаны все обнаруженные сигналы: аналоговые, цифровые и неизвестные. Срабатывание ещё не подтверждает речь или цифровой формат. Признак шифрования сам по себе не определяет формат.": {
    "en": "All detected signals are shown here: analog, digital and unknown. Detection alone does not confirm speech or a digital format. An encryption indication alone does not identify the format.",
    "uk": "Тут показано всі виявлені сигнали: аналогові, цифрові й невідомі. Спрацювання ще не підтверджує мовлення або цифровий формат. Ознака шифрування сама по собі не визначає формат."
  },
  "RadioMind · только приём": {
    "en": "RadioMind · receive only",
    "uk": "RadioMind · лише приймання"
  },
  "Данные остаются на этом ПК": {
    "en": "Data stays on this PC",
    "uk": "Дані залишаються на цьому ПК"
  },
  "Плеер записи": {
    "en": "Recording player",
    "uk": "Плеєр запису"
  },
  "Версия звука": {
    "en": "Audio version",
    "uk": "Версія звуку"
  },
  "Оригинал": {
    "en": "Original",
    "uk": "Оригінал"
  },
  "Очищено": {
    "en": "Cleaned",
    "uk": "Очищено"
  },
  "Предыдущая запись": {
    "en": "Previous recording",
    "uk": "Попередній запис"
  },
  "Следующая запись": {
    "en": "Next recording",
    "uk": "Наступний запис"
  },
  "Подряд": {
    "en": "Autoplay",
    "uk": "Поспіль"
  },
  "Удалить безвозвратно": {
    "en": "Delete permanently",
    "uk": "Видалити назавжди"
  },
  "Язык интерфейса": {
    "en": "Interface language",
    "uk": "Мова інтерфейсу"
  },
  "Серийный номер недоступен": {
    "en": "Serial number unavailable",
    "uk": "Серійний номер недоступний"
  },
  "Сейчас используется": {
    "en": "Currently in use",
    "uk": "Зараз використовується"
  },
  "Тестовый источник: выбор USB недоступен": {
    "en": "Test source: USB selection unavailable",
    "uk": "Тестове джерело: вибір USB недоступний"
  },
  "Библиотека HackRF не настроена": {
    "en": "HackRF library is not configured",
    "uk": "Бібліотеку HackRF не налаштовано"
  },
  "HackRF не найден. Проверьте USB-подключение.": {
    "en": "HackRF not found. Check the USB connection.",
    "uk": "HackRF не знайдено. Перевірте USB-підключення."
  },
  "Не удалось прочитать список USB-устройств": {
    "en": "Could not read the USB device list",
    "uk": "Не вдалося прочитати список USB-пристроїв"
  },
  "HackRF не вернул список устройств": {
    "en": "HackRF did not return a device list",
    "uk": "HackRF не повернув список пристроїв"
  },
  "Поиск HackRF занял слишком много времени. Повторите попытку.": {
    "en": "HackRF search timed out. Please try again.",
    "uk": "Пошук HackRF тривав надто довго. Повторіть спробу."
  },
  "Не удалось найти HackRF. Проверьте USB и библиотеку приёмника.": {
    "en": "Could not find HackRF. Check USB and the receiver library.",
    "uk": "Не вдалося знайти HackRF. Перевірте USB та бібліотеку приймача."
  },
  "Очищенная копия ещё не готова": {
    "en": "The cleaned copy is not ready yet",
    "uk": "Очищена копія ще не готова"
  },
  "Диапазоны не должны пересекаться": {
    "en": "Ranges must not overlap",
    "uk": "Діапазони не мають перетинатися"
  },
  "Диапазон выходит за разрешённые границы профиля приёма": {
    "en": "Range exceeds the allowed reception profile limits",
    "uk": "Діапазон виходить за дозволені межі профілю приймання"
  },
  "На этой частоте идёт захват. Дождитесь окончания разговора.": {
    "en": "This frequency is being captured. Wait for the conversation to finish.",
    "uk": "На цій частоті триває захоплення. Дочекайтеся завершення розмови."
  },
  "Дождитесь завершения очистки звука.": {
    "en": "Wait for audio cleanup to finish.",
    "uk": "Дочекайтеся завершення очищення звуку."
  },
  "Запись ещё сохраняется. Повторите позже.": {
    "en": "Recording is still being saved. Try again later.",
    "uk": "Запис ще зберігається. Повторіть пізніше."
  },
  "Записи уже удалены или не найдены.": {
    "en": "Recordings already deleted or not found.",
    "uk": "Записи вже видалено або не знайдено."
  },
  "Подтверждение устарело. Откройте удаление ещё раз.": {
    "en": "Confirmation expired. Open the deletion dialog again.",
    "uk": "Підтвердження застаріло. Відкрийте видалення ще раз."
  },
  "Список записей изменился. Проверьте новое подтверждение.": {
    "en": "The recording list changed. Review the new confirmation.",
    "uk": "Список записів змінився. Перевірте нове підтвердження."
  },
  "Очистка недоступна: установите RNNoise для Windows": {
    "en": "Cleanup unavailable: install RNNoise for Windows",
    "uk": "Очищення недоступне: установіть RNNoise для Windows"
  },
  "RNNoise: контрольная сумма библиотеки не совпала": {
    "en": "RNNoise: library checksum mismatch",
    "uk": "RNNoise: контрольна сума бібліотеки не збігається"
  },
  "Для очистки выберите разговор до 10 минут": {
    "en": "Select a conversation up to 10 minutes long for cleanup",
    "uk": "Для очищення виберіть розмову до 10 хвилин"
  },
  "Уже очищается другая запись. Попробуйте после её завершения": {
    "en": "Another recording is being cleaned. Try again when it finishes",
    "uk": "Інший запис уже очищується. Спробуйте після завершення"
  },
  "Сначала дождитесь завершения записи": {
    "en": "Wait for recording to finish first",
    "uk": "Спочатку дочекайтеся завершення запису"
  },
  "Сохранена незавершённая копия; исходник доступен для прослушивания": {
    "en": "An incomplete copy was saved; the original is available to play",
    "uk": "Збережено незавершену копію; оригінал доступний для прослуховування"
  },
  "Не удалось очистить запись; оригинал сохранён": {
    "en": "Could not clean the recording; the original is preserved",
    "uk": "Не вдалося очистити запис; оригінал збережено"
  },
  "Waiting for a live frame": {
    "en": "Waiting for a live frame",
    "uk": "Очікуємо поточний кадр",
    "ru": "Ожидаем текущий кадр"
  },
  "Recording is not available": {
    "en": "Recording is not available",
    "uk": "Запис недоступний",
    "ru": "Запись недоступна"
  },
  "Invalid recording": {
    "en": "Invalid recording",
    "uk": "Некоректний запис",
    "ru": "Некорректная запись"
  },
  "Recording file is missing": {
    "en": "Recording file is missing",
    "uk": "Файл запису відсутній",
    "ru": "Файл записи отсутствует"
  },
  "Conversation not found": {
    "en": "Conversation not found",
    "uk": "Розмову не знайдено",
    "ru": "Разговор не найден"
  },
  "Invalid conversation": {
    "en": "Invalid conversation",
    "uk": "Некоректна розмова",
    "ru": "Некорректный разговор"
  },
  "Conversation part is missing": {
    "en": "Conversation part is missing",
    "uk": "Частина розмови відсутня",
    "ru": "Часть разговора отсутствует"
  },
  "Invalid WAV part": {
    "en": "Invalid WAV part",
    "uk": "Некоректна частина WAV",
    "ru": "Некорректная часть WAV"
  },
  "Incomplete WAV part": {
    "en": "Incomplete WAV part",
    "uk": "Незавершена частина WAV",
    "ru": "Незавершённая часть WAV"
  },
  "No completed conversation parts yet": {
    "en": "No completed conversation parts yet",
    "uk": "Завершених частин розмови ще немає",
    "ru": "Завершённых частей разговора пока нет"
  },
  "Conversation exceeds WAV size limit; use individual parts": {
    "en": "Conversation exceeds WAV size limit; use individual parts",
    "uk": "Розмова перевищує обмеження WAV; використовуйте окремі частини",
    "ru": "Разговор превышает ограничение WAV; используйте отдельные части"
  },
  "Recording not found": {
    "en": "Recording not found",
    "uk": "Запис не знайдено",
    "ru": "Запись не найдена"
  },
  "Conversation is still being recorded": {
    "en": "Conversation is still being recorded",
    "uk": "Розмова ще записується",
    "ru": "Разговор ещё записывается"
  },
  "Archive quota reached; existing recordings were preserved": {
    "en": "Archive quota reached; existing recordings were preserved",
    "uk": "Досягнуто ліміту архіву; наявні записи збережено",
    "ru": "Достигнут лимит архива; существующие записи сохранены"
  },
  "Disk space low; recording stopped without deleting files": {
    "en": "Disk space low; recording stopped without deleting files",
    "uk": "Мало місця на диску; запис зупинено без видалення файлів",
    "ru": "Мало места на диске; запись остановлена без удаления файлов"
  },
  "Continuous IQ buffer overflow; audio has a gap": {
    "en": "Continuous IQ buffer overflow; audio has a gap",
    "uk": "Переповнення буфера IQ; у звуці є розрив",
    "ru": "Переполнение буфера IQ; в звуке есть разрыв"
  },
  "Metadata quota reached; stopped without deleting existing data": {
    "en": "Metadata quota reached; stopped without deleting existing data",
    "uk": "Досягнуто ліміту метаданих; зупинено без видалення даних",
    "ru": "Достигнут лимит метаданных; остановлено без удаления данных"
  },
  "RNNoise could not create state": {
    "en": "RNNoise could not create state",
    "uk": "RNNoise не вдалося ініціалізувати",
    "ru": "Не удалось инициализировать RNNoise"
  },
  "RNNoise returned invalid samples": {
    "en": "RNNoise returned invalid samples",
    "uk": "RNNoise повернув некоректні відліки",
    "ru": "RNNoise вернул некорректные отсчёты"
  },
  "Unsupported WAV format": {
    "en": "Unsupported WAV format",
    "uk": "Непідтримуваний формат WAV",
    "ru": "Неподдерживаемый формат WAV"
  },
  "Empty conversation": {
    "en": "Empty conversation",
    "uk": "Порожня розмова",
    "ru": "Пустой разговор"
  },
  "Диапазон должен быть шириной не менее 0.025 МГц": {
    "en": "A range must be at least 0.025 MHz wide",
    "uk": "Ширина діапазону має бути не меншою за 0.025 МГц"
  },
  "Частоты должны быть в пределах 1–6000 МГц": {
    "en": "Frequencies must be within 1–6000 MHz",
    "uk": "Частоти мають бути в межах 1–6000 МГц"
  }
};
