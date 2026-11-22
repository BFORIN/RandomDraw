"""随机抽签器（Tkinter 界面层）。

抽签规则与配置解析全部位于 draw_core.py，本文件只负责界面与交互。
"""

import os
import random
import shutil
import subprocess
import sys
import webbrowser

import tkinter as tk
import tkinter.font as tkfont
import tkinter.messagebox as messagebox
from tkinter import ttk

from draw_core import DrawEngine

# PIL 用于悬浮圆球超采样抗锯齿；不可用时回退为 Canvas 原生绘制
try:
    from PIL import Image, ImageDraw, ImageTk
    _HAS_PIL = True
except Exception:
    Image = ImageDraw = ImageTk = None
    _HAS_PIL = False

APP_TITLE = "随机抽签器"
STARTUP_HINT = "点击下方按钮开始抽签"
BG = "#eef2f7"
CARD_BG = "#ffffff"
ACCENT = "#1d4ed8"
TEXT = "#1f2937"
MUTED = "#6b7280"
BORDER = "#dde7f2"

# === 化学课特供版（长按悬浮窗开启）===
FANCY_HOLD_MS = 800            # 长按判定时长（毫秒）
FANCY_DRAG_THRESHOLD = 5       # 长按期间允许的最大移动像素（超过视为拖动）
FANCY_TITLE_SUFFIX = " · 化学课特供版"
FANCY_FLASH_MS = 500           # 终端启动日志闪现时长（越短越看不清）

# 抽签冷却：500ms，覆盖滚动动画(10 步 x 30ms)并留出余量
COOLDOWN_MS = 500

# 滚动动画参数：steps 为滚动次数，delay_ms 为每步间隔
ANIM_STEPS = 10
ANIM_DELAY_MS = 30

# 按钮点击区向外扩展的留白(px)：浅蓝底色不变，只是这块也能点
BUTTON_HIT_PAD = 8


# === 开机自启 ===

def get_autostart_path():
    """开机自启脚本路径；仅 Windows 支持，其他平台返回 None。"""
    if not sys.platform.startswith("win"):
        return None
    startup_dir = os.path.join(
        os.path.expanduser("~"),
        "AppData", "Roaming", "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
    )
    os.makedirs(startup_dir, exist_ok=True)
    return os.path.join(startup_dir, "random_draw.bat")


def is_autostart_enabled():
    autostart_path = get_autostart_path()
    return bool(autostart_path and os.path.exists(autostart_path))


def autostart_target():
    """开机自启脚本要拉起的程序路径。

    打包成单文件 exe 后 __file__ 指向临时解压目录，退出即被删除，
    此时必须直接指向 exe 自身，否则开机自启会静默失效。
    """
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(__file__)


def set_autostart(enabled):
    """写入/删除开机自启脚本，返回是否设置成功。"""
    autostart_path = get_autostart_path()
    if not autostart_path:
        return False
    if enabled:
        with open(autostart_path, "w", encoding="utf-8") as f:
            f.write(f'@echo off\n"{autostart_target()}"\n')
        return True
    if os.path.exists(autostart_path):
        os.remove(autostart_path)
    return True


def open_file_externally(path):
    """用系统默认程序打开文件。"""
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform.startswith("linux"):
        subprocess.run(["xdg-open", path], check=True)
    elif sys.platform.startswith("darwin"):
        subprocess.run(["open", path], check=True)


# === 化学课特供版：终端启动日志闪现 ===

# 假启动日志：**Arch systemd 风格**（绿 [  OK  ] / 红 [FAILED] / "Starting xxx..."），
# 但内容是 **Windows 日志**（Windows 服务/启动项），只求看起来真。
# 每项：("OK"|"FAIL"|"START"|"PLAIN", 行内容)
#   OK    -> 绿色 [  OK  ]  内容
#   FAIL  -> 红色 [FAILED] 内容
#   START -> 白色 "Starting 内容..."
#   PLAIN -> 原样输出（如横幅、Windows 版本行）
FAKE_BOOT_LOG = [
    ("PLAIN", "Microsoft Windows [Version 10.0.19045.4046]"),
    ("OK",    "Started Windows Event Log service"),
    ("OK",    "Started Plug and Play service"),
    ("OK",    "Started Power service"),
    ("OK",    "Started DCOM Server Process Launcher service"),
    ("START", "Windows Audio"),
    ("OK",    "Started Windows Audio service"),
    ("OK",    "Started Network Location Awareness service"),
    ("OK",    "Started DHCP Client service"),
    ("OK",    "Started DNS Client service"),
    ("OK",    "Started Windows Time service"),
    ("START", "Windows Update"),
    ("OK",    "Started Windows Update service"),
    ("OK",    "Started Windows Defender Antivirus service"),
    ("OK",    "Started Windows Firewall service"),
    ("START", "Print Spooler"),
    ("OK",    "Started Print Spooler service"),
    ("OK",    "Started Themes service"),
    ("OK",    "Started System Event Notification service"),
    ("OK",    "Started Security Accounts Manager service"),
    ("OK",    "Started Windows Management Instrumentation service"),
]


