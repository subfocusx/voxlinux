-- Vox — Hyprland 0.56 push-to-talk bindings (Lua config)
--
-- Append to ~/.config/hypr/bindings.lua. Hyprland 0.56 runs the Lua config,
-- so the old `bind = KEY, exec, ...` .conf syntax is not parsed — use `o.bind`.
--
-- The key is the X keysym for right Ctrl: `Right` (`RCTRL`/`RCTRC` are not
-- keysyms and are rejected). Vox itself records nothing here: the binds only
-- tell the systemd user service (voxlinux.service) to start/stop the
-- microphone via its unix socket, so the release direction matters and is
-- expressed with `release = true`.

local VOX = "vox-ptt"

-- Press: begin recording (Vox beeps).
o.bind("Right", "Vox: start recording", VOX .. " start")

-- Release: stop, transcribe and insert at the cursor.
o.bind("Right", "Vox: stop and insert", VOX .. " stop", { release = true })

-- Safety net: no press/release tracking needed. Every modifier gets its own
-- "+" in a Hyprland 0.56 key string: "SUPER SHIFT + D" is rejected as an
-- unknown keysym ("SUPER SHIFT"), "SUPER + SHIFT + D" is correct.
hl.unbind("SUPER + SHIFT + D")
o.bind("SUPER + SHIFT + D", "Vox: toggle", VOX .. " toggle")