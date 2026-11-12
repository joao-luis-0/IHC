"""Versão independente do bot, sem a segunda chamada de explicação ao LLM."""
import argparse
import json
import logging
import os
from pathlib import Path

import dspy
import requests
from dotenv import load_dotenv

# Configurações compartilhadas pelo bot, pela otimização e pela avaliação.
BASE_DIR = Path(__file__).resolve().parent
SCHEMA = """CREATE TABLE IF NOT EXISTS produtos (
    codigo TEXT PRIMARY KEY,
    nome TEXT,
    departamento TEXT,
    preco REAL,
    marca TEXT,
    quantidade INTEGER,
    validade TEXT,
    fornecedor TEXT
)"""
DEFAULT_PROGRAM = BASE_DIR / "resultados" / "gerador_gepa.json"
logger = logging.getLogger(__name__)


def configure_lm(cache=True):
    """Lê o .env e conecta o DSPy ao modelo servido pelo Jan."""
    load_dotenv(BASE_DIR / ".env")
    model = os.getenv("JAN_MODEL", "gemma-4-E2B_q4_0-it")
    # O prefixo informa ao DSPy o protocolo da API compatível com OpenAI.
    # O endereço JAN_BASE_URL determina o servidor que recebe as chamadas.
    if not model.startswith("openai/"):
        model = "openai/" + model
    lm = dspy.LM(
        model,
        api_base=os.getenv("JAN_BASE_URL", "http://localhost:1337/v1"),
        api_key=os.getenv("JAN_API_KEY", "not-needed"),
        temperature=0,
        max_tokens=int(os.getenv("JAN_MAX_TOKENS", "1024")),
        timeout=int(os.getenv("JAN_TIMEOUT", "180")),
        num_retries=0,
        cache=cache,
    )
    dspy.configure(lm=lm)
    return lm


# A docstring desta assinatura faz parte do prompt recebido pelo modelo.
# Os campos descrevem as entradas (esquema e pergunta) e a saída (SQL).
class TextToSQL(dspy.Signature):
    """Generate SQL from natural language.

    Database schema:
      - produtos (
          nome, departamento, preco, marca, quantidade, validade, fornecedor)
    """
    dbschema = dspy.InputField(desc="Databases schema")
    question = dspy.InputField(desc="Natural language question")
    sql_query = dspy.OutputField(desc="Valid SQL query")


# Unidade que o GEPA otimiza. O CoT fica concentrado nesta classe.
class ReliableSQLGenerator(dspy.Module):
    def __init__(self):
        super().__init__()
        self.generate_sql = dspy.ChainOfThought(TextToSQL)

    def forward(self, dbschema, question):
        # O DSPy chama forward quando usamos generator(dbschema=..., question=...).
        return self.generate_sql(dbschema=dbschema, question=question)


def checked_select(sql):
    """Aplica a checagem de prefixo SELECT usada no fluxo do bot."""
    # Preserva a regra já existente no bot original. Não implementa o item 2.
    sql = sql.strip()
    if not sql.upper().startswith("SELECT"):
        raise ValueError("Apenas consultas SELECT são permitidas")
    return sql


def load_generator(mode="normal", program_path=DEFAULT_PROGRAM):
    """Cria o gerador e, no modo gepa, carrega suas instruções salvas."""
    generator = ReliableSQLGenerator()
    if mode == "gepa":
        path = Path(program_path)
        if not path.is_file():
            raise FileNotFoundError(
                f"Programa GEPA não encontrado: {path}. Execute optimize_gepa.py primeiro."
            )
        generator.load(str(path))
    return generator


class DatabaseClient:
    """Encapsula a comunicação HTTP com a API FastAPI do estoque."""

    def __init__(self, url):
        self.url = url.rstrip("/")

    def query(self, sql):
        response = requests.post(
            self.url + "/question", json={"query": checked_select(sql)}, timeout=10
        )
        response.raise_for_status()
        data = response.json()
        # A API atual pode retornar uma string de erro com HTTP 200.
        if not isinstance(data, list):
            raise RuntimeError(f"A API não retornou uma lista de resultados: {data}")
        return data


class SQLService:
    """Coordena pergunta → geração de SQL → consulta na API."""

    # Receber as dependências permite testar o serviço com objetos simulados.
    def __init__(self, generator, database):
        self.generator = generator
        self.database = database

    def generate(self, question):
        pred = self.generator(dbschema=SCHEMA, question=question)
        sql = checked_select(pred.sql_query)
        logger.info("SQL gerado: %s", sql)
        return self.database.query(sql)


def format_results(results):
    """Converte os dados em texto JSON para exibição no Telegram."""
    if not results:
        return "Nenhum resultado encontrado."
    # Formatação determinística; não chama o Gemma.
    return json.dumps(results, ensure_ascii=False, indent=2, default=str)


class TelegramApplication:
    """Gerencia as mensagens e reutiliza o serviço de consulta."""

    def __init__(self, token, service):
        import telebot
        self.bot = telebot.TeleBot(token)
        self.service = service
        self.whisper_model = None
        self.bot.message_handler(content_types=["text"])(self.reply_text)
        self.bot.message_handler(content_types=["voice"])(self.reply_voice)

    def send_results(self, message, question):
        result = format_results(self.service.generate(question))
        # Divide respostas longas em mensagens menores.
        for start in range(0, len(result), 3500):
            self.bot.reply_to(message, result[start:start + 3500])

    def reply_text(self, message):
        try:
            self.send_results(message, message.text)
        except ValueError as exc:
            self.bot.reply_to(message, str(exc))
        except Exception:
            logger.exception("Erro ao processar a pergunta")
            self.bot.reply_to(message, "Erro ao processar a pergunta. Confira o terminal do bot.")

    def reply_voice(self, message):
        try:
            import whisper
            # Carrega uma vez, no primeiro áudio, e reutiliza nas próximas mensagens.
            if self.whisper_model is None:
                self.whisper_model = whisper.load_model("tiny")
            url = self.bot.get_file_url(message.voice.file_id)
            text = self.whisper_model.transcribe(url)["text"]
            self.send_results(message, text)
        except Exception:
            logger.exception("Erro ao processar o áudio")
            self.bot.reply_to(message, "Erro ao processar o áudio. Confira o terminal do bot.")

    def run(self):
        self.bot.infinity_polling()


def main():
    """Monta as dependências e inicia o bot no modo escolhido no terminal."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["normal", "gepa"], default="normal")
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    configure_lm()
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("Defina TELEGRAM_TOKEN no arquivo .env")
    service = SQLService(
        load_generator(args.mode, args.program),
        DatabaseClient(os.getenv("DATABASE_URL", "http://localhost:8000")),
    )
    TelegramApplication(token, service).run()


# Permite importar o gerador nos scripts de GEPA sem iniciar o Telegram.
if __name__ == "__main__":
    main()
