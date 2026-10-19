# VoxLinux — диктовка в любой текстовый курсор

Офлайн-распознавание русской речи для **Wayland + Hyprland**: говорите — текст
появляется в активном окне. Порт [Vox](https://github.com/privatekey7/Vox)
(privatekey7) с Windows на Linux.

* **Полностью офлайн.** Модель по умолчанию — GigaAM v3 e2e RNN-T с нативной
  пунктуацией (`gigaam-v3-e2e-rnnt-punct`, архив ~162 МБ, распакованная
  ~224 МБ). Скачивается один
  раз и дальше работает локально, без сети и без облачного API. Другие
  варианты GigaAM v3 — в таблице «Models / Модели».
* **Push-to-talk, а не always-on.** Запись идёт только пока удерживается
  горячая клавиша.
* **Русский язык из коробки** с постобработкой: словарь терминов, чистка
  filler-слов, ITN (числительные прописью → цифрами), расстановка пробелов и
  знаков препинания, капитализация по контексту. У моделей с нативной
  пунктуацией шаг `add_punctuation` отключён, чтобы не портить их вывод.
* **Без Python-окна.** Живёт как systemd *user*-сервис, статус — через
  `notify-send` (трей опционален — `voxtray`).

---

## Как это работает

```
горячая клавиша ──► микрофон (16 кГц / моно / int16)
                          │
       (Silero VAD: сегменты ≤20 с, опционально) ──► sherpa-onnx ──► GigaAM v3 (CTC/RNN-T)
                                                                       │
                                                                  сырой текст
                                                                       │
       постобработка: terms → fillers → ITN → spacing →
                      punctuation (если модель без нативной) → capitalization
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
| `voxapp/registry.py` | каталог моделей (четыре варианта GigaAM v3) |
| `voxapp/downloader.py` | скачивание и распаковка модели |
| `voxapp/post_processor.py` и friends | постобработка текста |
| `scripts/vox-ptt` | CLI к control-сокету (его ставят в `~/.local/bin`) |
| `systemd/voxlinux.service` | unit пользовательского сервиса |
| `hyprland-bind.conf.example` | пример биндов (Lua и legacy `.conf`) |

---

## Model / Модель

По умолчанию используется **GigaAM v3 e2e RNN-T с нативной пунктуацией**
(`gigaam-v3-e2e-rnnt-punct`): NeMo-трансдьюсер, в котором пунктуация,
регистр и нормализация текста уже встроены в модель. Архив ~162 МБ,
распакованная ~224 МБ. Модель скачивается один раз и дальше работает
полностью офлайн, без сети и без облачного API.

Пунктуация и регистр у punct-моделей нативные, поэтому эвристический шаг
`add_punctuation` для них отключён (флаг `needs_punctuation=False`) — иначе
получаются артефакты вроде «…зеленый,.». rule-based ITN при этом всё
равно работает: модель не переводит «пять серверов» в «5 серверов».

Model-level hotwords у punct-моделей недоступны: sherpa-onnx требует
sentencepiece `bpe_vocab` для BPE-моделей и падает с SIGSEGV без него, а в
релизе такого словаря нет. Словарь терминов поэтому остаётся пост-обработкой
(`voxapp/terms.py`).

Производительность (измерено): RTF ~0.05 на современном 8-ядерном CPU,
~0.4–0.7 с от отпускания клавиши до вставки для диктовки 10 с.

### Models / Модели

| id | архитектура | нативная пунктуация | архив | когда использовать |
| --- | --- | --- | --- | --- |
| `gigaam-v3-e2e-rnnt-punct` (default) | NeMo transducer (RNN-T) | да | ~162 МБ | по умолчанию; лучший WER (11.2) и пунктуация |
| `gigaam-v3-e2e-ctc-punct` | NeMo CTC | да | ~155 МБ | та же пунктуация на скорости CTC (медленные CPU) |
| `gigaam-v3-rnnt-plain` | NeMo transducer (RNN-T) | нет (эвристики) | ~159 МБ | единственная char-level модель — только с ней работают model-level hotwords |
| `gigaam-v3` | NeMo CTC (legacy) | нет | ~155 МБ | fallback / откат |

### VAD / Сегментация длинных диктовок

Энкодер GigaAM v3 держит 5000 позиционных эмбеддингов (25 кадров/с), поэтому
одно декодирование ограничено ~200 с: 199 с ещё декодируется, 201 с падает в
ONNX Runtime с «5000 by 5500». Длинные диктовки режутся на сегменты речи
(≤20 с) до декодирования.

Для этого используется Silero VAD (`silero_vad.onnx`, ~640 КБ) в каталоге
моделей. Он опционален: без него приложение падает на фиксированные окна
по 30 с (границы могут резать слова, но крэша не будет).

Установка VAD-модели:

- автоматически при `./install.sh` (шаг «VAD model (Silero)»);
- пропустить: `./install.sh --no-vad`;
- вручную: положить `silero_vad.onnx` в `~/.local/share/voxlinux/models/`
  (URL — `VAD_MODEL_URL` в `voxapp/vad.py`).

### Переключение моделей / Switching models

Демон читает ключ `"model"` из `~/.local/share/voxlinux/config.json` и
перезагружает движок при его изменении — переустанавливать ничего не нужно.

- CLI лаунчера: `voxlinux --list-models` / `-l` и `voxlinux --model <id>` /
  `-m <id>` (или позиционный аргумент `<id>`).
- Установщик: `./install.sh --model=<id>` (скачает выбранную модель).
- Вручную: записать `"model": "<id>"` в `config.json` — демон подхватит при
  следующей диктовке.

Выбранная модель должна быть установлена (распакована в
`~/.local/share/voxlinux/models/`); иначе первое распознавание завершится
ошибкой.

## Бенчмарк

`scripts/bench_models.py` меряет модели на размеченном наборе (27 реплик из
Golos crowd validation + локальные сэмплы) и печатает WER/CER (сырые и
нормализованные) и RTF.

```bash
./.venv/bin/python scripts/bench_models.py eval/data --model gigaam-v3-e2e-rnnt-punct
./.venv/bin/python eval/fetch_dataset.py --check   # сверка датасета по SHA-256
```

Наш замер (2026-10-20): norm WER 5.06 % у e2e RNN-T punct, 8.23 % у e2e CTC
punct, 2.53 % у legacy plain CTC — то есть нативная пунктуация стоит ~2.5 п. п.
WER, а внутри punct-семейства RNN-T точнее CTC. Подробности, нормализация и
лицензия датасета — в `eval/RESULTS.md`.

---

## Требования

* Linux с **Wayland** (проверено на Hyprland 0.56, Lua-конфиг, Omarchy)
* Python **3.10+**
* Внешние утилиты: `wtype` (вставка текста), `notify-send` (статус),
  `paplay` (бипы), `hyprctl` (опрос состояния клавиш)
* Микрофон, доступный PipeWire/PulseAudio

Вставка текста идёт тремя путями: `wl-copy` + `wtype` (буфер обмена и
атомарная вставка, основной путь), прямой `wtype`, затем `ydotool` — последнему
нужен запущенный демон (`sudo ydotool daemon`), он же требует, чтобы сокет
лежал в `YDOOTOOL_SOCKET` или `/tmp/.ydotool_socket`.

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
4. скачивает модель по умолчанию GigaAM v3 e2e RNN-T punct (~162 МБ) и
   Silero VAD (~640 КБ) в `~/.local/share/voxlinux/models/`;
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
| `--model[=ID]` / `--no-model` | скачать модель (по умолчанию из реестра) или пропустить; `--model=<id>` — конкретный вариант |
| `--no-vad` | пропустить скачивание Silero VAD (опционально) |
| `--input-group` | `sudo usermod -aG input $USER` — хоткей без биндов |
| `--udev-rule PATH` | udev-правило `uaccess` для конкретной клавиатуры |
| `--skip-service` | не ставить systemd-юнит |
| `--uninstall` | снять лаунчеры, юнит и (по `--purge-model` / `--purge-vad`) модели |
| `-y` | не задавать вопросов |

---

## Сборка / Build

`build.sh` собирает релизные артефакты в `dist/`:

| артефакт | что это |
| --- | --- |
| `voxlinux-<версия>.src.tar.gz` | исходники (без `.venv`, `__pycache__` и `.wav`), с `SHA256SUMS` внутри |
| `voxlinux-<версия>-linux-<arch>/` | самодостаточный бандл PyInstaller: `voxlinux`, `vox-ptt`, `vox-transcribe`, `rec_overlay.py`, systemd-юниты, свой `install.sh` — **venv не нужен** |
| `SHA256SUMS` | контрольные суммы артефактов |
| `BUILD-INFO.txt` | версии (python, sherpa-onnx, onnxruntime, PyInstaller), git-коммит, модель и её SHA-256, размеры и суммы артефактов |

```bash
cd voxlinux
./build.sh                    # тесты → тарбол → бандл → BUILD-INFO
./build.sh --skip-tests       # без тестового гейта
./build.sh --no-pyinstaller   # только исходный тарбол
./build.sh --with-model       # положить установленную модель в бандл
```

Сборка **проваливается**, если не проходят юнит-тесты (гейт) или если
PyInstaller не собрал бандл. PyInstaller ставится в отдельный `.build-venv` и
в проектный venv не попадает.

Проверка артефактов:

```bash
cd dist && sha256sum -c SHA256SUMS
./voxlinux-<версия>-linux-<arch>/vox-transcribe ../sample_ru.wav   # frozen-рантайм
```

Модель в бандл **не** входит (это 222 МБ) — она ставится отдельно в
`~/.local/share/voxlinux/models/`. Бандловый `install.sh` ставит лаунчеры в
`~/.local/bin` и systemd-юнит, но не создаёт venv.

Лаунчеры бандла указывают на его абсолютный путь — **переносить распакованный
бандл нельзя**, иначе переустановите его (`./install.sh` внутри бандла).

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
| `vox-ptt history [N]` | последние N диктовок (по умолчанию 10) |
| `vox-ptt stats` | счётчики: всего диктовок, словарь, использование моделей |

История пишется в SQLite (`~/.local/share/voxlinux/vox_data.db`) после
каждой успешно вставленной реплики; ошибка записи никогда не ломает
диктовку.

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
| `~/.local/share/voxlinux/models/` | скачанные модели (~155–162 МБ на модель + Silero VAD ~640 КБ) |
| `~/.local/share/voxlinux/vox_data.db` | база (история диктовок) |
| `~/.local/share/voxlinux/config.json` | настройки, в т.ч. `hotkey` и `model` |
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
control-сокет), движок sherpa-onnx с GigaAM v3 (CTC/RNN-T, в т.ч. с нативной
пунктуацией), Silero VAD, скачивание моделей, вся
постобработка текста, установщик и systemd-юнит. Основной цикл воркера —
`voxapp/daemon.py` (запись → GigaAM → постобработка → вставка через wtype),
запускается как systemd user service `voxlinux`.

Релизные артефакты собираются `build.sh` в `dist/`: source-тарбол и
самодостаточный PyInstaller-бандл без venv (см. «Сборка / Build»).

План работ — `PLAN.md` (рядом с этим файлом).

---

## Лицензия

Порт распространяется на условиях оригинального проекта
[Vox](https://github.com/privatekey7/Vox) — см. `LICENSE` в upstream-копии.
Модель GigaAM v3 распространяется отдельно, на условиях sherpa-onnx.