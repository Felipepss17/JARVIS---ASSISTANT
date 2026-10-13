import webbrowser

# Define o comando que dispara este plugin. Aqui, qualquer texto que contenha a palavra "iniciar" será reconhecido.

def handle(texto):
    """Inicia o Roblox, ChatGPT e Spotify.

    O usuário pode dizer: "Iniciar".
    """
    if "iniciar" in texto.lower():
        try:
            webbrowser.open('https://www.roblox.com', new=1)
            webbrowser.open('https://chat.openai.com', new=1)
            webbrowser.open('https://open.spotify.com', new=1)
        except Exception as e:
            return f'Houve um erro ao abrir os sites: {e}'
        return 'Abrindo Roblox, ChatGPT e Spotify agora.'
    return None
