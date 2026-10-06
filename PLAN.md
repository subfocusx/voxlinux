# Порт Vox (privatekey7/Vox) на Linux — план

База: `https://github.com/privatekey7/Vox` (Python, движок только GigaAM v3).
Цель: диктовка в микрофон → текст в курсор, офлайн, русский, Linux.

Окружение (факт, 2026-10-06): **Wayland + Hyprland**.

## Этап 1. Разведка
- [ ] Склонировать Vox в `/mnt/data-archive/Code/Python/vox_am/upstream`
- [ ] Разобрать win-зависимые модули: `tray.py`, хоткей (правый Ctrl), вставка текста, автозагрузка
- [ ] Разобрать переиспользуемое как есть: `engines.py`, `worker.py`, `post_processor.py`, `punctuation.py`, `capitalization.py`, `itn.py`, `downloader.py`, `config.py`
- [x] Определить окружение: **Wayland + Hyprland**

## Этап 2. Замена платформенного слоя (Wayland + Hyprland)
- [ ] Глобальный хоткей: биндинг Hyprland (`bind = ... , exec`) + `evdev` как вариант удержания клавиши
- [ ] Вставка текста: `wtype` (первый выбор), fallback `ydotool` (нужен демон)
- [ ] Статус: systemd user service + `notify-send`, трей опционально (waybar-модуль)
- [ ] Автозапуск: systemd user service

## Этап 3. Движок GigaAM на Linux
- [ ] Проверить запуск `engines.py` (GigaAM) под Linux: зависимости ONNX runtime, модель `gigaam-v3-e2e-ctc-fp32`
- [ ] Заменить win-специфичные пути/звуки
- [ ] Прогнать офлайн-транскрибацию тестового wav-файла

## Этап 4. Интеграция и проверка
- [ ] Связка: хоткей → запись → GigaAM → постобработка → вставка в активное окно
- [ ] Проверка на русском: пунктуация, капитализация, ITN (числительные)
- [ ] Замер задержки (цель: <2 с на короткой фразе, CPU)
- [ ] Фичи из voica-win как ТЗ (опционально): история диктовок, словарь замен, оверлей-подсказка

## Этап 5. Упаковка
- [ ] `install.sh` для Linux (зависимости: portaudio, onnxruntime, wtype, модели)
- [ ] README с инструкцией
- [ ] Удалить win-артефакты (`vox.iss`, `build.bat`, `.spec`) из рабочей копии

## Риски
- Wayland не даёт глобальных хоткеев/вставки без порталов → биндинг Hyprland + `wtype`, fallback `ydotool`
- GigaAM ONNX на слабом CPU может быть медленным → проверить int8-квантование
