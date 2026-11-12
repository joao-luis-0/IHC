"""Dataset, métrica com feedback para GEPA e avaliação em teste separado."""
import argparse
from collections import Counter
from contextlib import closing
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
from time import perf_counter

import dspy

from bot_sem_linguagem_natural import (
    BASE_DIR, DEFAULT_PROGRAM, SCHEMA, checked_select, configure_lm,
    format_results, load_generator,
)

# Cada pergunta especifica as colunas para evitar diferenças de apresentação.
# Partições fixas: teste nunca é passado ao GEPA.
DATASET = {
    "train": [
        ("Qual é o preço do sabonete? Retorne apenas preco.", "SELECT preco FROM produtos WHERE nome = 'sabonete'"),
        ("Quantos produtos diferentes existem? Retorne a contagem.", "SELECT COUNT(*) FROM produtos"),
        ("Liste nome e preco dos produtos de bebidas, em ordem de nome.", "SELECT nome, preco FROM produtos WHERE departamento = 'bebidas' ORDER BY nome"),
        ("Qual a soma das quantidades em estoque?", "SELECT SUM(quantidade) FROM produtos"),
        ("Liste nome dos produtos da marca Nivea.", "SELECT nome FROM produtos WHERE marca = 'Nivea'"),
        ("Liste nome e preco dos produtos com preço maior que 15, em ordem de nome.", "SELECT nome, preco FROM produtos WHERE preco > 15 ORDER BY nome"),
        ("Qual o preço médio dos produtos de alimentos?", "SELECT AVG(preco) FROM produtos WHERE departamento = 'alimentos'"),
        ("Liste nome e quantidade dos produtos com menos de 20 unidades, em ordem de nome.", "SELECT nome, quantidade FROM produtos WHERE quantidade < 20 ORDER BY nome"),
        ("Liste departamento e quantidade de produtos diferentes por departamento, em ordem de departamento.", "SELECT departamento, COUNT(*) FROM produtos GROUP BY departamento ORDER BY departamento"),
        ("Liste nome dos produtos fornecidos pela Unilever Brasil, em ordem de nome.", "SELECT nome FROM produtos WHERE fornecedor = 'Unilever Brasil' ORDER BY nome"),
        ("Liste nome e validade dos produtos com validade anterior a 2027-01, em ordem de nome.", "SELECT nome, validade FROM produtos WHERE validade < '2027-01' ORDER BY nome"),
        ("Qual o nome e o preço do produto mais caro?", "SELECT nome, preco FROM produtos ORDER BY preco DESC LIMIT 1"),
    ],
    "validation": [
        ("Qual a quantidade de feijao? Retorne apenas quantidade.", "SELECT quantidade FROM produtos WHERE nome = 'feijao'"),
        ("Quantos produtos diferentes são de higiene?", "SELECT COUNT(*) FROM produtos WHERE departamento = 'higiene'"),
        ("Liste nome e preco dos produtos de limpeza, em ordem de nome.", "SELECT nome, preco FROM produtos WHERE departamento = 'limpeza' ORDER BY nome"),
        ("Qual o total de unidades de bebidas?", "SELECT SUM(quantidade) FROM produtos WHERE departamento = 'bebidas'"),
        ("Liste nome dos produtos da marca Lacta.", "SELECT nome FROM produtos WHERE marca = 'Lacta'"),
        ("Liste nome e preco dos produtos com preço menor que 4, em ordem de nome.", "SELECT nome, preco FROM produtos WHERE preco < 4 ORDER BY nome"),
        ("Qual o preço médio dos produtos de higiene?", "SELECT AVG(preco) FROM produtos WHERE departamento = 'higiene'"),
        ("Liste nome e quantidade dos produtos com pelo menos 40 unidades, em ordem de nome.", "SELECT nome, quantidade FROM produtos WHERE quantidade >= 40 ORDER BY nome"),
        ("Liste departamento e soma das quantidades por departamento, em ordem de departamento.", "SELECT departamento, SUM(quantidade) FROM produtos GROUP BY departamento ORDER BY departamento"),
        ("Liste nome dos produtos fornecidos pela Coca-Cola Brasil, em ordem de nome.", "SELECT nome FROM produtos WHERE fornecedor = 'Coca-Cola Brasil' ORDER BY nome"),
        ("Liste nome e validade dos produtos que vencem em 2028, em ordem de nome.", "SELECT nome, validade FROM produtos WHERE validade LIKE '2028-%' ORDER BY nome"),
        ("Qual o nome e o preço do produto mais barato?", "SELECT nome, preco FROM produtos ORDER BY preco ASC LIMIT 1"),
    ],
    "test": [
        ("Qual o fornecedor do cafe? Retorne apenas fornecedor.", "SELECT fornecedor FROM produtos WHERE nome = 'cafe'"),
        ("Quantos departamentos diferentes existem?", "SELECT COUNT(DISTINCT departamento) FROM produtos"),
        ("Liste nome e preco dos alimentos que custam mais de 10, em ordem de nome.", "SELECT nome, preco FROM produtos WHERE departamento = 'alimentos' AND preco > 10 ORDER BY nome"),
        ("Qual o valor total do estoque, somando preço vezes quantidade?", "SELECT SUM(preco * quantidade) FROM produtos"),
        ("Liste codigo e nome dos produtos da marca Cristal.", "SELECT codigo, nome FROM produtos WHERE marca = 'Cristal'"),
        ("Liste nome e preco dos produtos com preço entre 5 e 8, inclusive, em ordem de nome.", "SELECT nome, preco FROM produtos WHERE preco BETWEEN 5 AND 8 ORDER BY nome"),
        ("Qual o maior preço entre as bebidas?", "SELECT MAX(preco) FROM produtos WHERE departamento = 'bebidas'"),
        ("Liste nome e quantidade dos produtos com quantidade igual a 30, em ordem de nome.", "SELECT nome, quantidade FROM produtos WHERE quantidade = 30 ORDER BY nome"),
        ("Liste departamento e valor total do estoque por departamento, em ordem de departamento.", "SELECT departamento, SUM(preco * quantidade) FROM produtos GROUP BY departamento ORDER BY departamento"),
        ("Liste nome dos produtos cujo nome contém agua, em ordem de nome.", "SELECT nome FROM produtos WHERE nome LIKE '%agua%' ORDER BY nome"),
        ("Liste nome e validade dos produtos que vencem em 2027-09, em ordem de nome.", "SELECT nome, validade FROM produtos WHERE validade = '2027-09' ORDER BY nome"),
        ("Liste nome dos produtos da marca Inexistente.", "SELECT nome FROM produtos WHERE marca = 'Inexistente'"),
    ],
}


