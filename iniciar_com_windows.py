import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
pythonw = os.path.join(here, ".venv", "Scripts", "pythonw.exe")
main = os.path.join(here, "main.py")
startup = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows",
                       "Start Menu", "Programs", "Startup")
vbs = os.path.join(startup, "JARVIS.vbs")

if len(sys.argv) > 1 and sys.argv[1] == "remover":
    if os.path.exists(vbs):
        os.remove(vbs)
        print("Inicialização automática removida.")
    else:
        print("Nada para remover.")
    sys.exit()

if not os.path.exists(pythonw):
    sys.exit(f"Não encontrei {pythonw}. Rode este script na pasta do JARVIS, com o .venv criado.")

script = (
    'Set sh = CreateObject("WScript.Shell")\r\n'
    'WScript.Sleep 15000\r\n'
    f'sh.CurrentDirectory = "{here}"\r\n'
    'sh.Run """' + pythonw + '"" ""' + main + '""", 0, False\r\n'
)
with open(vbs, "w", encoding="mbcs") as f:
    f.write(script)
print("Pronto! O JARVIS vai iniciar junto com o Windows.")
print("Arquivo criado em:", vbs)