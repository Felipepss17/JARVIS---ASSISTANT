import sys, os

# Adiciona o caminho do projeto pyperclip ao sys.path
PASTA = os.path.join(os.path.dirname(__file__), '..', 'jarvis_workspace', 'importados', 'asweigart_pyperclip', 'src')
sys.path.append(os.path.abspath(PASTA))

try:
    import pyperclip
except Exception as e:
    pyperclip = None
    ERROR = str(e)


def handle(texto):
    """Comandos de voz para manipulação da área de transferência.

    • copiar <texto>  – Copia <texto> para a área de transferência.
    • colar ou pasta – Retorna o conteúdo atual da área de transferência.
    """
    texto = texto.lower()
    if texto.startswith('copiar '):
        if pyperclip is None:
            return 'Erro: pyperclip não está disponível.'
        texto_copia = texto[7:]
        try:
            pyperclip.copy(texto_copia)
            preview = texto_copia[:20] + ('...' if len(texto_copia) > 20 else '')
            return f'Copiado para a área de transferência: {preview}'
        except Exception as e:
            return f'Erro ao copiar: {e}'
    if texto in ('colar', 'pasta', 'colar texto'):
        if pyperclip is None:
            return 'Erro: pyperclip não está disponível.'
        try:
            texto_colado = pyperclip.paste()
            return f'Texto colado: {texto_colado}'
        except Exception as e:
            return f'Erro ao colar: {e}'
    return None
