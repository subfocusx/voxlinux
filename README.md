# VoxLinux

Offline Russian voice dictation for **Linux + Wayland + Hyprland**.
Push-to-talk → speech recognition → text appears in the active window.

Офлайн-диктовка русского текста в любой текстовый курсор: удерживаете
горячую клавишу, говорите — текст вставляется в активное окно.

## How it works / Как это работает

```
hotkey ──► microphone (16 kHz / mono / int16)
                │
           sherpa-onnx ──► GigaAM v3 ──► raw text
                                         │
           post-processing: terms → fillers → ITN → spacing →
                            punctuation → capitalization
                                         │
           wl-copy + wtype ──► text in the cursor
```

- **Model / Модель:** [GigaAM v3](https://huggingface.co/salute-developers/GigaAMv3)
  (NeMo CTC, Russian, ~163 MB, int8 ONNX) via `sherpa-onnx`. Downloads once,
  works fully offline. Скачивается один раз, дальше всё локально.
- **Push-to-talk, not always-on.** Recording only while the hotkey is held.
  Запись идёт только пока удерживается клавиша.
- **Insertion / Вставка:** clipboard (`wl-copy`) + atomic `Shift+Insert`
  paste via `wtype` — keeps focus in Chrome omnibox and single-line inputs.
- **Status:** systemd user services + tray icon (`voxtray`, AppIndicator),
  notifications via `notify-send`.
- **Russian post-processing / Постобработка:** term dictionary, filler cleanup,
  ITN (numerals → digits), spacing, punctuation, contextual capitalization.

## Requirements / Требования

Linux + Wayland (tested on Hyprland 0.56), Python 3.10+, `wtype`, `wl-copy`,
`notify-send`, `paplay`, `hyprctl`, microphone (PipeWire/PulseAudio).

## Install / Установка

```bash
cd voxlinux
./install.sh --check      # environment report first
./install.sh              # venv, launchers, units, model
```

Hotkey (Hyprland Lua, `~/.config/hypr/bindings.lua`):

```lua
require("vox-bindings")   -- Right-Alt toggle + Super+Shift+D spare
```

Services:

```bash
systemctl --user status voxlinux voxtray
```

## Layout

| Path | Purpose |
| --- | --- |
| `voxlinux/voxapp/daemon.py` | dictation loop: capture → STT → post → paste |
| `voxlinux/voxapp/platform_linux.py` | mic, hotkey, insertion, notifications, socket |
| `voxlinux/voxapp/engines.py` | sherpa-onnx backend |
| `voxlinux/voxapp/post_processor.py` + friends | Russian text post-processing |
| `voxlinux/scripts/vox-ptt` | socket CLI for Hyprland binds |
| `voxlinux/scripts/voxtray` | tray icon (status, model, restart, quit) |
| `voxlinux/systemd/` | `voxlinux.service`, `voxtray.service`, `.desktop` entries |
| `PLAN.md` | port plan (Russian) |

## License

Same terms as the upstream project [Vox](https://github.com/privatekey7/Vox)
(ported from Windows to Linux). GigaAM v3 model is distributed separately
under sherpa-onnx terms.
