"""Reuse AutoWriting's compiler in a child with project-local caches."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auto_writing.web.serve import compile_latex

if __name__ == "__main__":
    main, build, log, result = map(Path, sys.argv[1:])
    compiler, pdf = compile_latex(main, build, log)
    result.write_text(json.dumps({"compiler": compiler, "pdf": str(pdf)}))