def flash_fancy_terminal():
    """弹出一个终端窗口，快速刷过一段"启动日志"后自动关闭（尽量看不清）。

    主界面不等待，Popen 立即返回；闪现失败也不影响界面。
    """
    try:
        if sys.platform.startswith("win"):
            _flash_terminal_windows()
        else:
            _flash_terminal_linux()
    except Exception:
        pass


def _flash_terminal_windows():
    """Windows：PowerShell 新开控制台，快速刷过一段假启动日志后自动关闭。

    日志行形如 [  OK  ] Started xxx / Starting xxx...（绿色/红色），纯英文，
    速度极快让人看不清。Windows 认 powershell.exe（系统自带），无需临时
    .bat；CREATE_NEW_CONSOLE 从 GUI 进程新建一个可见控制台窗口。
    """
    ps = (
        "$host.UI.RawUI.WindowTitle='Windows';"
        "function OK($m){Write-Host '  [  OK  ] ' -ForegroundColor Green -NoNewline;"
        "Write-Host $m};"
        "function FAIL($m){Write-Host '  [FAILED] ' -ForegroundColor Red -NoNewline;"
        "Write-Host $m};"
        "function ST($m){Write-Host \"Starting $m...\"};"
        + "".join(
            (
                f"OK('{msg}');" if kind == "OK"
                else f"FAIL('{msg}');" if kind == "FAIL"
                else f"ST('{msg}');" if kind == "START"
                else f"Write-Host '{msg}';"
            )
            for kind, msg in FAKE_BOOT_LOG
        )
        + f"Start-Sleep -Milliseconds {FANCY_FLASH_MS}"
    )
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
        creationflags=flags,
    )


def _flash_terminal_linux():
    """Linux：找可用的终端模拟器刷过一段"启动日志"；找不到则静默。"""
    bash_script = (
        "".join(
            (
                f"echo -e '  \\033[32m[  OK  ]\\033[0m {msg}';" if kind == "OK"
                else f"echo -e '  \\033[31m[FAILED]\\033[0m {msg}';" if kind == "FAIL"
                else f"echo 'Starting {msg}...';" if kind == "START"
                else f"echo '{msg}';"
            )
            for kind, msg in FAKE_BOOT_LOG
        )
        + f"sleep {FANCY_FLASH_MS/1000}"
    )
    for term, needs_ddash in (
        ("xterm", False), ("foot", False), ("alacritty", False), ("kitty", False),
        ("gnome-terminal", True), ("konsole", True), ("xfce4-terminal", True),
    ):
        exe = shutil.which(term)
        if not exe:
            continue
        if needs_ddash:
            subprocess.Popen([exe, "--", "bash", "-c", bash_script])
        else:
            subprocess.Popen([exe, "-e", "bash", "-c", bash_script])
        return


# === 高 DPI 感知 ===

def enable_dpi_awareness():
    """启用 Windows 进程级高 DPI 感知，让 Tk 按原生分辨率渲染。

    高分屏下若未声明 DPI 感知，Windows 会把程序当作低 DPI 应用，
    把整个窗口位图拉伸到物理分辨率，文字/控件边缘变成马赛克。
    这里用 shcore 的 PROCESS_PER_MONITOR_DPI_AWARE(2)，比旧版
    user32.SetProcessDPIAware() 更符合现代多屏缩放。非 Windows 或
    调用失败时静默——Tk 本身跨平台自适应，无需干预。
    """
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _hex_to_rgba(hex_color, alpha=255):
    """把 '#rrggbb' 转成 PIL 需要的 (r, g, b, a) 元组。"""
    hex_color = hex_color.lstrip("#")
    return (int(hex_color[0:2], 16), int(hex_color[2:4], 16),
            int(hex_color[4:6], 16), alpha)


