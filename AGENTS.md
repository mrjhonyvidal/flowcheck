# FlowCheck guidance

- Keep the default path in the Python standard library, with no account or network calls.
- Use British English, short explanations and no em dash in prose, CLI text or comments.
- Preserve the synthetic examples, reviewed expected results and explicit illustrative prices. Do not present fixture scores as measured model performance.
- Keep validation, duplicate detection, conflict rollback and evaluation gates explicit. Do not silently repair or discard invalid input.
- Run `python3 -m flowcheck demo` and `python3 -m unittest discover -s tests -v` from the repository root after changing the code or fixtures.
- Keep generated databases in the ignored `runs/` folder. Never commit credentials or private data.
