"""Game Night Launcher: one place to start any game from the Jackbox packs in this folder.

Scans sibling folders for pack installs, reads each pack's picker data for game names,
and opens the pack so the game can be picked from its own menu. Also manages the local
Jonahbox server and switches each pack between the local and official servers.

Games aren't launched with the engine's -launchTo option: it runs the game from its own
folder, so newer packs (e.g. Party Pack 9) can't find their jbg.config.jet and never
reach the server.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

try:
    from PIL import Image, ImageTk
except ImportError:  # icons are optional
    Image = ImageTk = None

ROOT = Path(__file__).resolve().parent
SERVER_DIR = ROOT / "jonahbox"
LOCAL_HOST = "192.168.0.202"
SKIP_DIRS = {"games", "jonahbox", "videos", "music", "sfx", "icons", "steam_settings", ".sentry-native", "Profile"}

BG = "#15131f"
SIDEBAR = "#1d1a2b"
CARD = "#29243d"
CARD_HOVER = "#332d4b"
TEXT = "#f2f0f8"
MUTED = "#a9a3c2"
ACCENT = "#ffcc33"
GREEN = "#3ddc84"
RED = "#ff5c6c"
FONT = "Segoe UI"

STRINGS = {
    "en": {
        "title_a": "GAME NIGHT", "title_b": " launcher",
        "checking": "Checking server…", "start_server": "Start server", "starting": "Starting server…",
        "online": "Local server online", "offline": "Local server offline",
        "join": "Players join at  https://{ip}",
        "library": "LIBRARY", "all_games": "All games",
        "no_packs": "No packs found next to\nthis launcher.",
        "open_menu": "Open pack menu",
        "server_local": "Server: Local  ⇄", "server_official": "Server: Official  ⇄",
        "switch_failed": "Couldn't switch servers",
        "no_match": "No games match.",
        "players": "{n} players", "play": "▶ Play",
        "not_running_title": "Server not running",
        "not_running_body": "{pack} is set to the local server, but it isn't running.\n\nStart the server first?",
        "already_title": "A game is already running", "already_body": "Launch another one anyway?",
        "launch_failed": "Couldn't launch", "server_missing": "Server not found",
        "pick_hint": "Opening {pack} — choose “{game}” from its menu.",
        "opening": "Opening {pack}…",
    },
}



# ---------- data ----------

def read_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def clean(text):
    text = re.sub(r"<br\s*/?>", " ", text or "")
    return re.sub(r"<[^>]+>", "", text).strip()


def find_child(folder, name):
    """Case-insensitive child lookup (pack data and folder names don't always match case)."""
    exact = folder / name
    if exact.exists():
        return exact
    if folder.is_dir():
        for child in folder.iterdir():
            if child.name.lower() == name.lower():
                return child
    return None


class Game:
    def __init__(self, pack, title, desc, players, standalone=False):
        self.pack = pack
        self.title = title
        self.desc = desc
        self.players = players
        self.standalone = standalone  # the pack is this one game, so there's no menu to pick from


class Pack:
    def __init__(self, folder, exe):
        self.folder = folder
        self.exe = folder / exe
        self.name = Path(exe).stem.replace("The Jackbox ", "")
        num = re.search(r"\d+", self.name)
        self.sort_key = (int(num.group()) if num else 999, self.name)
        self.icon = find_child(folder / "icons" / "win", "app.ico") if (folder / "icons").exists() else None
        self.games = self._load_games()

    def _load_games(self):
        picker = self.folder / "games" / "Picker"
        content = read_json(picker / "content.json")
        if not content:
            # Standalone titles (no picker) just launch straight in
            return [Game(self, self.name, "", "", standalone=True)]
        loc = (read_json(picker / "Localization.json") or {}).get("table", {}).get("en", {})
        entries = (content.get("games") or content.get("content") or []) if isinstance(content, dict) else content
        games = []
        for e in entries:
            if not e.get("enabled", True) or not e.get("mainSwf"):
                continue
            folder = find_child(self.folder / "games", e["name"])
            if not folder or not find_child(folder, e["mainSwf"]):
                continue
            players = e.get("players") or next(
                (i.get("value") for i in e.get("icons", []) if i.get("tag") == "PLAYERS"), "")
            desc = loc.get(e.get("description", "")) or loc.get(e.get("tagline", "")) or ""
            games.append(Game(self, clean(loc.get(e.get("menu", ""), e["name"])), clean(desc), players))
        return games

    # ----- server mode -----

    def configs(self):
        return [p for p in [self.folder / "jbg.config.jet", *self.folder.glob("games/*/jbg.config.jet")] if p.exists()]

    def is_local(self):
        try:
            return LOCAL_HOST in (self.folder / "jbg.config.jet").read_text(encoding="utf-8-sig")
        except OSError:
            return False

    def set_local(self, local):
        for cfg in self.configs():
            orig = cfg.with_name(cfg.name + ".orig")
            if not orig.exists():
                shutil.copyfile(cfg, orig)
            if not local:
                shutil.copyfile(orig, cfg)
                continue
            text = orig.read_text(encoding="utf-8-sig")
            text = re.sub(r'("serverUrl"\s*:\s*)"[^"]*"', rf'\1"{LOCAL_HOST}"', text)
            text = re.sub(r'("joinUrl"\s*:\s*)"[^"]*"', rf'\1"{LOCAL_HOST}"', text)
            cfg.write_text(text, encoding="utf-8")


def find_packs():
    packs = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        here = Path(dirpath)
        exes = [f for f in filenames if f.lower().startswith("the jackbox") and f.lower().endswith(".exe")]
        if exes and "games" in dirnames:
            packs.append(Pack(here, exes[0]))
            dirnames[:] = []
            continue
        depth = len(here.relative_to(ROOT).parts)
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS] if depth < 5 else []
    return sorted(packs, key=lambda p: p.sort_key)


