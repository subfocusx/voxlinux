# VoxLinux — диктовка в любой текстовый курсор

Офлайн-распознавание русской речи для **Wayland + Hyprland**: говорите — текст
появляется в активном окне. Порт [Vox](https://github.com/privatekey7/Vox)
(privatekey7) с Windows на Linux.

* **Полностью офлайн.** Модель GigaAM v3 (neMo CTC, ~163 МБ) скачивается один
  раз и работает локально, без сети и без облачного API.
* **Push-to-talk, а не always-on.** Запись идёт только пока удерживается
  горячая клавиша.
* **Русский язык из коробки** с постобработкой: словарь терминов, чистка
  filler-слов, ITN (числительные прописью → цифрами), расстановка пробелов и
  знаков препинания, капитализация по контексту.
* **Без Python-окна и трея.** Живёт как systemd *user*-сервис, статус —
  через `notify-send`.

---

## Как это работает

```
горячая клавиша ──► микрофон (16 кГц / моно / int16)
                          │
                     sherpa-onnx ──► GigaAM v3 ──► сырой текст
                                                   │
                     постобработка: terms → fillers → ITN → spacing →
                                    punctuation → capitalization
                                                   │
                          wtype ──► текст в курсор активного окна
```

Запись, распознавание и вставка разделены: микрофон и сокет команд
принадлежат одному процессу (воркеру), а хоткей — это лёгкие `exec`-bind'ы
Hyprland, которые шлют ему команду по unix-сокету.

Ключевые файлы:

| Файл | Назначение |
| --- | --- |
| `voxapp/platform_linux.py` | микрофон, хоткей (evdev / опрос Hyprland), вставка текста, уведомления, бипы, control-сокет |
| `voxapp/engines.py` | бэкенд распознавания (sherpa-onnx) |
| `voxapp/registry.py` | каталог моделей (сейчас одна — GigaAM v3) |
| `voxapp/downloader.py` | скачивание и распаковка модели |
| `voxapp/post_processor.py` и friends | постобработка текста |
| `scripts/vox-ptt` | CLI к control-сокету (его ставят в `~/.local/bin`) |
| `systemd/voxlinux.service` | unit пользовательского сервиса |
| `hyprland-bind.conf.example` | пример биндов (Lua и legacy `.conf`) |

---

## Требования

* Linux с **Wayland** (проверено на Hyprland 0.56, Lua-конфиг, Omarchy)
* Python **3.10+**
* Внешние утилиты: `wtype` (вставка текста), `notify-send` (статус),
  `paplay` (бипы), `hyprctl` (опрос состояния клавиш)
* Микрофон, доступный PipeWire/PulseAudio

`./install.sh --check` проверяет всё это и печатает отчёт.

---

## Установка

```bash
cd voxlinux
./install.sh --check      # сначала посмотреть, чего не хватает
./install.sh              # установка (venv, лаунчеры, unit, модель)
```

Установщик:

1. создаёт `./.venv` и ставит туда `requirements.txt`
   (`sherpa-onnx`, `sounddevice`, `numpy`);
2. кладёт в `~/.local/bin` лаунчеры `vox-ptt` и `voxlinux`;
3. рендерит `systemd/voxlinux.service` в
   `~/.config/systemd/user/voxlinux.service` и включает сервис;
4. скачивает модель GigaAM v3 (~163 МБ) в
   `~/.local/share/voxlinux/models/`;
5. печатает готовый бинд для Hyprland.

Убедитесь, что `~/.local/bin` в `PATH`:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
```

### Ключи установщика

| Ключ | Что делает |
| --- | --- |
| `--check` | только отчёт об окружении, ничего не меняет |
| `--deps` | доустановить системные пакеты через `sudo` (pacman) |
| `--model` / `--no-model` | скачать / пропустить модель |
| `--input-group` | `sudo usermod -aG input $USER` — хоткей без биндов |
| `--udev-rule PATH` | udev-правило `uaccess` для конкретной клавиатуры |
| `--skip-service` | не ставить systemd-юнит |
| `--uninstall` | снять лаунчеры, юнит и (по `--purge-model`) модель |
| `-y` | не задавать вопросов |

---

## Хоткей

### Вариант 1 — бинды Hyprland (рекомендуется)

Не требует доступа к `/dev/input`, работает сразу. Добавьте в
`~/.config/hypr/bindings.lua` (Hyprland 0.56 использует Lua-конфиг, legacy
`bind =` в нём **не работает**):

```lua
-- push-to-talk на правом Ctrl: старт по нажатию, стоп по отпусканию
o.bind("Right",         "Vox: start",  "vox-ptt start")
o.bind("Right",         "Vox: stop",   "vox-ptt stop")

-- вариант в одну строку — сам отслеживает отпускание
o.bind("Right",         "Vox: talk",   "vox-ptt hold Right")

-- комбинация, не конфликтующая ни с чем
o.bind("SUPER SHIFT D", "Vox: toggle", "vox-ptt toggle")
```

```bash
hyprctl reload
```

`Right` — это keysym правого Ctrl в биндах Hyprland (`RCTRL`/`RCTRC`
компоновщик не примет).

Если у вас классический `.conf`, а не Lua, — есть готовый пример:
`hyprland-bind.conf.example`.

### Вариант 2 — без биндов, через evdev

Если пользователь состоит в группе `input` (или для клавиатуры есть udev-правило
`uaccess`), Vox читает `KEY_RCTRL` прямо с клавиатуры:

```bash
sudo usermod -aG input $USER    # затем перелогиниться
./install.sh --input-group
```

или точечно, без членства в группе:

```bash
./install.sh --udev-rule /dev/input/by-id/usb-...-event-kbd
```

Бинды в этом случае не нужны.

### Команды `vox-ptt`

| Команда | Действие |
| --- | --- |
| `vox-ptt start` | начать запись |
| `vox-ptt stop` | остановить → распознать → вставить |
| `vox-ptt toggle` | переключить запись |
| `vox-ptt hold Right` | запись, пока клавиша нажата (останавливается сам) |
| `vox-ptt ping` | проверить, что воркер жив |

---

## Запуск

```bash
systemctl --user status voxlinux        # состояние
systemctl --user restart voxlinux       # перезапустить после правок
journalctl --user -u voxlinux -f        # логи в реальном времени
systemctl --user disable --now voxlinux # выключить
```

Запуск вручную (для отладки):

```bash
./.venv/bin/python -m voxapp.platform_linux          # смоук-тест платформы
python scripts/test_transcribe.py sample_ru.wav       # офлайн-транскрибация
python scripts/test_platform.py                       # вставка текста + notify
```

### Диагностика платформы

`test_platform.py` печатает, что нашлось из внешних утилит, вводит маркер в
активное окно через `wtype` и шлёт уведомление. Если маркер появился — вставка
текста работает.

---

## Что где лежит

Всё — в XDG-каталогах, ничего не пишется в систему:

| Путь | Содержимое |
| --- | --- |
| `~/.local/share/voxlinux/models/` | скачанные модели (~163 МБ на модель) |
| `~/.local/share/voxlinux/vox_data.db` | база (история диктовок) |
| `~/.local/share/voxlinux/config.json` | настройки, в т.ч. `hotkey` |
| `~/.local/state/voxlinux/logs/` | логи |
| `$XDG_RUNTIME_DIR/voxlinux.sock` | control-сокет воркера |

Удаление:

```bash
./install.sh --uninstall              # лаунчеры + юнит
./install.sh --uninstall --purge-model   # + модель
rm -rf ~/.local/share/voxlinux       # + база и конфиг
```

---

Готово и проверено: платформенный слой (микрофон, хоткей, вставка, уведомления,
control-сокет), движок sherpa-onnx с GigaAM v3, скачивание модели, вся
постобработка текста, установщик и systemd-юнит. Основной цикл воркера —
`voxapp/daemon.py` (запись → GigaAM → постобработка → вставка через wtype),
запускается как systemd user service `voxlinux`.

План работ — `../PLAN.md`.

---

## Лицензия

Порт распространяется на условиях оригинального проекта
[Vox](https://github.com/privatekey7/Vox) — см. `LICENSE` в upstream-копии.
Модель GigaAM v3 распространяется отдельно, на условиях sherpa-onnx.