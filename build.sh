#!/usr/bin/env bash
# 在 Linux 上用 Wine/Proton 一键打包 RandomDraw.exe 并分发到 ~/Public。
#
# 依赖：
#   - WE-Proton（Steam compatibilitytools）
#   - Windows Python（含 Pillow、PyInstaller）装在 /home/bforin/C
#   - wine 前缀位于 /home/bforin/.local/share/pfx（btrfs 支持符号链接，
#     持久化；不要放 /tmp 或 exFAT SD 卡，前者重启即清、后者不支持 symlink）
#
# 用法：bash build.sh
set -u

PROJECT="/home/bforin/SD/Repos/Project1"
WE="/home/bforin/.local/share/Steam/compatibilitytools.d/WE-Proton Latest"
PFX="/home/bforin/.local/share/pfx"
PY="/home/bforin/C/Users/BFORIN/AppData/Local/Programs/Python/Python314/python.exe"
PUBLIC="$HOME/Public"

export STEAM_COMPAT_CLIENT_INSTALL_PATH="$HOME/.steam/steam"
export STEAM_COMPAT_DATA_PATH="$PFX"

fail() { echo "✗ $*" >&2; exit 1; }
ok()   { echo "✓ $*"; }

# --- 前置检查 ---
[ -d "$PROJECT" ]              || fail "项目目录不存在：$PROJECT"
[ -d "$WE" ]                   || fail "WE-Proton 不存在：$WE"
[ -f "$PFX/pfx.lock" ]         || fail "wine 前缀缺失：$PFX/pfx.lock（先用 proton 初始化）"
[ -f "$PY" ]                   || fail "Windows Python 不存在：$PY"
[ -f "$PROJECT/random_draw.py" ] || fail "缺少 random_draw.py"

cd "$PROJECT" || fail "无法进入项目目录"

# --- 1) 打包 ---
echo "==> 打包 RandomDraw.exe（PyInstaller，onefile/windowed）..."
timeout 700 xvfb-run -a "$WE/proton" run "$PY" -m PyInstaller \
    --noconfirm --clean --onefile --windowed \
    --name RandomDraw random_draw.py >/tmp/opencode/build.log 2>&1
rc=$?
[ $rc -eq 0 ] || { tail -20 /tmp/opencode/build.log; fail "PyInstaller 失败（exit=$rc）"; }
[ -f dist/RandomDraw.exe ] || fail "未生成 dist/RandomDraw.exe"
ok "打包完成"

# --- 2) 分发到 ~/Public（config.json 由程序首次运行自动生成，不随包复制） ---
mkdir -p "$PUBLIC"
cp -f dist/RandomDraw.exe "$PUBLIC/" || fail "复制到 ~/Public 失败"
ok "已复制到 $PUBLIC/"

# --- 3) 校验 ---
file "$PUBLIC/RandomDraw.exe" | grep -q "PE32+ executable for MS Windows" \
    || fail "产物不是有效的 PE32+"
python3 - "$PUBLIC/RandomDraw.exe" <<'PYEOF' || fail "子系统校验失败"
import struct, sys
d = open(sys.argv[1], 'rb').read()
e = struct.unpack('<I', d[0x3c:0x40])[0]
opt = e + 24
sub = struct.unpack('<H', d[opt+68:opt+70])[0]
assert sub == 2, f"子系统应为 GUI(2)，实际 {sub}"
print(f"  subsystem={sub} (GUI)")
PYEOF

md5_dist=$(md5sum dist/RandomDraw.exe | awk '{print $1}')
md5_pub=$(md5sum "$PUBLIC/RandomDraw.exe" | awk '{print $1}')
[ "$md5_dist" = "$md5_pub" ] || fail "md5 不一致（dist=$md5_dist public=$md5_pub）"

echo
echo "✅ 打包并分发完成"
echo "   产物：$PUBLIC/RandomDraw.exe"
echo "   大小：$(du -h "$PUBLIC/RandomDraw.exe" | cut -f1)"
echo "   md5 ：$md5_pub"
