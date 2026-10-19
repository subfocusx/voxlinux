# Порт Vox (privatekey7/Vox) на Linux — план

> **Обновлено 2026-10-20:** модель по умолчанию теперь — GigaAM v3 e2e RNN-T с нативной пунктуацией (`gigaam-v3-e2e-rnnt-punct`); актуальный план работ — `voxlinux/PLAN.md`.

База: `https://github.com/privatekey7/Vox` (Python, движок только GigaAM v3).
Цель: диктовка в микрофон → текст в курсор, офлайн, русский, Linux.

Окружение (факт, 2026-10-06): **Wayland + Hyprland**.

## Этап 1. Разведка
- [x] Склонировать Vox в `/mnt/data-archive/Code/Python/vox_am/upstream`
- [x] Разобрать win-зависимые модули: `tray.py`, хоткей (правый Ctrl), вставка текста, автозагрузка
- [ ] Разобрать переиспользуемое как есть: `engines.py`, `worker.py`, `post_processor.py`, `punctuation.py`, `capitalization.py`, `itn.py`, `downloader.py`, `config.py`
- [x] Определить окружение: **Wayland + Hyprland**

## Этап 2. Замена платформенного слоя (Wayland + Hyprland)
- [x] Глобальный хоткей: биндинг Hyprland (`bind = ... , exec`) + `evdev` как вариант удержания клавиши
- [ ] Вставка текста: `wtype` (первый выбор), fallback `ydotool` (нужен демон)
- [x] Статус: systemd user service + `notify-send`, трей опционально (waybar-модуль)
- [x] Автозапуск: systemd user service

## Этап 3. Движок GigaAM на Linux
- [x] Проверить запуск `engines.py` (GigaAM) под Linux: зависимости ONNX runtime, модель GigaAM v3 (CTC/RNN-T)
- [x] Заменить win-специфичные пути/звуки
- [x] Прогнать офлайн-транскрибацию тестового wav-файла

## Этап 4. Интеграция и проверка
- [x] Связка: хоткей → запись → GigaAM → постобработка → вставка в активное окно
- [x] Проверка на русском: пунктуация, капитализация, ITN (числительные)
- [x] Замер задержки (цель: <2 с на короткой фразе, CPU)
- [ ] Фичи из voica-win как ТЗ (опционально): история диктовок, словарь замен, оверлей-подсказка

## Этап 5. Упаковка
- [x] `install.sh` для Linux (зависимости: portaudio, onnxruntime, wtype, модели)
- [x] README с инструкцией
- [x] Удалить win-артефакты (`vox.iss`, `build.bat`, `.spec`) из рабочей копии

## Риски
- Wayland не даёт глобальных хоткеев/вставки без порталов → биндинг Hyprland + `wtype`, fallback `ydotool`
- GigaAM ONNX на слабом CPU может быть медленным → проверить int8-квантование
