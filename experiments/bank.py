"""Check the message bank, or freeze it with --freeze."""

import argparse

from llmtraders import bank

p = argparse.ArgumentParser()
p.add_argument(
    "--freeze", action="store_true", help="write data/messages/bank_v1.frozen.json"
)
a = p.parse_args()

if a.freeze:
    try:
        sha = bank.freeze()
    except FileExistsError as e:
        p.error(str(e))
    print("frozen, sha256:", sha)
else:
    print(bank.check())
