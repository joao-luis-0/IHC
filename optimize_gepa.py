"""Otimiza apenas o gerador SQL da versão sem explicação."""
import argparse
import json
from pathlib import Path

import dspy

from bot_sem_linguagem_natural import BASE_DIR, ReliableSQLGenerator, configure_lm
from sql_evaluation import SQLBenchmark, build_examples


def main():
    """Executa a otimização e salva o programa para uso posterior pelo bot."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="Ensaio pequeno, não avaliação conclusiva")
    parser.add_argument("--max-metric-calls", type=int, default=None)
    parser.add_argument("--output", type=Path, default=BASE_DIR / "resultados")
    args = parser.parse_args()
    # Limite aproximado de avaliações da métrica. A reflexão também usa o LLM.
    budget = args.max_metric_calls if args.max_metric_calls is not None else (12 if args.quick else 100)
    if budget < (8 if args.quick else 30):
        parser.error("Orçamento muito pequeno: use pelo menos 8 no modo quick ou 30 no completo.")
    lm = configure_lm(cache=False)
    benchmark = SQLBenchmark()
    # Treino fornece exemplos para propor melhorias.
    # Validação ajuda a selecionar candidatos. O conjunto de teste fica reservado.
    train = build_examples("train")
    validation = build_examples("validation")
    if args.quick:
        train, validation = train[:3], validation[:2]
    args.output.mkdir(parents=True, exist_ok=True)
    # A métrica retorna nota e feedback textual sobre o SQL.
    # O mesmo Gemma gera SQL e reflete sobre as instruções a melhorar.
    optimizer = dspy.GEPA(
        metric=benchmark.metric,
        auto=None,
        max_metric_calls=budget,
        reflection_lm=lm,
        reflection_minibatch_size=2 if args.quick else 3,
        num_threads=1,
        seed=42,
        track_stats=True,
    )
    # compile executa as tentativas e devolve o programa selecionado pelo GEPA.
    optimized = optimizer.compile(
        ReliableSQLGenerator(), trainset=train, valset=validation
    )
    path = args.output / "gerador_gepa.json"
    # Salva o estado do programa DSPy, incluindo as instruções escolhidas.
    optimized.save(str(path))
    # Registra as condições do experimento para apoiar sua reprodução.
    metadata = {
        "model": lm.model, "quick": args.quick, "max_metric_calls": budget,
        "train_examples": len(train), "validation_examples": len(validation),
        "database_sha256": benchmark.database_hash,
        "note": "Orçamento de avaliações da métrica; não é número de iterações ou chamadas ao LLM.",
    }
    (args.output / "otimizacao.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Programa salvo em {path}")
    print("Avalie antes e depois com: python sql_evaluation.py")


if __name__ == "__main__":
    main()
