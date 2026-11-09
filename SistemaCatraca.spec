# Gera dist/SistemaCatraca.exe. Requer: pip install pyinstaller
# Uso: python build.py (grava o .exe e o .sha256 em dist/ e usa pasta temporária fora do OneDrive)

a = Analysis(
    ["main.py"],
    datas=[("styles.qss", ".")],
    excludes=["tkinter", "numpy", "PIL", "matplotlib", "pandas", "pytest",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml",
              "PySide6.QtQuick", "PySide6.QtPdf", "PySide6.QtMultimedia", "PySide6.QtNetwork"],
)

# Binários do Qt que o programa não usa (renderização OpenGL por software, QML, Quick, PDF).
DESNECESSARIOS = ("opengl32sw", "qt6quick", "qt6qml", "qt6pdf", "qt6network", "qt6opengl",
                  "qt6virtualkeyboard", "qt6dbus")
a.binaries = [b for b in a.binaries if not b[0].lower().split("\\")[-1].startswith(DESNECESSARIOS)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="SistemaCatraca",
    icon="assets/app.ico",
    console=False,
)
