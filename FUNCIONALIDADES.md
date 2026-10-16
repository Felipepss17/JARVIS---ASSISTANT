# Funcionalidades do J.A.R.V.I.S.

Este documento reúne o que o projeto oferece atualmente, exemplos de comandos e os requisitos de cada recurso. O J.A.R.V.I.S. está em desenvolvimento; algumas ações dependem do Windows, de internet ou de uma chave de API.

## Interface e conversa

- Janela de chat para enviar mensagens por texto e receber respostas.
- Reator flutuante animado que indica o estado do assistente e dá acesso à interface.
- Respostas da IA e ferramentas para executar tarefas no projeto.
- Confirmação apresentada na interface antes de operações sensíveis, como executar código, instalar pacotes ou remover arquivos e plugins.

## Voz

- Ativação por voz usando “Jarvis” e reconhecimento de português.
- Durante a fala do assistente, é possível interrompê-lo com uma frase normal, sem repetir a palavra de ativação. Exemplo: “abra o YouTube”.
- Voz masculina em português do Brasil: Edge TTS online quando disponível e Piper local como alternativa.
- Reconhecimento local por Faster Whisper; pode baixar o modelo na primeira execução. Há fallback de reconhecimento online do Google.
- Efeitos sonoros da interface.

**Para usar:** conecte um microfone e alto-falantes ou fones. A qualidade da detecção de interrupção depende do microfone e do volume de reprodução.

## Chat com IA e ferramentas

Com uma chave `GROQ_API_KEY` configurada no arquivo `.env`, o J.A.R.V.I.S. pode conversar com a IA e, quando apropriado, usar ferramentas para:

- Listar, ler, criar e excluir arquivos dentro de `jarvis_workspace` (ações de escrita e exclusão pedem autorização).
- Executar um script Python em `jarvis_workspace` (pede autorização e tem limite de execução).
- Baixar um repositório público do GitHub como arquivo compactado para inspeção. A importação não executa o projeto.
- Criar, listar e remover plugins Python (alterações de plugins pedem autorização).
- Instalar pacotes Python e remover projetos importados (pedem autorização).
- Criar um arquivo ZIP de backup do código, excluindo arquivos sensíveis e ambientes/modelos ignorados pelo backup.

Os comandos locais básicos continuam disponíveis sem a chave da Groq; os recursos de IA dependem dela.

## Comandos locais

Os comandos abaixo são exemplos; algumas formas alternativas também são reconhecidas.

| O que faz | Exemplos |
|---|---|
| Ver hora e data | “Que horas são?”; “Que dia é hoje?” |
| Pesquisar no Google | “Pesquise sobre astronomia” |
| Pesquisar vídeos ou canais no YouTube | “Procure vídeos de jazz no YouTube”; “pesquise o canal …” |
| Controlar volume e mudo | “Aumente o volume”; “volume no máximo”; “silencie” |
| Controlar reprodução de mídia | “Pause a música”; “próxima música”; “música anterior” |
| Bloquear o computador | “Bloqueie o computador” |
| Abrir o Roblox Studio / preparar modo desenvolvimento | “Modo desenvolvimento” ou “modo dev” |
| Buscar e abrir um jogo no Roblox | “Entre no Roblox [nome do jogo]” |
| Abrir o Figma | “Abra o Figma” |

O modo desenvolvimento usa os aplicativos configurados no arquivo `acoes.py` e abre a pasta de projetos definida ali. A busca de jogos do Roblox e as pesquisas na web precisam de internet.

## Memória pessoal

As informações só são guardadas quando você pede explicitamente. Elas ficam localmente em SQLite.

- Guardar: “Lembre que prefiro respostas curtas”.
- Consultar: “O que você lembra de mim?”.
- Apagar uma informação: “Esqueça que prefiro respostas curtas”.
- Pedir para apagar tudo: “Apague todas as memórias”; o assistente pede confirmação.

Por padrão, as memórias não são compartilhadas com a IA. Para incluí-las no contexto enviado à Groq, configure `JARVIS_COMPARTILHAR_MEMORIA_COM_IA=1` no `.env`.

## Caixa de ideias e tarefas

Capture ideias ou tarefas rapidamente por voz ou pelo chat: “Anote uma ideia: criar um jogo de Roblox” ou “Guarde a tarefa de estudar matemática”. Diga “minhas ideias”, “minhas tarefas” ou “caixa de ideias” para revisar a lista. Use “concluir tarefa 2” para marcar como feita ou “apague ideia 3” para remover um item. Tudo fica local em `jarvis_workspace/caixa_ideias.sqlite3`.

## Rotinas

O comando **“modo estudo”** executa uma sequência configurável, que pode abrir aplicativos, pastas e endereços web, ativar o mudo e abrir as configurações de foco do Windows. Na primeira execução, o J.A.R.V.I.S. cria `jarvis_workspace/rotinas.json`; edite esse arquivo para ajustar as etapas.

## Agenda e lembretes

- Criar com confirmação do texto e horário: “Me lembre de estudar amanhã às 19h” ou “Me lembre de tomar água em 30 minutos”.
- Consultar: “Meus lembretes”.
- Cancelar: “Apague lembrete 2” (use o número exibido na lista).
- Os dados são locais. Os avisos são disparados enquanto o aplicativo está aberto.

## Entendimento da tela

Pergunte “O que está acontecendo aqui?” ou “Analise a tela”. O aplicativo captura o monitor principal e envia a imagem à Groq para análise. A captura é temporária, fica em memória durante a solicitação e não é gravada em arquivo. Este recurso requer `GROQ_API_KEY` e conexão com a internet.

## Estado do sistema

Pergunte “Estado do sistema” ou “Como está o sistema?” para consultar informações locais do Windows, como bateria, volume, microfone, títulos das janelas abertas e tarefas atuais do J.A.R.V.I.S. Algumas informações podem aparecer como indisponíveis dependendo do dispositivo.

## Plugins

Plugins Python em `plugins/` podem acrescentar comandos personalizados. Um plugin define `handle(texto)`, recebe o comando normalizado e devolve uma resposta ou `None`. O assistente também pode gerenciar plugins pelas ferramentas do chat, com autorização para criação, atualização e remoção.

## Configuração rápida

1. Instale as dependências com `pip install -r requirements.txt`.
2. Configure `GROQ_API_KEY` no arquivo `.env` para habilitar IA e análise da tela.
3. Inicie com `python main.py`.

Para instruções completas de instalação, configuração e testes, consulte [README.md](README.md). A suíte local pode ser executada com:

```powershell
python -m unittest discover -s tests -v
```
