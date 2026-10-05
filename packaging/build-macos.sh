#!/bin/bash
# 在 Mac 上重建 ObraDinnSaveTool.app 并打发布 zip
#
#   前置：源码已经在 ~/ObraDinnSaveTool（从 Windows 端 tar+scp 过去的那一份）
#   用法：bash ~/ObraDinnSaveTool/_remote/build-savetool-mac.sh
#
# 做四件事：png->icns、venv+pyinstaller、打 .app（并 headless 自检 HTTP）、压成发布 zip
set -e
cd "$HOME/ObraDinnSaveTool"
P=/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12
NAME="ObraDinnSaveTool_MacOS"

echo "--- 1. png -> icns"
if [ -f icon_save.png ]; then
  rm -rf /tmp/icon_save.iconset icon_save.icns
  mkdir -p /tmp/icon_save.iconset
  for s in 16 32 64 128 256 512; do
    sips -z $s $s icon_save.png --out /tmp/icon_save.iconset/icon_${s}x${s}.png >/dev/null
    sips -z $((s*2)) $((s*2)) icon_save.png --out /tmp/icon_save.iconset/icon_${s}x${s}@2x.png >/dev/null
  done
  iconutil -c icns /tmp/icon_save.iconset -o icon_save.icns
  ls -l icon_save.icns | awk '{print $5, $9}'
else
  echo "!! 没有 icon_save.png，.app 用默认图标"
fi

echo "--- 2. venv + pyinstaller"
if [ ! -x .venv/bin/python ]; then "$P" -m venv .venv; fi
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q pyinstaller
echo -n "pyinstaller "; .venv/bin/python -m PyInstaller --version

echo "--- 3. build .app"
# 旧实例开着的话 dist/ 删不掉（rm -rf 会失败），先收掉
pkill -f "ObraDinnSaveTool.app/Contents/MacOS" 2>/dev/null && echo "（已关掉旧的 .app 实例）" || true
sleep 1
rm -rf build dist
.venv/bin/python build_gui.py --onedir 2>&1 | tail -6
APP=dist/ObraDinnSaveTool.app
ls -d "$APP"

echo "--- 4. smoke（无窗口跑起来，打 HTTP 自检）"
BIN="$APP/Contents/MacOS/ObraDinnSaveTool"
"$BIN" --no-browser --port 8790 >/tmp/savetool-smoke.log 2>&1 &
SMOKE=$!
sleep 14
fail=0
for u in /api/state /api/difficulty /maker; do
  code=$(curl -s -o /tmp/smoke.out -w '%{http_code}' "http://127.0.0.1:8790$u" || echo 000)
  size=$(wc -c < /tmp/smoke.out | tr -d ' ')
  echo "  $u -> $code  ${size}B"
  [ "$code" = "200" ] || fail=1
done
if [ "$fail" = "0" ]; then
  curl -s http://127.0.0.1:8790/api/difficulty > /tmp/diff.json
  /usr/bin/python3 -c 'import json;d=json.load(open("/tmp/diff.json"));print("  难度工具 available=%s level=%s/%s installDir=%s" % (d["available"], d["level"], d["levelName"], d["installDir"]))'
  echo "  /maker 含制作器工具条: $(curl -s http://127.0.0.1:8790/maker | grep -c mkbar)"
  echo "  /api/state 槽位/预制/库: $(curl -s http://127.0.0.1:8790/api/state | /usr/bin/python3 -c 'import json,sys;s=json.load(sys.stdin);print(len(s["slots"]),len(s["presets"]),len(s["library"]))')"
else
  echo "!! 自检有失败项，日志尾部："; tail -5 /tmp/savetool-smoke.log
fi
kill $SMOKE 2>/dev/null || true
sleep 1

echo "--- 5. release zip"
rm -rf "dist/$NAME" "dist/$NAME.zip"
# 自检时真跑过一遍，包里会多出运行期生成的东西（saves/、日志）—— 发出去只留 .app
rm -rf "$APP/Contents/MacOS/saves"
rm -f "$APP"/Contents/MacOS/*.log
mkdir -p "dist/$NAME"
cp -R "$APP" "dist/$NAME/"
( cd dist && ditto -c -k --sequesterRsrc --keepParent "$NAME" "$NAME.zip" )
# 旧命名的包别留着晃眼
rm -f dist/ObraDinnSaveTool-0.1.0-macos-x86_64.zip "$HOME/Desktop/ObraDinnSaveTool-0.1.0-macos-x86_64.zip"
cp "dist/$NAME.zip" "$HOME/Desktop/"

echo "--- 结果"
ls -lh "dist/$NAME.zip" | awk '{print $5, $9}'
shasum -a 256 "dist/$NAME.zip" | awk '{print $1}'