def build_examples(split):
    """Converte a partição em exemplos DSPy com entradas e SQL de referência."""
    return [
        dspy.Example(dbschema=SCHEMA, question=q, expected_sql=sql,
                     ordered="ORDER BY" in sql.upper()).with_inputs("dbschema", "question")
        for q, sql in DATASET[split]
    ]


def normalized(rows):
    """Padroniza as linhas e reduz diferenças de arredondamento decimal."""
    return [tuple(round(v, 6) if isinstance(v, float) else v for v in row) for row in rows]


class SQLBenchmark:
    """Reúne o banco de avaliação, a comparação e o feedback para o GEPA."""

    def __init__(self, path=BASE_DIR / "lojas.db"):
        path = Path(path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Banco de avaliação não encontrado: {path}")
        self.database_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        # Snapshot fixo apenas para avaliação; não altera o banco ou o gerador.
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
            self.dump = "\n".join(conn.iterdump())
        if not self.execute("SELECT COUNT(*) FROM produtos")[0][0]:
            raise ValueError("O banco de avaliação está vazio.")

    def execute(self, sql):
        """Executa uma consulta na cópia temporária do banco em memória."""
        sql = checked_select(sql)
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.executescript(self.dump)
            # A cópia recebe restrições de leitura antes de executar o SQL gerado.
            conn.execute("PRAGMA query_only = ON")
            allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}

            def authorize(action, arg1, arg2, db, source):
                if action not in allowed or (action == sqlite3.SQLITE_FUNCTION and arg2 == "load_extension"):
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            conn.set_authorizer(authorize)
            ticks = 0

            def progress():
                nonlocal ticks
                ticks += 1
                return int(ticks > 1000)

            # Interrompe consultas excessivamente custosas durante a avaliação.
            conn.set_progress_handler(progress, 1000)
            rows = conn.execute(sql).fetchmany(1001)
            if len(rows) > 1000:
                raise ValueError("Resultado de avaliação excedeu 1000 linhas")
            return rows

    def assess(self, example, sql):
        """Compara resultados, respeitando ordenação quando solicitada."""
        expected = normalized(self.execute(example.expected_sql))
        actual = normalized(self.execute(sql))
        # Counter preserva a quantidade de duplicatas ao desconsiderar a ordem.
        correct = actual == expected if example.ordered else Counter(actual) == Counter(expected)
        return correct, actual, expected

    def metric(self, example, pred, trace=None, pred_name=None, pred_trace=None):
        """Retorna nota 1 ou 0 e uma explicação do acerto ou erro para o GEPA."""
        # Os argumentos adicionais fazem parte da interface de métricas do DSPy.
        try:
            correct, actual, expected = self.assess(example, pred.sql_query)
            feedback = ("Resultado correto." if correct else
                        f"Resultado incorreto. Esperado: {expected}; recebido: {actual}.")
            score = float(correct)
        except (sqlite3.Error, ValueError, AttributeError) as exc:
            score, feedback = 0.0, f"Consulta inválida: {exc}"
        return dspy.Prediction(
            score=score,
            feedback=f"{feedback} SQL de referência: {example.expected_sql}. Use as colunas solicitadas.",
        )


