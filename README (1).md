# IHC — Bot de consultas ao estoque

O bot recebe perguntas pelo Telegram, usa o Gemma no Jan para gerar consultas SQL e devolve os resultados do SQLite pela API FastAPI.

## O que instalar

- **Python 3.11 ou 3.12** para criar o ambiente virtual e instalar as dependências.
- **Jan** com o modelo `gemma-4-E2B_q4_0-it` e o servidor local na porta `1337`.
- **Git**, caso queira clonar o repositório.
- **Whisper e FFmpeg**, apenas para usar mensagens de voz na versão nova.
- **Token do Telegram**, criado pelo BotFather, para iniciar o bot.

## Configuração no Windows (PowerShell)

Abra o PowerShell na pasta que contém `database.py` e execute:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-gepa.txt
```

Se já tiver uma `.venv` nessa pasta, use o Python dela diretamente. O arquivo `requirements-gepa.txt` instala as bibliotecas da versão nova em modo texto, incluindo FastAPI, Uvicorn, DSPy e GEPA. O `requirements.txt` pertence à versão original.

Se ainda não tiver um `.env`, crie-o a partir do exemplo:

```powershell
if (-not (Test-Path .\.env)) {
    Copy-Item .\.env.gepa.example .\.env
}
notepad .\.env
```

Preencha `TELEGRAM_TOKEN` com seu token. Confira se `JAN_MODEL` coincide com o ID do modelo no Jan. Mantenha o token apenas no `.env` local.

Para usar voz, instale o Whisper no mesmo ambiente e disponibilize o FFmpeg no `PATH`:

```powershell
.\.venv\Scripts\python.exe -m pip install openai-whisper
ffmpeg -version
```

## Como executar

Com o servidor local do Jan ligado, inicie a API em um PowerShell:

```powershell
.\.venv\Scripts\python.exe -m uvicorn database:app --host 127.0.0.1 --port 8000
```

Em outro PowerShell na mesma pasta, inicie o bot:

```powershell
.\.venv\Scripts\python.exe bot_sem_linguagem_natural.py --mode normal
```

No Telegram, pergunte: “Qual é o preço do sabonete?”

Para testar o GEPA, pare o bot com `Ctrl+C` e mantenha o Jan ligado. Se ainda não existir `resultados/gerador_gepa.json`, gere o arquivo:

```powershell
.\.venv\Scripts\python.exe optimize_gepa.py --quick
```

Depois, com o Jan e a API ligados, execute:

```powershell
.\.venv\Scripts\python.exe bot_sem_linguagem_natural.py --mode gepa
```

Para comparar os acertos e os tempos dos dois modos:

```powershell
.\.venv\Scripts\python.exe sql_evaluation.py --with-explanation
```

Os relatórios ficam em `resultados/avaliacao.json` e `resultados/avaliacao.csv`.
