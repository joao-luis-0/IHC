import os
import sqlite3
from fastapi import FastAPI
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, "lojas.db")

app = FastAPI()

class questionRequest(BaseModel):
  query: str

@app.post("/question")
async def get_question(question: questionRequest):
  try:
    conn = sqlite3.connect(db_path)
    result = conn.execute(question.query).fetchall()
  except Exception as e:
    result = "Erro ao conectar com o banco"
  finally:
    conn.close()

  return result

def create_db():
  conn = sqlite3.connect(db_path)
  c = conn.cursor()
  
  c.execute("""CREATE TABLE IF NOT EXISTS produtos (
                codigo TEXT PRIMARY KEY,
                nome TEXT,
                departamento TEXT,
                preco REAL,
                marca TEXT,
                quantidade INTEGER,
                validade TEXT,
                fornecedor TEXT
            )""")

  c.executemany("INSERT INTO produtos VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
    ("01", "sabonete", "higiene", 3.50, "Nivea", 20, "2027-05", "Nivea Brasil"),
    ("02", "agua", "bebidas", 2.50, "Cristal", 30, "2027-10", "Agua Brasil"),
    ("03", "coca", "bebidas", 7.00, "Coca-Cola", 50, "2027-09", "Coca-Cola Brasil"),
    ("04", "condicionador", "higiene", 14.50, "Seda", 18, "2027-07", "Unilever Brasil"),
    ("05", "arroz", "alimentos", 25.90, "Camil", 40, "2027-12", "Camil Alimentos"),
    ("06", "feijao", "alimentos", 8.90, "Kicaldo", 35, "2027-11", "Kicaldo"),
    ("07", "macarrao", "alimentos", 5.50, "Renata", 25, "2028-01", "Selmi"),
    ("08", "leite", "alimentos", 5.90, "Italac", 30, "2026-12", "Italac"),
    ("09", "cafe", "alimentos", 18.90, "Pilao", 22, "2027-06", "JDE Brasil"),
    ("10", "suco de laranja", "bebidas", 6.50, "Del Valle", 20, "2027-09", "Coca-Cola Brasil"),
    ("11", "refrigerante guarana", "bebidas", 6.00, "Antarctica", 28, "2027-10", "Ambev"),
    ("12", "detergente", "limpeza", 2.99, "Ype", 40, "2028-02", "Quimica Amparo"),
    ("13", "sabao em po", "limpeza", 9.90, "Omo", 25, "2028-01", "Unilever Brasil"),
    ("14", "papel higienico", "higiene", 16.90, "Neve", 30, "2029-03", "Suzano"),
    ("15", "pasta de dente", "higiene", 7.50, "Colgate", 24, "2028-05", "Colgate-Palmolive"),
    ("16", "biscoito", "alimentos", 4.50, "Bauducco", 20, "2027-08", "Bauducco"),
    ("17", "chocolate", "doces", 6.90, "Lacta", 15, "2027-07", "Mondelez Brasil"),
    ("18", "batata chips", "salgadinhos", 8.00, "Ruffles", 18, "2027-09", "PepsiCo Brasil"),
    ("19", "agua com gas", "bebidas", 3.00, "gas aguas", 50, "2027-12", "Coca-Cola Brasil"),
    ("20", "acucar", "alimentos", 5.00, "União", 50, "2028-12", "Copersucar S.A."),
  ])

  conn.commit()
  conn.close()