# Usada somente na comparação opcional do custo da explicação.
# A docstring é uma instrução do modelo e foi mantida igual à original.
class ResultToNaturalLanguage(dspy.Signature):
    """Convert a SQL query result into a natural, conversational answer in Portuguese. Ignore the id column"""
    question = dspy.InputField(desc="Pergunta original do usuário")
    sql_query = dspy.InputField(desc="Query SQL executada")
    result = dspy.InputField(desc="Resultado da consulta em formato JSON")
    answer = dspy.OutputField(desc="Resposta em linguagem natural, clara e direta")


def evaluate(program, examples, benchmark, mode, explainer=None):
    """Registra SQL, acerto, erro e duração para cada pergunta."""
    records = []
    for index, example in enumerate(examples, 1):
        started = perf_counter()
        record = {"mode": mode, "question": example.question, "expected_sql": example.expected_sql,
                  "sql": "", "valid": False, "correct": False, "error": ""}
        try:
            prediction = program(dbschema=SCHEMA, question=example.question)
            record["sql"] = prediction.sql_query
            # Tempo de execução inclui a criação do snapshot de avaliação.
            rows = benchmark.execute(prediction.sql_query)
            format_results(rows)
            record["seconds"] = perf_counter() - started
            record["valid"] = True
            correct, actual, expected = benchmark.assess(example, prediction.sql_query)
            record.update(correct=correct, actual=actual, expected=expected)
            # Reutiliza o mesmo SQL e resultado para medir o custo adicional do texto.
            if explainer is not None:
                before = perf_counter()
                try:
                    explanation = explainer(question=example.question, sql_query=prediction.sql_query,
                                            result=json.dumps(rows, ensure_ascii=False, default=str))
                    record["answer"] = explanation.answer
                    record["explanation_seconds"] = perf_counter() - before
                    record["with_explanation_seconds"] = record["seconds"] + record["explanation_seconds"]
                except Exception as exc:
                    record["explanation_error"] = str(exc)
        except Exception as exc:
            record["error"] = str(exc)
            record["seconds"] = perf_counter() - started
        records.append(record)
        print(f"{mode} {index}/{len(examples)}: acerto={record['correct']} tempo={record['seconds']:.2f}s", flush=True)
    return records