def server_online():
    try:
        with socket.create_connection((LOCAL_HOST, 443), timeout=0.6):
            return True
    except OSError:
        return False


# ---------- UI ----------

class ScrollFrame(tk.Frame):
    def __init__(self, master, **kw):
        super().__init__(master, bg=BG, **kw)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        bar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))
        self.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))

    def scroll_top(self):
        self.canvas.yview_moveto(0)


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Game Night Launcher")
        self.geometry("1100x720")
        self.minsize(820, 520)
        self.configure(bg=BG)

        self.packs = find_packs()
        self.icons = {}
        self.procs = []
        self.online = False
        self.starting = False
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.render())

        self.build_ui(None)
        self._poll_server()

    def t(self, key, **fmt):
        return STRINGS["en"][key].format(**fmt)

    def f(self, size, weight="normal"):
        return (FONT, size, weight)

    def build_ui(self, current):
        for w in self.winfo_children():
            w.destroy()
        self.columns = 0
        self._build_header()
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)
        self._build_sidebar(body)
        main = tk.Frame(body, bg=BG)
        main.pack(side="left", fill="both", expand=True, padx=(0, 16), pady=(0, 16))
        self.pack_bar = tk.Frame(main, bg=BG)
        self.pack_bar.pack(fill="x", pady=(0, 10))
        self.scroll = ScrollFrame(main)
        self.scroll.pack(fill="both", expand=True)
        self.scroll.canvas.bind("<Configure>", self._on_resize, add="+")
        self.status = tk.Label(main, text="", font=self.f(10), fg=ACCENT, bg=BG, anchor="w")
        self.status.pack(fill="x", pady=(8, 0))
        self.show(current)
        self._set_online(self.online)

    # header: title, search, server status
    def _build_header(self):
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=16, pady=14)
        tk.Label(bar, text=self.t("title_a"), font=self.f(20, "bold"), fg=ACCENT, bg=BG).pack(side="left")
        tk.Label(bar, text=self.t("title_b"), font=self.f(20), fg=TEXT, bg=BG).pack(side="left")

        entry = tk.Entry(bar, textvariable=self.search, font=self.f(11), bg=CARD, fg=TEXT,
                         insertbackground=TEXT, relief="flat", width=26)
        entry.pack(side="left", padx=24, ipady=6)
        tk.Label(bar, text="🔍", bg=CARD, fg=MUTED, font=self.f(10)).place(in_=entry, relx=1.0, x=-24, rely=0.5, anchor="w")

        right = tk.Frame(bar, bg=BG)
        right.pack(side="right")
        self.server_dot = tk.Label(right, text="●", font=self.f(14), bg=BG, fg=MUTED)
        self.server_dot.pack(side="left")
        self.server_label = tk.Label(right, text=self.t("checking"), font=self.f(10), bg=BG, fg=MUTED)
        self.server_label.pack(side="left", padx=(4, 10))
        self.server_btn = self._button(right, self.t("start_server"), self.start_server)
        self.server_btn.pack(side="left")
        tk.Label(self, text=self.t("join", ip=LOCAL_HOST), font=self.f(10), fg=MUTED, bg=BG
                 ).pack(anchor="e", padx=18, pady=(0, 6))

    def _build_sidebar(self, body):
        side = tk.Frame(body, bg=SIDEBAR, width=220)
        side.pack(side="left", fill="y", padx=16, pady=(0, 16))
        side.pack_propagate(False)
        tk.Label(side, text=self.t("library"), font=self.f(9, "bold"), fg=MUTED, bg=SIDEBAR).pack(anchor="w", padx=14, pady=(14, 6))
        self.side_buttons = {}
        for pack in [None, *self.packs]:
            label = self.t("all_games") if pack is None else pack.name
            btn = tk.Label(side, text=label, image=self._icon(pack, 22), compound="left", anchor="w",
                           font=self.f(11), fg=TEXT, bg=SIDEBAR, padx=12, pady=7, cursor="hand2")
            btn.pack(fill="x")
            btn.bind("<Button-1>", lambda e, p=pack: self.show(p))
            self.side_buttons[pack] = btn
        if not self.packs:
            tk.Label(side, text=self.t("no_packs"), fg=MUTED, bg=SIDEBAR,
                     font=self.f(10), justify="left").pack(anchor="w", padx=14, pady=10)

    def _icon(self, pack, size):
        if pack is None or not pack.icon or Image is None:
            return ""
        key = (pack.folder, size)
        if key not in self.icons:
            try:
                img = Image.open(pack.icon)
                img = img.convert("RGBA").resize((size, size), Image.LANCZOS)
                self.icons[key] = ImageTk.PhotoImage(img)
            except Exception:
                self.icons[key] = ""
        return self.icons[key]

    def _button(self, parent, text, command, primary=False):
        bg, fg = (ACCENT, "#1a1626") if primary else (CARD, TEXT)
        btn = tk.Label(parent, text=text, font=self.f(10, "bold"), bg=bg, fg=fg, padx=14, pady=6, cursor="hand2")
        btn.bind("<Button-1>", lambda e: command())
        return btn

    # ----- views -----

    def show(self, pack):
        self.current = pack
        for p, btn in self.side_buttons.items():
            btn.configure(bg=CARD if p is pack else SIDEBAR, fg=ACCENT if p is pack else TEXT)
        for w in self.pack_bar.winfo_children():
            w.destroy()
        if pack is not None:
            tk.Label(self.pack_bar, text=pack.name, image=self._icon(pack, 36), compound="left", padx=10,
                     font=self.f(18, "bold"), fg=TEXT, bg=BG).pack(side="left")
            self._button(self.pack_bar, self.t("open_menu"), lambda: self.launch(pack)).pack(side="right")
            self.mode_btn = self._button(self.pack_bar, "", lambda: self.toggle_mode(pack))
            self.mode_btn.pack(side="right", padx=8)
            self._update_mode(pack)
        self.scroll.scroll_top()
        self.render()

    def _update_mode(self, pack):
        local = pack.is_local()
        self.mode_btn.configure(text=self.t("server_local") if local else self.t("server_official"),
                                fg=GREEN if local else ACCENT)

    def toggle_mode(self, pack):
        try:
            pack.set_local(not pack.is_local())
        except OSError as e:
            messagebox.showerror(self.t("switch_failed"), str(e))
        self._update_mode(pack)

    def _on_resize(self, event):
        cols = max(1, event.width // 330)
        if cols != self.columns:
            self.columns = cols
            self.render()

    def render(self):
        if not hasattr(self, "scroll"):
            return
        inner = self.scroll.inner
        for w in inner.winfo_children():
            w.destroy()
        query = self.search.get().strip().lower()
        packs = self.packs if self.current is None else [self.current]
        games = [g for p in packs for g in p.games
                 if not query or query in g.title.lower() or query in g.pack.name.lower()]
        cols = max(1, self.columns)
        for c in range(cols):
            inner.grid_columnconfigure(c, weight=1, uniform="col")
        for i, game in enumerate(games):
            self._card(inner, game).grid(row=i // cols, column=i % cols, sticky="nsew", padx=6, pady=6)
        if not games:
            tk.Label(inner, text=self.t("no_match"), fg=MUTED, bg=BG, font=self.f(12)).grid(pady=40)

    def _card(self, parent, game):
        card = tk.Frame(parent, bg=CARD, padx=16, pady=14, cursor="hand2")
        top = tk.Frame(card, bg=CARD)
        top.pack(fill="x")
        tk.Label(top, text=game.title, font=self.f(13, "bold"), fg=TEXT, bg=CARD, anchor="w",
                 wraplength=230, justify="left").pack(side="left", fill="x", expand=True)
        play = self._button(top, self.t("play"), lambda: self.launch(game.pack, game), primary=True)
        play.pack(side="right", anchor="n")
        meta = game.pack.name + (f"  ·  {self.t('players', n=game.players)}" if game.players else "")
        tk.Label(card, text=meta, font=self.f(9), fg=ACCENT, bg=CARD, anchor="w").pack(fill="x", pady=(2, 6))
        if game.desc:
            desc = game.desc if len(game.desc) < 170 else game.desc[:167].rstrip() + "…"
            tk.Label(card, text=desc, font=self.f(9), fg=MUTED, bg=CARD, anchor="w", justify="left",
                     wraplength=280).pack(fill="x")

        def hover(on):
            color = CARD_HOVER if on else CARD
            for w in [card, top, *card.winfo_children(), *top.winfo_children()]:
                if w is not play:
                    w.configure(bg=color)
        for w in [card, *card.winfo_children()]:
            w.bind("<Enter>", lambda e: hover(True))
            w.bind("<Leave>", lambda e: hover(False))
            w.bind("<Double-Button-1>", lambda e: self.launch(game.pack, game))
        return card

    # ----- actions -----

    def launch(self, pack, game=None):
        if pack.is_local() and not self.online:
            if messagebox.askyesno(self.t("not_running_title"), self.t("not_running_body", pack=pack.name)):
                self.start_server()
                return
        if any(p.poll() is None for p in self.procs):
            if not messagebox.askyesno(self.t("already_title"), self.t("already_body")):
                return
        try:
            self.procs.append(subprocess.Popen([str(pack.exe)], cwd=pack.folder))
        except OSError as e:
            messagebox.showerror(self.t("launch_failed"), str(e))
            return
        if game and not game.standalone:
            self.status.configure(text=self.t("pick_hint", pack=pack.name, game=game.title))
        else:
            self.status.configure(text=self.t("opening", pack=pack.name))

    def start_server(self):
        bat = SERVER_DIR / "start_server.bat"
        if not bat.exists():
            messagebox.showerror(self.t("server_missing"), str(bat))
            return
        os.startfile(bat)
        self.starting = True
        self.server_label.configure(text=self.t("starting"))

    def _poll_server(self):
        def check():
            ok = server_online()
            self.after(0, lambda: self._set_online(ok))
        threading.Thread(target=check, daemon=True).start()
        self.after(3000, self._poll_server)

    def _set_online(self, ok):
        self.online = ok
        if ok:
            self.starting = False
        self.server_dot.configure(fg=GREEN if ok else RED)
        if not self.starting:
            self.server_label.configure(text=self.t("online") if ok else self.t("offline"))
        if ok:
            self.server_btn.pack_forget()
        elif not self.server_btn.winfo_ismapped():
            self.server_btn.pack(side="left")


if __name__ == "__main__":
    Launcher().mainloop()
