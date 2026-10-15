# J.A.R.V.I.S.

Assistente pessoal para Windows, com interface de desktop, comandos por voz e chat com ferramentas. O projeto está em desenvolvimento e foi pensado para uso local no computador do autor.

## Recursos atuais

- Interface flutuante com indicador animado e janela de chat.
- Ativação por voz com a palavra “Jarvis”, reconhecimento em português e resposta falada.
- Voz masculina em português do Brasil: tenta Edge TTS online e usa Piper `pt_BR-faber-medium` como reserva local. Não usa vozes femininas como fallback.
- Reconhecimento local com `faster-whisper` (modelo `small`, baixado na primeira utilização) ou fallback para o reconhecimento online do Google.
- Chat com IA da Groq, incluindo chamadas de ferramentas para ler e criar arquivos na pasta `jarvis_workspace`, importar projetos públicos do GitHub e gerenciar plugins.
- Comandos locais para abrir programas e sites, pesquisar na web, controlar mídia e volume e iniciar o Roblox Studio.
- Plugins Python para acrescentar comandos personalizados.
- Confirmação antes de operações sensíveis oferecidas pelas ferramentas do chat, como executar código, instalar pacotes ou criar/remover plugins.

## Requisitos

- Windows 10 ou 11.
- Python 3.11 recomendado.
- Microfone e saída de áudio para os recursos de voz.
- Chave de API da Groq para usar o chat e as respostas de IA.
- Conexão com a internet para instalar dependências, usar a API da Groq e o reconhecimento online de fallback. A fala neural do Edge TTS também precisa de internet quando habilitada. O `faster-whisper` pode baixar o modelo na primeira execução.

## Instalação

Abra o PowerShell nesta pasta e execute:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Se o PowerShell bloquear a ativação do ambiente, execute na mesma janela:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

O `requirements.txt` inclui as dependências do aplicativo, inclusive `faster-whisper` para reconhecimento local de voz.

## Configuração da API

Crie um arquivo `.env` na pasta do projeto e adicione sua chave:

```text
GROQ_API_KEY=sua_chave_aqui
```

Sem essa variável, os comandos locais continuam disponíveis, mas os recursos de IA não funcionam. Não compartilhe o `.env` nem inclua chaves em código ou backups públicos.

O JARVIS tenta a voz neural masculina do Edge TTS (`pt-BR-AntonioNeural`) e, se o serviço online estiver indisponível, usa o modelo Piper `pt_BR-faber-medium` local. Para preparar o modelo em uma instalação nova, execute `python -m piper.download_voices --download-dir assets/voices pt_BR-faber-medium`. O modelo local permite falar sem internet depois de baixado.

## Executar

Com o ambiente virtual ativado:

```powershell
python main.py
```

O JARVIS também pode ser configurado para iniciar com o Windows executando `python iniciar_com_windows.py`. Para remover essa configuração, execute `python iniciar_com_windows.py remover`.

## Testes

Com o ambiente virtual ativado, rode os testes locais:

```powershell
python -m unittest discover -s tests -v
```

O teste de voz online é separado porque precisa acessar a internet:

```powershell
$env:JARVIS_TEST_ONLINE_VOICE = "1"
python -m unittest discover -s tests -p test_jarvis.py -k GoogleOnlineVoiceTests -v
```

Para testar especificamente a voz neural do Edge TTS, use `$env:JARVIS_TEST_EDGE_VOICE = "1"` e troque `GoogleOnlineVoiceTests` por `EdgeOnlineVoiceTests` no comando. O endpoint do Edge TTS pode recusar conexões em alguns ambientes.

## Estrutura do projeto

- `main.py`: ponto de entrada e inicialização do aplicativo.
- `jarvis/settings.py`: configurações, limites e prompts da IA.
- `jarvis/audio.py`: captura do microfone, detecção da palavra de ativação e reconhecimento de fala.
- `jarvis/workers.py`: tarefas em background para IA, comandos e fala.
- `jarvis/ui.py`: janela de chat e indicador flutuante.
- `jarvis/controller.py`: coordenação da interface, ações, áudio e workers.
- `acoes.py`: comandos locais reconhecidos diretamente, sem depender da IA.
- `ferramentas.py`: ferramentas do chat, operações no workspace, importação de projetos e gerenciamento de plugins.
- `plugins/`: plugins de comandos por voz.
- `jarvis_workspace/`: arquivos de trabalho e projetos importados pelo assistente.
- `assets/sounds/`: efeitos sonoros da interface.

## Observações

- O analisador de projetos importados procura padrões de risco de forma heurística. Ele ajuda na inspeção, mas não certifica que um projeto seja seguro.
- Plugins e código autorizado são executados com as permissões do usuário que iniciou o JARVIS.
- O projeto está em desenvolvimento; recursos, dependências e instruções podem mudar.
