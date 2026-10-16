# Assistente do Roblox Studio

O JARVIS pode ler scripts Lua/Luau de uma pasta local e receber erros/avisos do Output para explicar possíveis causas. A análise é somente leitura; nada é alterado dentro do jogo.

## 1. Configure a pasta de scripts

No `.env` do JARVIS, informe a pasta que contém seus arquivos `.lua` ou `.luau`:

```env
JARVIS_ROBLOX_PROJECT_DIR=C:\Users\Felipe17\Documents\MeuJogo\src
```

Reinicie o JARVIS. No chat, peça para listar ou analisar os scripts. A busca ignora pastas comuns de dependências/build, não segue links simbólicos e limita cada leitura a 30 KB. Arquivos `.rbxl` binários não são lidos; use arquivos-fonte sincronizados/exportados.

## 2. Conecte o Output do Studio

1. Deixe o JARVIS aberto. Ele inicia uma ponte HTTP somente em `127.0.0.1:18743`.
2. No Roblox Studio, crie um `Script`, cole o conteúdo de `roblox/JARVIS_Output_Connector.lua` e selecione **Plugins > Save as Local Plugin** (Salvar como plugin local). O Studio salva e carrega o plugin local.
3. Se o Studio pedir autorização de acesso HTTP ao endereço local, permita para usar a ponte.
4. Clique no botão **CaptureOutput** da barra **JARVIS** para iniciar a captura. Clique novamente para parar.
5. Reproduza o erro no Studio e peça no chat do JARVIS: “analise os erros do Output do Roblox”.

O plugin encaminha erros e avisos somente enquanto a captura está ligada. Os registros ficam apenas na memória do processo e desaparecem quando o JARVIS fecha. A ponte aceita apenas texto de erros/avisos, não executa comandos e não escuta conexões da rede local.

## Limites

- A integração precisa do JARVIS e do Roblox Studio abertos ao mesmo tempo.
- A ponte só vê mensagens que o plugin consegue ler do Output e que o Studio permite encaminhar para localhost.
- Para inspeção de código, configure uma pasta com arquivos-fonte Lua/Luau; o JARVIS não extrai conteúdo de `.rbxl`/`.rbxlx`.
