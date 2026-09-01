import dspy
import telebot #pip install pytelegrambotapi
import whisper #pip install -U openai-whisper
import json
import os
from dotenv import load_dotenv
import requests

load_dotenv()

lm = dspy.LM('openai/gemma-4-E2B-it-IQ4_XS', api_base='http://localhost:1337/v1', api_key='not-needed')
dspy.configure(lm=lm)

class TextToSQL(dspy.Signature):
    """Generate SQL from natural language.

        Database schema:
          - produtos (
              nome, departamento, preco, marca, quantidade, validade, fornecedor)
    """
    dbschema = dspy.InputField(desc="Databases schema")
    question = dspy.InputField(desc="Natural language question")
    sql_query = dspy.OutputField(desc="Valid SQL query")

class ResultToNaturalLanguage(dspy.Signature):
    """Convert a SQL query result into a natural, conversational answer in Portuguese. Ignore the id column"""
    question = dspy.InputField(desc="Pergunta original do usuário")
    sql_query = dspy.InputField(desc="Query SQL executada")
    result = dspy.InputField(desc="Resultado da consulta em formato JSON")
    answer = dspy.OutputField(desc="Resposta em linguagem natural, clara e direta")

class ReliableSQLGenerator(dspy.Module):
    def __init__(self):
        super().__init__()
        self.generate_sql = dspy.ChainOfThought(TextToSQL)
        self.explain_result = dspy.ChainOfThought(ResultToNaturalLanguage)

    def forward(self, dbschema, question):
        pred = self.generate_sql(dbschema=dbschema, question=question)
        return pred

    def explain(self, question, sql_query, result):
        return self.explain_result(
            question=question,
            sql_query=sql_query,
            result=json.dumps(result, default=str, ensure_ascii=False)
        )

def generate(question):
    schema = """CREATE TABLE IF NOT EXISTS produtos (
                codigo TEXT PRIMARY KEY,
                nome TEXT,
                departamento TEXT,
                preco REAL,
                marca TEXT,
                quantidade INTEGER,
                validade TEXT,
                fornecedor TEXT
            )"""
    generator = ReliableSQLGenerator()
    sql = generator.forward(schema, question)
    sql_query = sql.sql_query.strip()

    if not sql_query.upper().startswith("SELECT"):
        raise ValueError("Apenas consultas SELECT são permitidas")

    try:
        print(sql_query)
        response = requests.post(os.getenv("DATABASE_URL") + "/question", json={"query": sql_query}, timeout=10)
        response.raise_for_status() 
        results = response.json()
    except requests.RequestException as e:
        results = {"erro": f"Erro ao fazer a consulta: {e}"}

    explanation = generator.explain(question, sql_query, results)
    return explanation.answer

bot = telebot.TeleBot(os.getenv("TELEGRAM_TOKEN"))

@bot.message_handler(content_types=["text"])
def reply_hi(message):
    try:
        result = generate(message.text)
        bot.reply_to(message, result)
    except ValueError as e:
        bot.reply_to(message, str(e))
    except Exception:
        bot.reply_to(message, "Desculpa, algo deu errado ao processar sua mensagem.")

@bot.message_handler(content_types=['voice'])
def transcribe_voice_message(message):
    file_id = message.voice.file_id
    # Get url to audio file.
    file_path = bot.get_file_url(file_id)

    # Transcribe the audio using Whisper AI
    text = whisper_transcribe(file_path)

    result = generate(text)
    bot.reply_to(message, json.dumps(result))

model = whisper.load_model("tiny")
def whisper_transcribe(filepath: str) -> str:
    """
    Function to perform ASR on a .mp3 file
    :param filepath: Path to the .mp3 audiofile.
    :param model: Set the model type for whisper
    ["tiny", "base", "small", "medium", "large"].
    Larger model means more parameters, higher memory requirements and
    slower speed.
    :return: transcribed audio.
    """
    result = model.transcribe(filepath)

    return result["text"]

bot.polling()