class DrawApp:
    """主窗口与悬浮窗的持有者，集中管理界面状态与交互。"""

    def __init__(self):
        # 必须在 Tk 实例化之前启用 DPI 感知，否则本次运行的分辨率已按低 DPI 决定
        enable_dpi_awareness()

        self.engine = DrawEngine()
        self.floating_window = None
        self._animation_id = None
        self._cooldown_id = None
        self._float_circle_photo = None  # PIL 超采样位图（无 PIL 时保持 None）

        # 化学课特供版状态（仅内存态，不持久化；关闭窗口后自动恢复正常版）
        self.fancy_active = False
        self.fancy_lucky = None       # 用户输入的幸运数字；开启后只抽到这个
        self._fancy_hold_after = None
        self._fancy_input_after = None  # 终端闪现结束后再弹输入框的延迟回调
        self._fancy_pressed = False
        self._fancy_press_pos = None
        self._lucky_input_var = None    # 数字小键盘输入值（存实例防 GC）

        self.root = tk.Tk()
        self.root.title(APP_TITLE)

        self._build_window()
        self._build_menu()
        self._build_result_panel()
        self._build_controls()
        self._fit_height_to_content()

        self.root.protocol("WM_DELETE_WINDOW", self.minimize_to_floating)
        self.engine.reset_pool()
        self.update_remaining()

    def run(self):
        self.root.mainloop()

    # ---------- 界面搭建 ----------

    def _build_window(self):
        root = self.root
        root.configure(bg=BG)

        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        # 窗口大小跟随 1/2 逻辑分辨率：宽高都占屏幕一半
        self.window_w = max(320, screen_w // 2)
        self.window_h = max(240, screen_h // 2)
        root.resizable(False, False)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.98)

        # 使用系统默认字体，避免跨平台字体缺失
        self.default_family = tkfont.nametofont("TkDefaultFont").actual("family")
        # 结果行用等宽字体：抽签动画数字补零后宽度恒定，不左右晃
        self.mono_family = tkfont.nametofont("TkFixedFont").actual("family")

        # 字体大小跟随窗口：以 560 宽为基准 scale=1，窗口越大字体越大（夹 1.0~2.0）
        self.ui_scale = min(2.0, max(1.0, self.window_w / 560))

        # 关于/免责声明等窗口沿用 clam 主题
        ttk.Style(root).theme_use("clam")

    def _fsize(self, base):
        """按 UI 缩放系数换算字体大小（字体跟随窗口）。"""
        return max(8, int(base * self.ui_scale))

    def _fit_height_to_content(self):
        """按 1/2 逻辑分辨率固定窗口尺寸（宽高都占屏幕一半）并居中。"""
        root = self.root
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        window_w, window_h = self.window_w, self.window_h
        root.geometry(
            f"{window_w}x{window_h}"
            f"+{max(0, (screen_w - window_w) // 2)}"
            f"+{max(0, (screen_h - window_h) // 2)}"
        )

    def _build_menu(self):
        menubar = tk.Menu(self.root, bg=CARD_BG, fg=TEXT)
        help_menu = tk.Menu(menubar, tearoff=0, bg=CARD_BG, fg=TEXT)
        help_menu.add_command(label="编辑配置文件", command=self.open_config_file)
        help_menu.add_command(label="关于", command=self.show_about)
        help_menu.add_command(label="免责声明", command=self.show_disclaimer)
        help_menu.add_separator()
        self.autostart_var = tk.BooleanVar(value=is_autostart_enabled())
        help_menu.add_checkbutton(label="开机自启", variable=self.autostart_var, command=self.toggle_autostart)
        help_menu.add_command(label="🧪 化学课特供版（长按悬浮窗）", command=self.enter_fancy_mode)
        help_menu.add_command(label="恢复正常版", command=self._exit_fancy_mode)
        help_menu.add_command(label="停止进程", command=self.stop_process)
        menubar.add_cascade(label="更多", menu=help_menu)
        self.root.config(menu=menubar)

    def _build_result_panel(self):
        panel = tk.Frame(
            self.root,
            bg=CARD_BG,
            highlightbackground=BORDER,
            highlightthickness=1,
            padx=int(18 * self.ui_scale),
            pady=int(18 * self.ui_scale),
            bd=0,
        )
        # 卡片撑满半屏窗口（fill both + expand），内容垂直居中
        panel.pack(
            fill="both", expand=True,
            padx=int(18 * self.ui_scale), pady=(int(12 * self.ui_scale), int(10 * self.ui_scale)),
        )

        self.result_var = tk.StringVar(value=STARTUP_HINT)
        self._result_label = tk.Label(
            panel,
            textvariable=self.result_var,
            bg=CARD_BG,
            fg=TEXT,
            font=(self.mono_family, self._fsize(17), "bold"),
            justify="center",
            wraplength=max(260, self.window_w - 100),
            height=2,           # 固定占两行：切换文字时结果行高度不跳动
            bd=0,
        )
        self._result_label.pack(fill="both", expand=True, pady=(0, int(12 * self.ui_scale)))

        # 剩余数字显示
        self.remaining_str = tk.StringVar()
        tk.Label(
            panel,
            textvariable=self.remaining_str,
            bg=CARD_BG,
            fg=MUTED,
            font=(self.default_family, self._fsize(10)),
            wraplength=max(260, self.window_w - 120),
            justify="center",
            bd=0,
        ).pack(fill="x", pady=(0, int(10 * self.ui_scale)))

    def _build_controls(self):
        btn_frame = tk.Frame(self.root, bg=BG, bd=0)
        btn_frame.pack(side="bottom", pady=(0, int(18 * self.ui_scale)))
        self.btn_draw = self._make_button(btn_frame, "🎲 抽签", self.generate)
        self.btn_reset = self._make_button(btn_frame, "🔄 重置", self.reset_pool)

    def _make_button(self, parent, text, command, bg="#edf4ff", active_bg="#dfeeff"):
        """创建一个白板风格的扁平按钮。

        视觉仍是原来那块浅蓝底色，但真实点击区向外扩展一圈
        (wrapper 透明、内边距留白)，点边缘也不会落空。
        """
        s = self.ui_scale
        wrapper = tk.Frame(parent, bg=BG)
        wrapper.pack(side="left", padx=int(8 * s), pady=int(6 * s))

        button = tk.Button(
            wrapper,
            text=text,
            command=command,
            bg=bg,
            fg=ACCENT,
            activebackground=active_bg,
            activeforeground=ACCENT,
            borderwidth=0,
            highlightthickness=0,
            relief="flat",
            padx=int(18 * s),
            pady=int(8 * s),
            width=15,
            height=2,
            cursor="hand2",
            font=(self.default_family, self._fsize(10), "bold"),
        )
        button.pack(padx=BUTTON_HIT_PAD, pady=BUTTON_HIT_PAD)
        button.hit_wrapper = wrapper

        # 让 wrapper 的留白区域也能点击：按下时转发给按钮
        def forward_click(event, target=button):
            target.invoke()

        for widget in (wrapper, button):
            widget.bind("<Button-1>", forward_click)
            widget.bind("<ButtonRelease-1>", lambda e: None)
            widget.configure(cursor="hand2")
        return button

    # ---------- 抽签交互 ----------

    def generate(self):
        """抽一个数字并播放滚动动画，冷却期内不接受新请求。"""
        if self._cooldown_id is not None:
            return

        # 化学课特供版：开启且已选幸运数字时，只抽这个数字
        if self.fancy_active and self.fancy_lucky is not None:
            self.animate_result(self.fancy_lucky)
            self.update_remaining()
            self._start_cooldown()
            return

        num = self.engine.draw()
        if num is None:
            # 池已抽完，先停掉残留动画，否则它会在稍后把提示覆盖成滚动结果
            self._cancel_animation()
            self.result_var.set(self.engine.last_error)
            self.update_remaining()
            return

        self.animate_result(num)
        self.update_remaining()
        self._start_cooldown()

    def _start_cooldown(self):
        """抽完后进入冷却，避免连点刷屏。

        冷却时长覆盖滚动动画，让动画播完前按钮不会再次响应。
        """
        self._set_buttons_enabled(False)
        self._cooldown_id = self.root.after(COOLDOWN_MS, self._end_cooldown)

    def _end_cooldown(self):
        """冷却结束，恢复按钮。"""
        self._cooldown_id = None
        self._set_buttons_enabled(True)

    def _set_buttons_enabled(self, enabled):
        """统一切换按钮可用状态（含外扩的点击留白区）。"""
        state = "normal" if enabled else "disabled"
        for button in (self.btn_draw, self.btn_reset):
            button.configure(state=state)
            wrapper = getattr(button, "hit_wrapper", None)
            if wrapper is not None:
                if enabled:
                    wrapper.bind("<Button-1>",
                                 lambda e, t=button: t.invoke())
                    wrapper.configure(cursor="hand2")
                else:
                    wrapper.unbind("<Button-1>")
                    wrapper.configure(cursor="arrow")

    def _cancel_animation(self):
        """取消正在播放的滚动动画。"""
        if self._animation_id is not None:
            self.root.after_cancel(self._animation_id)
            self._animation_id = None

    def reset_pool(self, forget_history=False):
        """手动重置数字池。

        forget_history=True 时一并清空累计抽签次数，用于彻底重新开始。
        """
        self.engine.reload()
        self.engine.reset_pool(forget_history=forget_history)
        # 同 generate：提示前先停掉动画，避免被残留滚动结果覆盖
        self._cancel_animation()
        self._end_cooldown()
        # 重置后提示统一显示「刚打开窗口时的那段文字」
        self.result_var.set(STARTUP_HINT)
        self.update_remaining()

    def update_remaining(self):
        """更新剩余数字显示（化学课特供版界面与标准版一致）。"""
        self.remaining_str.set(f"随机池剩余: {len(self.engine.remaining_pool)}")

    def animate_result(self, final_num, steps=ANIM_STEPS, delay_ms=ANIM_DELAY_MS):
        """让结果在极短时间内快速滚动后停在最终值。

        滚动值取自候选池，与最终结果无关，仅为视觉效果。
        数字补零到候选最大位数（等宽字体下宽度恒定），动画期间不左右晃。
        """
        self._cancel_animation()

        candidates = self.engine.config.candidates() or [final_num]
        # 候选最大绝对值位数：如 pool_max=54 → 2 位，数字显示为 01~54
        width = max(len(str(abs(v))) for v in candidates)

        def fmt(num):
            if num < 0:
                return f"-{abs(num):0{width}d}"
            return f"{num:0{width}d}"

        seq = [random.choice(candidates) for _ in range(steps)]
        seq.append(final_num)

        def tick(index):
            if index >= len(seq):
                self.result_var.set(f"输出结果: {fmt(final_num)}")
                self._animation_id = None
                return
            self.result_var.set(f"输出结果: {fmt(seq[index])}")
            self._animation_id = self.root.after(delay_ms, tick, index + 1)

        tick(0)

    # ---------- 窗口与菜单 ----------

    def minimize_to_floating(self):
        """最小化到悬浮窗，不退出程序（进程持久化）。

        若处于化学课特供版，先自动回退到标准版（标题还原、抽签正常），
        再最小化到悬浮球，进程继续运行。
        """
        if self.fancy_active:
            self._exit_fancy_mode()
        if self.floating_window is not None and self.floating_window.winfo_exists():
            self.floating_window.deiconify()
        else:
            self.show_floating_window()
        self.root.withdraw()

    def restore_main_window(self):
        """从悬浮窗恢复主窗口。"""
        if self.floating_window is not None and self.floating_window.winfo_exists():
            self.floating_window.withdraw()
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.focus_force()

    def show_floating_window(self):
        """显示圆形悬浮小窗，支持拖动与双击恢复主窗口，并随分辨率自适应。"""
        if self.floating_window is not None and self.floating_window.winfo_exists():
            self.floating_window.deiconify()
            return

        win = tk.Toplevel(self.root)
        win.title(APP_TITLE)
        self.floating_window = win

        screen_min = min(self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        float_size = max(72, min(110, int(screen_min * 0.072)))

        transparent_color = BG
        win.configure(bg=transparent_color)
        # Windows 用 override-redirect + 透明色实现无边框圆形悬浮球。
        # Wayland 合成器（含 niri）不支持客户端请求浮动窗口，override-redirect
        # 窗口也会被平铺，所以非 Windows 下退化为带标题栏的小窗，
        # 功能（拖动、双击恢复、置顶）不受影响。
        if sys.platform.startswith("win"):
            win.overrideredirect(True)
            win.attributes("-transparentcolor", transparent_color)
        win.attributes("-topmost", True)

        win.geometry(f"{float_size}x{float_size}")

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        # 按屏幕定位而非主窗口：主窗口被拖动后，悬浮球不该跟着乱跑
        pos_x = max(0, screen_w - float_size - 18)
        pos_y = max(0, min(screen_h - float_size, int(screen_h * 0.6 - float_size / 2)))
        win.geometry(f"+{pos_x}+{pos_y}")

        circle = tk.Canvas(
            win,
            width=float_size,
            height=float_size,
            bg=transparent_color,
            highlightthickness=0,
            bd=0,
        )
        circle.pack()
        if _HAS_PIL:
            # 位图绘制：PIL 4x 超采样渲染圆球再缩回，圆边抗锯齿（文字仍由 Tk 清晰绘制）
            photo = self._render_float_circle_image(float_size)
            circle.create_image(float_size / 2, float_size / 2, image=photo)
            self._float_circle_photo = photo  # 必须持有引用，否则被 GC 回收后图片消失
        else:
            # 回退：Canvas 原生绘制（无 PIL 环境）
            circle.create_oval(5, 5, float_size - 5, float_size - 5, fill=CARD_BG, outline="#dfe7f0", width=2)
            circle.create_oval(
                int(float_size * 0.24), int(float_size * 0.24),
                int(float_size * 0.76), int(float_size * 0.76),
                fill="#f2f7ff", outline="#dbeaff", width=1,
            )
        circle.create_text(
            float_size / 2, float_size / 2, text="抽",
            fill="#4b5563",
            font=(self.default_family, max(11, int(float_size * 0.18)), "bold"),
        )

        circle.bind("<ButtonPress-1>", self._on_float_press)
        circle.bind("<B1-Motion>", self._on_float_motion)
        circle.bind("<ButtonRelease-1>", self._on_float_release)
        circle.bind("<Double-Button-1>", self._on_float_double)
        circle.bind("<Button-3>", self._on_float_right)  # 右键悬浮窗打开特供版
        win.protocol("WM_DELETE_WINDOW", self.close_app)
        self._refresh_fancy_visual()

    def _render_float_circle_image(self, size):
        """用 PIL 超采样绘制圆形悬浮球位图。

        以 4 倍尺寸在 RGBA 画布上画出外圆(白底浅描边)与内圆(浅蓝)，
        再用 LANCZOS 缩回目标尺寸，圆边获得平滑抗锯齿；画布其余部分
        为全透明，由 Canvas 背景色填充。返回 ImageTk.PhotoImage，调用
        方须持有引用直到窗口关闭。
        """
        ss = 4  # 超采样倍率：越高圆边越平滑，4x 在 72~110px 圆球上已足够
        big = size * ss
        img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # 外圆：白底 + 浅灰描边（对应原 create_oval width=2）
        d.ellipse(
            [5 * ss, 5 * ss, (size - 5) * ss, (size - 5) * ss],
            fill=_hex_to_rgba(CARD_BG), outline=_hex_to_rgba("#dfe7f0"), width=2 * ss,
        )
        # 内圆：浅蓝底 + 浅蓝描边（对应原 0.24~0.76 width=1）
        d.ellipse(
            [size * 0.24 * ss, size * 0.24 * ss,
             size * 0.76 * ss, size * 0.76 * ss],
            fill=_hex_to_rgba("#f2f7ff"), outline=_hex_to_rgba("#dbeaff"), width=1 * ss,
        )
        img = img.resize((size, size), Image.LANCZOS)
        return ImageTk.PhotoImage(img)

    # ---------- 化学课特供版：长按悬浮窗开启 ----------

    def _on_float_press(self, event):
        """按下悬浮窗：启动长按计时，同时记录拖动起点。"""
        win = self.floating_window
        self._fancy_pressed = True
        self._fancy_press_pos = (event.x_root, event.y_root)
        if win is not None:
            win._drag_start = (event.x_root - win.winfo_x(), event.y_root - win.winfo_y())
        self._cancel_fancy_hold()
        self._fancy_hold_after = self.root.after(FANCY_HOLD_MS, self._on_fancy_hold)

    def _on_float_motion(self, event):
        """移动超过阈值视为拖动，取消长按；否则继续拖动窗口。"""
        if self._fancy_pressed and self._fancy_press_pos is not None:
            dx = abs(event.x_root - self._fancy_press_pos[0])
            dy = abs(event.y_root - self._fancy_press_pos[1])
            if max(dx, dy) > FANCY_DRAG_THRESHOLD:
                self._cancel_fancy_hold()
        win = self.floating_window
        if win is not None:
            start = getattr(win, "_drag_start", None)
            if start:
                win.geometry(f"+{event.x_root - start[0]}+{event.y_root - start[1]}")

    def _on_float_release(self, _event):
        """松开悬浮窗：结束拖动并取消长按计时。"""
        self._fancy_pressed = False
        self._fancy_press_pos = None
        self._cancel_fancy_hold()
        win = self.floating_window
        if win is not None:
            win._drag_start = None

    def _on_float_double(self, _event):
        self.restore_main_window()

    def _on_float_right(self, _event):
        """右键悬浮窗：直接打开化学课特供版（同长按触发）。"""
        self.enter_fancy_mode()

    def _cancel_fancy_hold(self):
        if self._fancy_hold_after is not None:
            self.root.after_cancel(self._fancy_hold_after)
            self._fancy_hold_after = None

    def _on_fancy_hold(self):
        """长按达到阈值：开启（或重选）化学课特供版。"""
        self._fancy_hold_after = None
        self.enter_fancy_mode()

    def enter_fancy_mode(self):
        """长按悬浮窗触发：先闪现乱码终端（快、看不清、自动关闭），结束后再弹输入框。

        完整流程：闪现终端 → 标题加后缀 → （终端关闭后）弹幸运数字输入框。
        无论是否已开启，每次长按都重新走完整流程（可重选幸运数字）。
        """
        flash_fancy_terminal()
        self.fancy_active = True
        self._apply_fancy_title()
        # 等终端闪现结束（约 0.28s + 关闭余量）后再弹输入框，符合"先终端后输入框"
        self._cancel_fancy_input_delay()
        self._fancy_input_after = self.root.after(
            FANCY_FLASH_MS + 220, self._ask_lucky_number
        )

    def _cancel_fancy_input_delay(self):
        """取消挂起的输入框延迟回调（关闭花哨版/清理时调用）。"""
        if self._fancy_input_after is not None:
            self.root.after_cancel(self._fancy_input_after)
            self._fancy_input_after = None

    def _exit_fancy_mode(self):
        """关闭化学课特供版，恢复正常版。"""
        self.fancy_active = False
        self.fancy_lucky = None
        self._cancel_fancy_hold()
        self._cancel_fancy_input_delay()
        self._apply_fancy_title()
        self.result_var.set(STARTUP_HINT)
        self.update_remaining()

    def _apply_fancy_title(self):
        """根据状态给主窗口/悬浮窗标题加后缀。"""
        suffix = FANCY_TITLE_SUFFIX if self.fancy_active else ""
        title = APP_TITLE + suffix
        self.root.title(title)
        if self.floating_window is not None and self.floating_window.winfo_exists():
            self.floating_window.title(title)

    def _refresh_fancy_visual(self):
        """化学课特供版外观只体现在标题上（其余界面与标准版一致）。"""
        self._apply_fancy_title()

    def _ask_lucky_number(self):
        """弹出幸运数字输入框（屏幕居中 + 数字小键盘），输入框初始为空。"""
        candidates = self.engine.config.candidates()
        if not candidates:
            messagebox.showerror("化学课特供版", "候选数字为空，无法选择幸运数字")
            self._exit_fancy_mode()
            return

        master = self.floating_window
        if master is None or not master.winfo_exists():
            master = self.root
        dlg = tk.Toplevel(master)
        dlg.title("🧪 化学课特供版 · 输入幸运数字")
        dlg.resizable(False, False)
        dlg.transient(master)
        self._grab_when_viewable(dlg)

        s = self.ui_scale  # 小键盘窗口大小/字体跟随主窗口 UI 缩放

        lo, hi = min(candidates), max(candidates)
        tk.Label(
            dlg,
            text="🧪 化学课特供版 · 输入幸运数字",
            font=(self.default_family, self._fsize(11)),
        ).pack(pady=(int(12 * s), int(2 * s)))
        tk.Label(
            dlg,
            text=f"有效范围 {lo}~{hi}（黑名单除外）",
            font=(self.default_family, self._fsize(9)),
            fg=MUTED,
        ).pack(pady=(0, int(4 * s)))

        # 输入显示区（StringVar 存实例防 GC）；初始为空，用户用数字小键盘点选
        self._lucky_input_var = tk.StringVar(value="")
        display = tk.Label(
            dlg,
            textvariable=self._lucky_input_var,
            font=(self.mono_family, self._fsize(20), "bold"),
            bg=CARD_BG,
            width=8,
            relief="sunken",
            bd=1,
        )
        display.pack(pady=(0, int(8 * s)))

        # 数字小键盘：0-9 点选输入 + 清空/删除（字体随窗口缩放）
        # 输入上限改为固定 6 位（悬浮窗解除候选位数限制，最高到 6 位数）
        maxlen = 6

        def on_key(d):
            cur = self._lucky_input_var.get()
            if d == "C":
                self._lucky_input_var.set("")
            elif d == "DEL":
                self._lucky_input_var.set(cur[:-1])
            elif len(cur) < maxlen:
                self._lucky_input_var.set(cur + d)

        keys = tk.Frame(dlg)
        keys.pack()
        # ttk 按钮字体须经 style 配置（ttk 控件不支持 font 选项）
        style = ttk.Style(dlg)
        style.configure("LuckyKey.TButton", font=(self.default_family, self._fsize(13)))
        style.configure("LuckyOk.TButton", font=(self.default_family, self._fsize(11)))
        layout = [("7", "8", "9"), ("4", "5", "6"), ("1", "2", "3"), ("DEL", "0", "确定")]
        for r, row in enumerate(layout):
            for c, label in enumerate(row):
                # "C" 已替换为"确定"（并与 DEL 对调）：确定固定在键盘网格内，
                # 即使窗口渲染异常（底部被裁）也始终有点确定的渠道
                if label == "确定":
                    cmd = self._make_confirm_fancy(dlg, candidates)
                else:
                    cmd = lambda d=label: on_key(d)
                ttk.Button(
                    keys, text=label, width=4,
                    style="LuckyKey.TButton",
                    command=cmd,
                ).grid(row=r, column=c, padx=int(3 * s), pady=int(3 * s))

        # 确定已并入键盘网格（唯一），不再单独放底部；Esc 仍可关闭弹窗
        dlg.bind("<Return>", lambda _e: self._make_confirm_fancy(dlg, candidates)())
        dlg.bind("<Escape>", lambda _e: dlg.destroy())

        # 窗口尺寸按内容自适应（字体随窗口缩放，Windows 下字体更高更宽，
        # 固定尺寸会裁掉底部「确定」按钮；实测内容尺寸保证按钮始终可见可点），
        # 并屏幕居中。
        dlg.update_idletasks()
        dw = dlg.winfo_reqwidth() + int(8 * s)
        dh = dlg.winfo_reqheight() + int(8 * s)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        dlg.geometry(f"{dw}x{dh}+{max(0, (sw - dw) // 2)}+{max(0, (sh - dh) // 2)}")

    def _make_confirm_fancy(self, dlg, candidates):
        def confirm():
            raw = self._lucky_input_var.get().strip()
            if not raw:
                messagebox.showwarning("化学课特供版", "请输入一个幸运数字")
                return
            try:
                num = int(raw)
            except ValueError:
                messagebox.showwarning("化学课特供版", f"请输入有效整数（{min(candidates)}~{max(candidates)}）")
                return
            if num not in candidates:
                messagebox.showwarning(
                    "化学课特供版",
                    f"{num} 不在候选数字范围内，请输入 {min(candidates)}~{max(candidates)}（黑名单除外）",
                )
                return
            self.fancy_lucky = num
            self.fancy_active = True
            self._refresh_fancy_visual()
            # 界面按标准版样式显示（不展示花哨专属文字），只保留标题后缀
            self.result_var.set(STARTUP_HINT)
            self.update_remaining()
            # 立即弹出主窗口（化学课特供版）——即使从悬浮球触发也恢复主窗口
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.focus_force()
            dlg.destroy()
        return confirm

    def _grab_when_viewable(self, win):
        """等窗口可见后再 grab，避免 TclError: grab failed: window not viewable。

        窗口刚创建时在部分合成器下尚未映射，立刻 grab 会失败；这里等
        after_idle 后再试，仍未可见则每 60ms 重试一次，直到成功或窗口销毁。
        """
        def attempt():
            if not win.winfo_exists():
                return
            try:
                win.grab_set()
            except tk.TclError:
                win.after(60, attempt)
        win.after_idle(attempt)

    def _cleanup_animations(self):
        """关闭窗口时取消挂起的长按计时与滚动动画。"""
        self._cancel_animation()
        self._cancel_fancy_hold()
        self._cancel_fancy_input_delay()

    def close_app(self):
        """悬浮窗关闭：清理后退出程序（化学课特供版不持久化，重开即恢复正常）。"""
        self.engine.flush()  # 退出前把累计记录落盘
        self._cleanup_animations()
        self._float_circle_photo = None  # 释放超采样位图
        self.root.destroy()

    def stop_process(self):
        """停止进程：清理动画与位图后销毁主窗口退出。"""
        self.engine.flush()  # 退出前把累计记录落盘
        self._cleanup_animations()
        self._float_circle_photo = None
        self.root.destroy()

    def toggle_autostart(self):
        set_autostart(self.autostart_var.get())

    def open_config_file(self):
        """用系统默认程序打开 config.json，供用户直接编辑。"""
        cfg_path = self.engine.store.path
        if not os.path.exists(cfg_path):
            self.engine.store.save(self.engine.config)
        try:
            open_file_externally(cfg_path)
            messagebox.showinfo("提示", "配置文件已打开，修改后会自动热加载，保存即可生效")
        except Exception as e:
            messagebox.showerror("错误", f"无法打开配置文件：{str(e)}")

    def _center_over(self, win, width, height):
        """把弹窗摆在主窗口正中；主窗口隐藏（如悬浮球模式）时退回屏幕正中。"""
        parent = self.root
        if parent.winfo_ismapped():
            base_x, base_y = parent.winfo_rootx(), parent.winfo_rooty()
            base_w, base_h = parent.winfo_width(), parent.winfo_height()
        else:
            base_x = base_y = 0
            base_w, base_h = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{width}x{height}+{max(0, base_x + (base_w - width) // 2)}+{max(0, base_y + (base_h - height) // 2)}")

    def show_about(self):
        """显示关于页面。"""
        about = tk.Toplevel(self.root)
        about.title("关于")
        self._center_over(about, 420, 220)
        about.minsize(360, 200)
        about.resizable(True, False)
        about.transient(self.root)
        self._grab_when_viewable(about)

        info_font = (self.default_family, 11)
        ttk.Label(
            about,
            text="本软件遵循 GNU General Public License v3.0 (GPL‑3.0) 开源协议",
            font=info_font,
            justify="center",
            wraplength=340,
        ).pack(pady=(24, 10))

        link_frame = ttk.Frame(about)
        link_frame.pack(pady=2, fill="x", padx=18)
        ttk.Label(link_frame, text="项目地址: ", font=info_font).pack(side="left")
        link_label = ttk.Label(
            link_frame,
            text="https://github.com/BFORIN/main",
            font=(self.default_family, 11, "underline"),
            foreground="blue",
            cursor="hand2",
            wraplength=250,
            justify="left",
        )
        link_label.pack(side="left", fill="x", expand=True)
        link_label.bind("<Button-1>", lambda _e: webbrowser.open("https://github.com/BFORIN/main"))
        ttk.Button(about, text="确定", command=about.destroy).pack(pady=(20, 10))

    def show_disclaimer(self):
        """显示免责声明对话框。"""
        disclaimer = tk.Toplevel(self.root)
        disclaimer.title("免责声明")
        self._center_over(disclaimer, 500, 260)
        disclaimer.minsize(420, 220)
        disclaimer.resizable(True, False)
        disclaimer.transient(self.root)
        self._grab_when_viewable(disclaimer)

        lines = (
            "本软件仅用于随机结果展示，不构成任何投资、决策、或法律依据。使用者应自行承担由本软件产生的全部风险和后果。",
            "开发者不对因使用本软件造成的任何直接或间接损失负责。",
            "最终解释权归开发者所有。",
        )
        text = "\n".join(f"        {line}" for line in lines)
        ttk.Label(
            disclaimer,
            text=text,
            font=(self.default_family, 11),
            justify="left",
            wraplength=440,
        ).pack(padx=20, pady=(20, 10), fill="x")
        ttk.Button(disclaimer, text="确定", command=disclaimer.destroy).pack(pady=(0, 15))


if __name__ == "__main__":
    DrawApp().run()