def summarize(records):
    """Calcula precisão e médias de tempo, identificando casos com falha."""
    valid = [r for r in records if r["valid"]]
    paired = [r for r in records if "with_explanation_seconds" in r]
    return {
        "questions": len(records),
        "correct": sum(r["correct"] for r in records),
        "accuracy_percent": round(100 * sum(r["correct"] for r in records) / len(records), 2),
        "valid_sql": len(valid), "errors": len(records) - len(valid),
        "mean_seconds_all_attempts": sum(r["seconds"] for r in records) / len(records),
        "mean_seconds_valid_sql": sum(r["seconds"] for r in valid) / len(valid) if valid else None,
        "explanation_pairs": len(paired),
        "paired_mean_without_explanation": sum(r["seconds"] for r in paired) / len(paired) if paired else None,
        "paired_mean_with_explanation": sum(r["with_explanation_seconds"] for r in paired) / len(paired) if paired else None,
    }


def main():
    """Avalia os modos escolhidos no conjunto de teste e exporta os relatórios."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["normal", "gepa", "both"], default="both")
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--with-explanation", action="store_true", help="Mede a chamada adicional da versão com explicação")
    parser.add_argument("--limit", type=int, default=None, help="Ensaio parcial; omita na avaliação final")
    parser.add_argument("--output", type=Path, default=BASE_DIR / "resultados" / "avaliacao.json")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit precisa ser positivo")
    # Desabilita cache para medir novas chamadas ao modelo.
    lm = configure_lm(cache=False)
    benchmark = SQLBenchmark()
    examples = build_examples("test")[:args.limit]
    modes = ["normal", "gepa"] if args.mode == "both" else [args.mode]
    programs = {mode: load_generator(mode, args.program) for mode in modes}
    # Aquecimento excluído da medição. Não usa perguntas de teste ou otimização.
    lm("Responda apenas OK.")
    explainer = dspy.ChainOfThought(ResultToNaturalLanguage) if args.with_explanation else None
    records = []
    # Alterna a ordem entre perguntas para reduzir o efeito de executar todo um modo primeiro.
    for index, example in enumerate(examples):
        order = modes if index % 2 == 0 else list(reversed(modes))
        for mode in order:
            records.extend(evaluate(programs[mode], [example], benchmark, mode,
                                    explainer if mode == "normal" else None))
    summaries = {mode: summarize([r for r in records if r["mode"] == mode]) for mode in modes}
    # Os hashes identificam os arquivos usados no experimento.
    report = {
        "model": lm.model, "database_sha256": benchmark.database_hash,
        "program_sha256": hashlib.sha256(args.program.read_bytes()).hexdigest() if "gepa" in modes else None,
        "lm_config": {"temperature": 0, "max_tokens": lm.kwargs.get("max_tokens"), "cache": False},
        "partial": len(examples) < len(DATASET["test"]),
        "scope": "Geração + execução SQLite local + formatação; sem rede FastAPI, Telegram ou áudio. Uma execução por pergunta/modo.",
        "explanation_scope": "Chamada adicional com a assinatura original e o mesmo SQL/resultado. Não executa bot.py nem avalia a qualidade da explicação.",
        "summary": summaries, "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with args.output.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["mode", "question", "sql", "valid", "correct", "seconds", "error"])
        writer.writeheader()
        writer.writerows({k: r[k] for k in writer.fieldnames} for r in records)
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    print(f"Relatório: {args.output}")


if __name__ == "__main__":
    main()
